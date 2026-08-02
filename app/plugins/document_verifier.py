"""Document verifier plugin — thin wrapper exposing the document_ai
pipeline through the same Plugin interface as everything else, so the
graph's plugin-execution node doesn't need special-casing for it."""
from __future__ import annotations

from app.core.schemas import DocumentType, LoanApplication, PluginResult
from app.document_ai.pipeline import process_document


class DocumentVerifierPlugin:
    name = "document_verifier"

    def run(self, application: LoanApplication, **kwargs) -> PluginResult:
        image_bytes: bytes | None = kwargs.get("image_bytes")
        if not image_bytes:
            return PluginResult(
                plugin_name=self.name, success=False, error="No document image provided"
            )

        extraction = process_document(image_bytes)

        return PluginResult(
            plugin_name=self.name,
            success=extraction.is_valid,
            data={
                "doc_type": extraction.doc_type.value,
                "fields": [f.model_dump() for f in extraction.fields],
                "ocr_confidence": extraction.ocr_confidence,
                "summary": extraction.vlm_summary,
            },
            error=None if extraction.is_valid else "; ".join(extraction.validation_errors),
        )
