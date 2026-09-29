"""The document pipeline: source-to-canonical processing.

Holds the two stage handlers currently wired to the worker queue:

* ``handle_converting``  -> DocumentUploaded  -> unstructured markdown
* ``handle_structuring`` -> DocumentConverted -> canonical JSON + render

Boundaries this pipeline does not gate
-------------------------------------

**R1, stated here because it is the gap most likely to be read as covered.**
The PII gate consumes ``marker.md`` and ``marker.md`` is what
``handle_converting``'s ``self._ocr.to_markdown(images, ocr_prompt)``
**produces**. The image is therefore handed to the provider *before* any gate
has run, and no setting in this file changes that. This is not an oversight to
be fixed by wiring the gate earlier: the gate has nothing to read until OCR has
produced text, and a document that is only an image has no markdown at all.

Three consequences worth stating rather than leaving implied:

1. ``ai_base_url``, ``ai_model`` and the credentials are the *same* settings for
   OCR and for extraction. Setting ``llm_mode=external_llm`` therefore moves the
   extraction call to an untrusted boundary and leaves the OCR call exactly
   where it was, still receiving the full page image. Phase 15 redacts the text;
   it does not protect the image.
2. The mitigation is a control *before* the OCR call — image classification, a
   trusted in-house OCR deployment, or refusing image documents on an external
   boundary. That is a different control with a different threat model, and it
   is out of M5's scope rather than silently included in it.
3. What this pipeline *can* say is that its text boundary is now real: with
   ``llm_mode=external_llm`` the extraction call receives redacted markdown and
   ``redacted.md`` records what crossed. ``DocumentPipeline.__init__`` warns at
   start-up when that mode is selected, so an operator sees the limit next to
   the switch rather than having to find it here.
"""

import json
import logging
from uuid import UUID, uuid4

from canonical import ClassificationMeta, build_canonical, render_document
from contracts.events import (
    DocumentAnalysisCompleted,
    DocumentConverted,
    DocumentProcessingFailed,
    DocumentUploaded,
)
from pydantic import ValidationError
from storage import (
    MARKDOWN_KIND_CANONICAL,
    MARKDOWN_KIND_CLASSIFICATION,
    MARKDOWN_KIND_PII,
    MARKDOWN_KIND_REDACTED,
    MARKDOWN_KIND_STRUCTURED,
    MARKDOWN_KIND_UNSTRUCTURED,
)

from app.artifacts import (
    build_markdown_key,
    download_text,
    upload_text,
)
from app.canonical import (
    PIPELINE_VERSION,
    SCHEMA_VERSION,
    build_frontmatter_meta,
    build_source_meta,
    build_validation_meta,
)
from app.classification import (
    ClassificationDecision,
    MarkdownNormalizer,
    RegistrySchemaResolver,
    RuleBasedClassificationService,
    build_classification_artifact,
)
from app.config.settings import Settings
from app.ingestion import OcrEngine, count_pages, load_images
from app.llm import AIClient
from app.messaging import (
    ROUTING_KEY_ANALYSIS_COMPLETED,
    ROUTING_KEY_CONVERTED,
    ROUTING_KEY_PROCESSING_FAILED,
)
from app.pii import (
    HALTING_DECISIONS,
    PIIAction,
    PIIDecision,
    PIIDecisionError,
    PIIRedactionError,
    build_canonical_guard,
    build_document_gate,
    build_pii_artifact,
    build_pii_meta_block,
)
from app.pipeline.context import ProcessingContext
from app.prompts import PromptManager

logger = logging.getLogger("ai_worker")


PII_GATE_JOB_TYPE = "pii_gate"
"""``job_type`` on the failure event a halting PII decision produces."""

PII_CANONICAL_GATE_JOB_TYPE = "pii_canonical_guard"
"""``job_type`` for a halting **contour-2** decision — a second value, not a reuse.

Sharing :data:`PII_GATE_JOB_TYPE` would make the two contours indistinguishable
in the failure queue, and the distinction is the useful one: ``pii_gate`` means
the *source* document was refused before extraction, ``pii_canonical_guard``
means extraction produced something that must not be stored. The second is an
upstream prompt defect, and an operator triaging it needs to know that without
cross-referencing which stage produced the failure.
"""

