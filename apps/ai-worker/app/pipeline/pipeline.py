"""The document pipeline: source-to-canonical processing.

Holds the two stage handlers currently wired to the worker queue:

* ``handle_converting``  -> DocumentUploaded  -> unstructured markdown
* ``handle_structuring`` -> DocumentConverted -> canonical JSON + render
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
from storage import (
    MARKDOWN_KIND_CANONICAL,
    MARKDOWN_KIND_CLASSIFICATION,
    MARKDOWN_KIND_PII,
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
    PIIDecision,
    build_document_gate,
    build_pii_artifact,
    build_pii_meta_block,
)
from app.pipeline.context import ProcessingContext
from app.prompts import PromptManager

logger = logging.getLogger("ai_worker")


PII_GATE_JOB_TYPE = "pii_gate"
"""``job_type`` on the failure event a halting PII decision produces."""

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

            pii_result = await self._pii_gate.inspect(normalized, context)
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

            prompt_key = "default"
            if classification.decision is not ClassificationDecision.AMBIGUOUS:
                prompt_key = self._resolver.resolve(
                    classification.document_type,
                    classification.document_subtype,
                )
            canonical_prompt = self._prompt_manager.load_prompt("canonical", prompt_key)

            result = await self._ai_client.extract_canonical(
                markdown=unstructured_markdown,
                system_prompt=canonical_prompt["system_prompt"],
                model=canonical_prompt.get("model", self._settings.ai_model),
                temperature=canonical_prompt.get("temperature", 0.0),
            )
            raw = json.loads(result.content)
            canonical = build_canonical(prompt_key, raw)
            page_count = count_pages(unstructured_markdown)

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
