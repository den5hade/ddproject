import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from canonical import FrontmatterMeta, build_canonical, render_document
from contracts.events import (
    DocumentAnalysisCompleted,
    DocumentConverted,
    DocumentProcessingFailed,
    DocumentUploaded,
)
from storage import (
    MARKDOWN_KIND_CANONICAL,
    MARKDOWN_KIND_STRUCTURED,
    MARKDOWN_KIND_UNSTRUCTURED,
    CloudS3,
    markdown_key,
)

from app.ai_client import AIClient
from app.config import Settings
from app.doc_classifier import classify_document_type
from app.pdf_converter import convert_pdf_to_images
from app.prompts import PromptManager

logger = logging.getLogger("ai_worker")

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
_PDF_EXTENSION = ".pdf"
_SCHEMA_VERSION = "1.0.0"
_PIPELINE_VERSION = "1.0.0"

_PAGE_MARKER_RE = re.compile(r"^## Page (\d+)", re.MULTILINE)


def _count_pages(markdown: str) -> int:
    """Count the number of rendered image pages from their ``## Page N`` markers."""
    markers = _PAGE_MARKER_RE.findall(markdown or "")
    if not markers:
        return 1
    try:
        return max(int(number) for number in markers)
    except ValueError:
        return len(markers)


class DocumentProcessor:
    """Convert documents to markdown and structure it via an LLM."""

    def __init__(
        self,
        s3: CloudS3,
        publisher,
        settings: Settings,
    ) -> None:
        self._s3 = s3
        self._publisher = publisher
        self._settings = settings
        self._ai_client = AIClient(settings)
        self._prompt_manager = PromptManager(settings.prompts_dir)

    async def handle_converting(self, event: DocumentUploaded) -> None:
        """Handle PDF/image → unstructured markdown conversion."""
        logger.info("converting_started document_id=%s", event.document_id)

        try:
            images = await self._load_images(event.storage_key)

            ocr_prompt = self._prompt_manager.load_prompt("ocr")
            markdown_parts: list[str] = []
            for index, image_bytes in enumerate(images):
                logger.info(
                    "processing_page page=%s total=%s",
                    index + 1,
                    len(images),
                )
                text = await self._ai_client.extract_text_from_image(
                    image_bytes=image_bytes,
                    system_prompt=ocr_prompt["system_prompt"],
                    model=ocr_prompt.get("model", self._settings.ai_model),
                    temperature=ocr_prompt.get("temperature", 0.1),
                )
                markdown_parts.append(f"## Page {index + 1}\n\n{text}")

            unstructured_markdown = "\n\n---\n\n".join(markdown_parts)

            unstructured_key = self._build_key(event, MARKDOWN_KIND_UNSTRUCTURED)
            await asyncio.to_thread(
                self._s3.upload_bytes,
                unstructured_markdown.encode("utf-8"),
                unstructured_key,
                "text/markdown",
            )
            logger.info("unstructured_markdown_uploaded key=%s", unstructured_key)

            await self._publish(
                "document.converted",
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
        """Handle unstructured markdown → canonical JSON + structured render."""
        logger.info("structuring_started document_id=%s", event.document_id)

        try:
            markdown_bytes = await asyncio.to_thread(
                self._s3.download_bytes, event.output_storage_key
            )
            unstructured_markdown = markdown_bytes.decode("utf-8")

            client_type = getattr(event, "document_type", None) or ""
            canonical_doc_type = classify_document_type(unstructured_markdown, client_type)
            canonical_prompt = self._prompt_manager.load_prompt("canonical", canonical_doc_type)

            result = await self._ai_client.extract_canonical(
                markdown=unstructured_markdown,
                system_prompt=canonical_prompt["system_prompt"],
                model=canonical_prompt.get("model", self._settings.ai_model),
                temperature=canonical_prompt.get("temperature", 0.0),
            )
            raw = json.loads(result.content)
            canonical = build_canonical(canonical_doc_type, raw)
            page_count = _count_pages(unstructured_markdown)

            meta = self._build_frontmatter(
                event,
                canonical,
                canonical_prompt,
                result.usage,
                client_type=client_type,
                page_count=page_count,
            )

            canonical_key = self._build_canonical_key(event)
            structured_key = self._build_key(event, MARKDOWN_KIND_STRUCTURED)

            canonical_json = json.dumps(
                canonical.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
            structured_markdown = render_document(canonical, meta)

            await asyncio.to_thread(
                self._s3.upload_bytes,
                canonical_json.encode("utf-8"),
                canonical_key,
                "application/json",
            )
            await asyncio.to_thread(
                self._s3.upload_bytes,
                structured_markdown.encode("utf-8"),
                structured_key,
                "text/markdown",
            )
            logger.info(
                "structured_uploaded canonical_key=%s structured_key=%s",
                canonical_key,
                structured_key,
            )

            await self._publish(
                "document.analysis.completed",
                DocumentAnalysisCompleted(
                    event_id=uuid4(),
                    document_id=event.document_id,
                    document_version_id=event.document_version_id,
                    patient_id=event.patient_id,
                    extraction_id=uuid4(),
                    schema_name=canonical.schema_name,
                    schema_version=_SCHEMA_VERSION,
                    status="succeeded",
                    confidence=1.0,
                    data={
                        **canonical.model_dump(mode="json", by_alias=True),
                        "canonical_key": canonical_key,
                        "structured_key": structured_key,
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
    ) -> FrontmatterMeta:
        """Compose the Python-built YAML metadata envelope around a canonical doc."""
        model = prompt.get("model", self._settings.ai_model)
        prompt_version = str(prompt.get("prompt_version") or _PIPELINE_VERSION)

        source = {
            "object_key": event.output_storage_key,
            "filename": getattr(event, "original_filename", None),
            "mime_type": getattr(event, "mime_type", None),
            "sha256": getattr(event, "sha256", None),
        }
        if client_type:
            source["declared_type"] = client_type

        return FrontmatterMeta(
            doc_id=str(event.document_id),
            type=canonical.type,
            subtype=canonical.subtype,
            document={
                "language": canonical.language,
                "document_date": canonical.document_date,
                "page_count": page_count,
            },
            source=source,
            processing={
                "pipeline_version": _PIPELINE_VERSION,
                "extraction": {
                    "model": model,
                    "prompt_version": prompt_version,
                    "schema": canonical.schema_name,
                    "schema_version": _SCHEMA_VERSION,
                    "tokens": usage,
                    "cost_usd": 0.0,
                },
            },
            validation={
                "status": "valid",
                "schema_valid": True,
                "warnings": [],
                "validated_at": datetime.now(UTC).isoformat(),
            },
        )

    async def _load_images(self, storage_key: str) -> list[bytes]:
        """Download the input from S3 and return a list of image blobs.

        For a PDF the pages are rendered to images; for an image upload the
        original blob is returned directly.
        """
        file_bytes = await asyncio.to_thread(self._s3.download_bytes, storage_key)
        extension = os.path.splitext(storage_key)[1].lower()

        if extension == _PDF_EXTENSION:
            return await asyncio.to_thread(
                convert_pdf_to_images,
                file_bytes,
                self._settings.pdf_dpi,
                self._settings.pdf_format,
            )
        if extension in _IMAGE_EXTENSIONS:
            return [file_bytes]
        raise ValueError(f"unsupported document extension: {extension}")

    def _build_key(self, event, kind: str) -> str:
        if not event.document_version_id:
            return ""
        return markdown_key(
            tenant_id=self._settings.s3_tenant_id,
            patient_id=event.patient_id,
            document_id=event.document_id,
            version_id=event.document_version_id,
            kind=kind,
        )

    def _build_canonical_key(self, event) -> str:
        if not event.document_version_id:
            return ""
        return markdown_key(
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
    ) -> None:
        logger.warning(
            "processing_failed document_id=%s job_type=%s message=%s",
            document_id,
            job_type,
            error_message,
        )
        await self._publish(
            "document.processing.failed",
            DocumentProcessingFailed(
                event_id=uuid4(),
                document_id=document_id,
                document_version_id=version_id,
                patient_id=patient_id,
                job_type=job_type,
                error_code="PROCESSING_ERROR",
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