PII_DECISION_ERROR_CODES: dict[PIIDecision, str] = {
    PIIDecision.REVIEW: "PII_REVIEW_REQUIRED",
    PIIDecision.BLOCK: "PII_BLOCKED",
}
"""Why a document stopped, as an ``error_code``.

The plan writes the two halting outcomes as ``processing_status =
needs_review`` and ``processing failure`` (ORDER §0, IMPL_PLAN Phase 11). There
is no ``processing_status`` field to carry either: ``DocumentAnalysisCompleted.status``
is ``Literal["succeeded", "failed"]`` and ``DocumentProcessingFailed`` has no
``data``, and M5 is explicitly forbidden from changing a cross-package event
contract (ORDER §13.6). So the distinction is made in ``error_code``, which
exists on the contract already and exists precisely to say *why* a job failed.

``REVIEW`` and ``BLOCK`` need different codes because they are different events
for whoever clears the queue: one is a document waiting for a person, the other
is a document that must not be written down at all. Sharing one code would
erase exactly the distinction the plan asks for.

The key set is asserted in ``test_pipeline.py`` to equal
:data:`~app.pii.gate.HALTING_DECISIONS`, so a new halting decision fails the
suite instead of raising ``KeyError`` at the worst possible moment — on a real
document, mid-request, after a scan that must be acted on.
"""


def _has_redaction(guard_result) -> bool:
    """Whether the guard result asks for any leaf to be masked.

    Checked against ``actions`` rather than ``violations``, because those answer
    different questions: a payload whose only finding is an ``ALLOW``-actioned
    doctor name *has* violations and needs *no* rewrite. Going by violations
    would push every such document through a dump → sanitize → re-validate
    round trip it did not need, and a round trip that can fail (R4) would then be
    able to fail a perfectly good document.
    """
    return PIIAction.REDACT in set(guard_result.actions.values())


