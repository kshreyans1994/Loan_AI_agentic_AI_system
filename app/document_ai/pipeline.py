"""
Document processing pipeline: OCR -> VLM -> structured, validated extraction.

This is called from the DocumentProcessing node in the LangGraph pipeline.
Kept separate from the graph itself so it can be unit-tested with sample
images independent of any agent orchestration.
"""
from __future__ import annotations

import re

from app.core.config import get_settings
from app.core.schemas import DocumentExtraction, DocumentType, ExtractedField
from app.document_ai.ocr import get_ocr_engine
from app.document_ai.vlm import get_vlm_client

# Lightweight format checks — not a substitute for real KYC verification,
# but enough to catch obviously malformed input before it reaches a human
# or an eligibility decision.
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
AADHAAR_PATTERN = re.compile(r"^\d{4}\s?\d{4}\s?\d{4}$")


def _validate_fields(doc_type: DocumentType, fields: list[ExtractedField]) -> list[str]:
    errors: list[str] = []
    field_map = {f.name: f.value for f in fields}

    if doc_type == DocumentType.PAN:
        pan = field_map.get("pan_number", "")
        if not PAN_PATTERN.match(pan.replace(" ", "").upper()):
            errors.append("PAN number does not match expected format (AAAAA9999A)")

    elif doc_type == DocumentType.AADHAAR:
        aadhaar = field_map.get("aadhaar_number", "")
        if not AADHAAR_PATTERN.match(aadhaar.strip()):
            errors.append("Aadhaar number does not match expected 12-digit format")

    elif doc_type == DocumentType.SALARY_SLIP:
        if "monthly_income" not in field_map and "net_pay" not in field_map:
            errors.append("Could not locate income figure on salary slip")

    return errors


def process_document(image_bytes: bytes, ocr_confidence_threshold: float | None = None) -> DocumentExtraction:
    settings = get_settings()
    threshold = ocr_confidence_threshold or settings.ocr_confidence_threshold

    ocr_engine = get_ocr_engine()
    ocr_result = ocr_engine.extract(image_bytes)

    vlm_client = get_vlm_client()
    vlm_output = vlm_client.analyze_document(image_bytes, ocr_result.text)

    try:
        doc_type = DocumentType(vlm_output.get("doc_type", "unknown"))
    except ValueError:
        doc_type = DocumentType.UNKNOWN

    fields = [
        ExtractedField(
            name=f.get("name", ""),
            value=str(f.get("value", "")),
            confidence=float(f.get("confidence", 0.0)),
        )
        for f in vlm_output.get("fields", [])
    ]

    validation_errors = _validate_fields(doc_type, fields)
    quality_flags = vlm_output.get("quality_flags", [])

    is_valid = (
        ocr_result.mean_confidence >= threshold
        and not validation_errors
        and not quality_flags
        and doc_type != DocumentType.UNKNOWN
    )

    if ocr_result.mean_confidence < threshold:
        validation_errors.append(
            f"OCR confidence {ocr_result.mean_confidence:.2f} below threshold {threshold:.2f} — "
            "image may be blurry or low resolution"
        )

    return DocumentExtraction(
        doc_type=doc_type,
        raw_text=ocr_result.text,
        fields=fields,
        ocr_confidence=ocr_result.mean_confidence,
        vlm_summary=vlm_output.get("summary"),
        is_valid=is_valid,
        validation_errors=validation_errors + [f"quality: {q}" for q in quality_flags],
    )