class DocumentPipeline:
    """Convert documents to markdown and structure it via an LLM."""

    def __init__(
        self,
        s3,
        publisher,
        settings: Settings,
    ) -> None:
        self._s3 = s3
        self._publisher = publisher
        self._settings = settings
        self._ai_client = AIClient(settings)
        self._prompt_manager = PromptManager(settings.prompts_dir)
        self._ocr = OcrEngine(self._ai_client, settings.ai_model)
        self._normalizer = MarkdownNormalizer()
        self._classifier = RuleBasedClassificationService()
        self._resolver = RegistrySchemaResolver()
        # Constructed here, at start-up, so a deployment with no
        # PII_FINGERPRINT_SECRET raises before it consumes a single message
        # rather than failing every document with the same exception.
        self._pii_gate = build_document_gate(settings)
        # Contour 2, same start-up choke point and same chain. Built from the
        # same settings so the two contours cannot disagree about which
        # detectors run — the Phase 11 subset defect (risk R13) in the place
        # the observed leak actually is.
        self._pii_guard = build_canonical_guard(settings)
        if settings.llm_mode == "external_llm":
            # R1. The OCR call in handle_converting runs before every gate and
            # consumes the page image; `llm_mode` moves the *extraction* call to
            # an untrusted boundary and does nothing about that one. Said at
            # start-up, where the operator is choosing the mode, because the
            # alternative is discovering it from this file's docstring after a
            # document has already been sent.
            logger.warning(
                "pii_boundary_warning document_id=- llm_mode=external_llm: extraction "
                "redacts before the model call, but OCR (handle_converting) is upstream "
                "of the gate and still sends the page image to the same ai_base_url. "
                "See 'Boundaries this pipeline does not gate' in app/pipeline/pipeline.py."
            )

    async def handle_converting(self, event: DocumentUploaded) -> None:
        """Handle PDF/image -> unstructured markdown conversion."""
        logger.info("converting_started document_id=%s", event.document_id)

        try:
            images = await load_images(
                self._s3,
                event.storage_key,
                dpi=self._settings.pdf_dpi,
                format=self._settings.pdf_format,
            )

            ocr_prompt = self._prompt_manager.load_prompt("ocr")
            unstructured_markdown = await self._ocr.to_markdown(images, ocr_prompt)

            unstructured_key = self._build_key(event, MARKDOWN_KIND_UNSTRUCTURED)
            await upload_text(
                self._s3,
                unstructured_markdown,
                unstructured_key,
                "text/markdown",
            )
            logger.info("unstructured_markdown_uploaded key=%s", unstructured_key)

            await self._publish(
                ROUTING_KEY_CONVERTED,
                DocumentConverted(
                    event_id=uuid4(),
                    document_id=event.document_id,
                    document_version_id=event.document_version_id,
                    patient_id=event.patient_id,
                    output_storage_key=unstructured_key,
                    original_filename=getattr(event, "original_filename", ""),
                    mime_type=getattr(event, "mime_type", ""),
                    sha256=getattr(event, "sha256", ""),
                    document_type=getattr(event, "document_type", "other"),
                ),
            )
            logger.info("converting_completed document_id=%s", event.document_id)

        except Exception as exc:  # noqa: BLE001
            logger.exception("converting_failed document_id=%s", event.document_id)
            await self._fail(
                event.document_id,
                event.document_version_id,
                event.patient_id,
                "pdf_conversion",
                str(exc),
            )

    async def handle_structuring(self, event: DocumentConverted) -> None:
        """Handle unstructured markdown -> canonical JSON + structured render."""
        logger.info("structuring_started document_id=%s", event.document_id)

        try:
            unstructured_markdown = await download_text(self._s3, event.output_storage_key)

            client_type = getattr(event, "document_type", None) or ""
            context = ProcessingContext(
                document_id=event.document_id,
                document_version_id=event.document_version_id,
                patient_id=event.patient_id,
                client_type=client_type,
            )
            normalized = self._normalizer.normalize(
                unstructured_markdown,
                metadata={"client_type": client_type},
            )
            classification = await self._classifier.classify(normalized, context)

            gate_result = await self._pii_gate.evaluate_document(normalized, context)
            pii_result = gate_result.scan_result
            if pii_result.decision in HALTING_DECISIONS:
                # No artifact, no event data, no extraction. The decision is
                # logged and published as a failure; nothing derived from this
                # document is written anywhere.
                logger.warning(
                    "pii_gate_halted document_id=%s decision=%s risk_level=%s "
                    "findings_count=%s findings=%s reasons=%s",
                    event.document_id,
                    pii_result.decision.value,
                    pii_result.risk_level.value,
                    pii_result.findings_count,
                    pii_result.category_counts,
                    pii_result.reasons,
                )
                await self._fail(
                    event.document_id,
                    event.document_version_id,
                    event.patient_id,
                    PII_GATE_JOB_TYPE,
                    f"PII gate {pii_result.decision.value}: {pii_result.reasons}",
                    error_code=PII_DECISION_ERROR_CODES[pii_result.decision],
                )
                return

            # Uploaded before the extraction call, not alongside the other
            # artifacts at the end. The gate has already run and its verdict is
            # the audit record of it; if the LLM call then fails, that verdict
            # is still on disk instead of being lost with the failed request.
            pii_key = self._build_key(event, MARKDOWN_KIND_PII)
            await upload_text(
                self._s3,
                build_pii_artifact(result=pii_result),
                pii_key,
                "application/json",
            )
            logger.info(
                "pii_result_uploaded key=%s decision=%s", pii_key, pii_result.decision.value
            )

            # Phase 15. Redact **before** the extraction call and upload the
            # result before it too, so if the LLM call then fails, both the
            # verdict and the text that would have been sent are on disk.
            #
            # `redact` returns `unstructured_markdown` *by identity* when no
            # category is REDACT-actioned, and the pipeline observes that rather
            # than re-deriving "was this redacted" from the categories: a second
            # place deciding the same question is a second place able to answer
            # it differently, and the difference would be a document sent
            # unredacted to an untrusted provider.
            redacted = await self._redact(event, unstructured_markdown, gate_result)
            if redacted is None:
                return
            redacted_markdown, redacted_key = redacted
            prompt_key = "default"
            if classification.decision is not ClassificationDecision.AMBIGUOUS:
                prompt_key = self._resolver.resolve(
                    classification.document_type,
                    classification.document_subtype,
                )
            canonical_prompt = self._prompt_manager.load_prompt("canonical", prompt_key)

            result = await self._ai_client.extract_canonical(
                markdown=redacted_markdown,
                system_prompt=canonical_prompt["system_prompt"],
                model=canonical_prompt.get("model", self._settings.ai_model),
                temperature=canonical_prompt.get("temperature", 0.0),
            )
            raw = json.loads(result.content)
            canonical = build_canonical(prompt_key, raw)
            # The original, not the redacted text: the page count describes the
            # document, and the document is what was uploaded and what the
            # operator will compare `redacted.md` against.
            page_count = count_pages(unstructured_markdown)

            # Contour 2. Runs after build_canonical and **replaces** the binding
            # below, so all three consumers -- canonical.json, render_document
            # and event data -- read the sanitized object. Sanitizing a copy, or
            # running this after the dump, leaves at least one surface leaking
            # while the guard's own tests stay green: the observed leak reached
            # three sinks from one object, so fixing one is not fixing any.
            canonical = await self._guard_canonical(event, canonical)
            if canonical is None:
                return

            classification_meta = self._build_classification_meta(classification)
            # One build, used for the frontmatter *and* the event payload, so
            # the two surfaces cannot disagree about what the gate decided.
            pii_meta = build_pii_meta_block(result=pii_result)
            meta = self._build_frontmatter(
                event,
                canonical,
                canonical_prompt,
                result.usage,
                client_type=client_type,
                page_count=page_count,
                classification=classification_meta,
                pii=pii_meta,
            )

            classification_key = self._build_key(event, MARKDOWN_KIND_CLASSIFICATION)
            canonical_key = self._build_canonical_key(event)
            structured_key = self._build_key(event, MARKDOWN_KIND_STRUCTURED)

            classification_artifact = self._build_classification_artifact(
                classification,
                context,
                canonical,
                prompt_key,
                canonical_prompt,
                classification_key,
            )
            await upload_text(
                self._s3,
                classification_artifact,
                classification_key,
                "application/json",
            )
            logger.info("classification_uploaded key=%s", classification_key)

            canonical_json = json.dumps(
                canonical.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
            structured_markdown = render_document(canonical, meta)

            await upload_text(
                self._s3,
                canonical_json,
                canonical_key,
                "application/json",
            )
            await upload_text(
                self._s3,
                structured_markdown,
                structured_key,
                "text/markdown",
            )
            logger.info(
                "structured_uploaded canonical_key=%s structured_key=%s",
                canonical_key,
                structured_key,
            )

            await self._publish(
                ROUTING_KEY_ANALYSIS_COMPLETED,
                DocumentAnalysisCompleted(
                    event_id=uuid4(),
                    document_id=event.document_id,
                    document_version_id=event.document_version_id,
                    patient_id=event.patient_id,
                    extraction_id=uuid4(),
                    schema_name=canonical.schema_name,
                    schema_version=SCHEMA_VERSION,
                    status="succeeded",
                    confidence=classification.confidence,
                    data={
                        **canonical.model_dump(mode="json", by_alias=True),
                        "canonical_key": canonical_key,
                        "structured_key": structured_key,
                        "classification_key": classification_key,
                        "classification": classification_meta.model_dump(mode="json"),
                        "pii": pii_meta,
                        "pii_key": pii_key,
                        # Optional, and deliberately not a permanent nullable
                        # key: at the trusted destination — the default, and
                        # essentially every run — nothing is redacted and there
                        # is no artifact to point at. Adding a key that is null
                        # on 99% of documents to a cross-package event contract
                        # (R11) would be a schema change for a non-event.
                        **({"redacted_key": redacted_key} if redacted_key else {}),
                    },
                ),
            )
            logger.info("structuring_completed document_id=%s", event.document_id)

        except Exception as exc:  # noqa: BLE001
            logger.exception("structuring_failed document_id=%s", event.document_id)
            await self._fail(
                event.document_id,
                event.document_version_id,
                event.patient_id,
                "markdown_structuring",
                str(exc),
            )

    async def _guard_canonical(self, event, canonical):
        """Contour 2: inspect the built payload and return the model to persist.

        Three outcomes, and the caller branches only on ``None``:

        * **clean or nothing to redact** — the original object, returned by
          identity. No copy, no re-validation, because a document with only an
          ``ALLOW``-actioned finding (a doctor name, a clinic) must not be able
          to fail a rebuild it did not need: a guard that can break a good
          document is a guard whose halts stop meaning anything.
        * **redacted** — a rebuilt model. Sanitization is a rebuild rather than
          a mutation (§7 decision 7), so the returned object is a *different*
          one, which is why this method's return value has to be assigned back
          and a local copy cannot do.
        * **must not be persisted** — ``None``, with the failure already
          published. No canonical JSON, no structured markdown, no completed
          event: the guard runs before all three. (The contour-1
          ``pii_result.json`` is already on disk by this point and stays there —
          it is the gate's own audit record and carries no patient text, so
          "nothing was uploaded" would be the wrong claim to make here.)

        Args:
            event: The incoming event, for the document ids and the tenant-keyed
                failure.
            canonical: The model ``build_canonical`` produced. Never mutated.

        Returns:
            The model to persist, or ``None`` if the document is refused.

        Raises:
            Nothing. Every failure mode — a halting decision, a policy that
            cannot decide, a re-validation the sanitized payload does not
            satisfy — is turned into a published failure and a ``None``, because
            a raise here would be caught by the handler above and reported as a
            markdown-structuring error, losing the fact that a security control
            stopped the document.
        """
        try:
            payload = canonical.model_dump(mode="json", by_alias=True)
            guard_result = self._pii_guard.evaluate_payload(payload)
        except PIIDecisionError as exc:
            # The guard could not produce a verdict at all. Fail closed, and
            # fail with the contour-2 job type so it is not filed as a
            # structuring bug.
            return await self._fail_canonical_guard(event, str(exc))

        if guard_result.decision in HALTING_DECISIONS:
            logger.warning(
                "pii_canonical_guard_halted document_id=%s decision=%s risk_level=%s "
                "violations=%s reasons=%s",
                event.document_id,
                guard_result.decision.value,
                guard_result.risk_level.value,
                [(v.field_path, v.category.value) for v in guard_result.violations],
                guard_result.reasons,
            )
            return await self._fail_canonical_guard(
                event,
                f"PII canonical guard {guard_result.decision.value}: {guard_result.reasons}",
                error_code=PII_DECISION_ERROR_CODES[guard_result.decision],
            )

        if not _has_redaction(guard_result):
            # Findings exist but nothing is REDACT-actioned — a doctor name, a
            # clinic, a clinical fact. The payload persists as the model built
            # it, and the record that anything was seen is the log line, not a
            # rewrite of a document that did not need one.
            if guard_result.violations:
                logger.info(
                    "pii_canonical_guard_recorded document_id=%s decision=%s violations=%s",
                    event.document_id,
                    guard_result.decision.value,
                    [(v.field_path, v.category.value) for v in guard_result.violations],
                )
            return canonical

        logger.info(
            "pii_canonical_guard_sanitized document_id=%s decision=%s risk_level=%s violations=%s",
            event.document_id,
            guard_result.decision.value,
            guard_result.risk_level.value,
            [(v.field_path, v.category.value) for v in guard_result.violations],
        )
        try:
            sanitized = self._pii_guard.sanitize(payload, guard_result)
            return type(canonical).model_validate(sanitized)
        except (ValidationError, PIIRedactionError) as exc:
            # A mask the schema rejects, or a span the redactor could not
            # resolve. Either way the sanitized object is not trustworthy, and
            # the *unsanitized* one must never be written to close the gap --
            # that fallback is the leak with extra steps. R4 anticipated this
            # case, and it is a loud failure by design.
            return await self._fail_canonical_guard(
                event,
                f"canonical sanitization failed closed: {exc}",
                error_code="PII_CANONICAL_GUARD_FAILED",
            )

    async def _redact(self, event, markdown: str, gate_result) -> tuple[str, str | None] | None:
        """Return ``(text_to_send, redacted_key)``, or ``None`` if the document stops.

        The pre-extraction half of the gate, and the reason
        :meth:`DefaultPIIGate.evaluate_document` exists. Three outcomes:

        * **nothing is ``REDACT``-actioned** — the input string, returned *by
          identity*, and no key. At the trusted destination this is every
          document the platform processes, so a ``redacted.md`` written here
          would be an artifact per document recording a non-event, and the
          event's ``redacted_key`` would be null on essentially every run. The
          identity is how the caller tells the two cases apart without
          re-deriving the policy condition.
        * **redacted** — the redacted text and the key it was uploaded under.
          The artifact holds placeholders only, never a raw value, which is
          what makes it safe to store and simultaneously the reason it is
          evidence: it is what left. A log line would not be — it is rotated,
          lossy, and holds no text to begin with.
        * **redaction failed** — ``None``, with the failure already published,
          and **no extraction call**: a document whose PII could not be removed
          is a document that must not be sent. The already-uploaded
          ``pii_result.json`` stays, because it is the scan's own audit record.

        Args:
            event: The incoming event, for the ids and the tenant-keyed failure.
            markdown: The text as it would be sent. Never modified.
            gate_result: The evaluation this redaction belongs to.

        Returns:
            ``(text_to_send, redacted_key_or_None)``, or ``None`` to halt.

        Raises:
            Nothing. A :class:`PIIRedactionError` is turned into a published
                failure and a ``None``, because a raise would be caught by the
                handler above and reported as ``markdown_structuring`` —
                losing the fact that a security control stopped the document.
        """
        try:
            redacted = self._pii_gate.redact(markdown, gate_result)
        except PIIRedactionError as exc:
            logger.warning("pii_redaction_failed document_id=%s message=%s", event.document_id, exc)
            await self._fail(
                event.document_id,
                event.document_version_id,
                event.patient_id,
                PII_GATE_JOB_TYPE,
                f"PII redaction failed closed: {exc}",
                error_code="PII_REDACTION_FAILED",
            )
            return None

        if redacted is markdown:
            return markdown, None

        redacted_key = self._build_key(event, MARKDOWN_KIND_REDACTED)
        await upload_text(self._s3, redacted, redacted_key, "text/markdown")
        # Not a new messaging event and not a new artifact type: the record of
        # what was removed is the policy's per-category warnings, which already
        # reach pii_result.json and the §4.7 frontmatter/event block. This line
        # is the searchable version of the same fact.
        logger.info(
            "pii_redacted document_id=%s key=%s destination=%s categories=%s",
            event.document_id,
            redacted_key,
            gate_result.scan_result.destination.value,
            sorted(
                {
                    finding.category.value
                    for finding in gate_result.findings
                    if gate_result.actions.get(finding.category) is PIIAction.REDACT
                }
            ),
        )
        return redacted, redacted_key

    async def _fail_canonical_guard(self, event, message: str, error_code: str = "PII_GUARD_ERROR"):
        """Publish a contour-2 failure and return ``None`` for the caller."""
        logger.warning(
            "pii_canonical_guard_failed document_id=%s message=%s", event.document_id, message
        )
        await self._fail(
            event.document_id,
            event.document_version_id,
            event.patient_id,
            PII_CANONICAL_GATE_JOB_TYPE,
            message,
            error_code=error_code,
        )
        return None

    def _build_frontmatter(
        self,
        event,
        canonical,
        prompt: dict,
        usage: dict,
        client_type: str | None = None,
        page_count: int | None = None,
        classification: ClassificationMeta | None = None,
        pii: dict | None = None,
    ):
        """Compose the Python-built YAML metadata envelope around a canonical doc."""
        model = prompt.get("model", self._settings.ai_model)
        prompt_version = str(prompt.get("prompt_version") or PIPELINE_VERSION)

        return build_frontmatter_meta(
            document_id=event.document_id,
            canonical=canonical,
            source=build_source_meta(event, declared_type=client_type),
            page_count=page_count,
            model=model,
            prompt_version=prompt_version,
            tokens=usage,
            validation=build_validation_meta(),
            classification=classification,
            pii=pii,
        )

    def _build_classification_meta(self, classification) -> ClassificationMeta:
        """Project the classification result into the frontmatter metadata block."""
        return ClassificationMeta(
            document_type=classification.document_type.value,
            document_subtype=classification.document_subtype,
            confidence=classification.confidence,
            confidence_level=classification.confidence_level.value,
            decision=classification.decision.value,
            method=classification.method,
            classifier_version=classification.classifier_version,
            reasons=classification.reasons,
            warnings=classification.warnings,
        )

    def _build_classification_artifact(
        self,
        classification,
        context: ProcessingContext,
        canonical,
        prompt_key: str,
        prompt: dict,
        classification_key: str,
    ) -> str:
        """Serialize the classification 2.0 verdict + provenance artifact."""
        model = prompt.get("model", self._settings.ai_model)
        prompt_version = str(prompt.get("prompt_version") or PIPELINE_VERSION)
        return build_classification_artifact(
            classification=classification,
            prompt_key=prompt_key,
            schema_name=canonical.schema_name,
            prompt_version=prompt_version,
            model=model,
            processing={
                "processing_id": context.processing_id,
                "document_id": str(context.document_id),
                "document_version_id": str(context.document_version_id)
                if context.document_version_id
                else None,
                "patient_id": str(context.patient_id),
                "client_type": context.client_type,
                "schema_version": SCHEMA_VERSION,
                "artifact_key": classification_key,
            },
        )

    def _build_key(self, event, kind: str) -> str:
        return build_markdown_key(
            tenant_id=self._settings.s3_tenant_id,
            patient_id=event.patient_id,
            document_id=event.document_id,
            version_id=event.document_version_id,
            kind=kind,
        )

    def _build_canonical_key(self, event) -> str:
        return build_markdown_key(
            tenant_id=self._settings.s3_tenant_id,
            patient_id=event.patient_id,
            document_id=event.document_id,
            version_id=event.document_version_id,
            kind=MARKDOWN_KIND_CANONICAL,
        )

    async def _fail(
        self,
        document_id: UUID,
        version_id: UUID | None,
        patient_id: UUID,
        job_type: str,
        error_message: str,
        error_code: str = "PROCESSING_ERROR",
    ) -> None:
        logger.warning(
            "processing_failed document_id=%s job_type=%s error_code=%s message=%s",
            document_id,
            job_type,
            error_code,
            error_message,
        )
        await self._publish(
            ROUTING_KEY_PROCESSING_FAILED,
            DocumentProcessingFailed(
                event_id=uuid4(),
                document_id=document_id,
                document_version_id=version_id,
                patient_id=patient_id,
                job_type=job_type,
                error_code=error_code,
                error_message=error_message,
            ),
        )

    async def _publish(self, routing_key: str, event) -> None:
        if self._publisher is None:
            logger.warning(
                "event_dropped routing_key=%s document_id=%s (broker unavailable)",
                routing_key,
                event.document_id,
            )
            return
        await self._publisher.publish(routing_key, event)
