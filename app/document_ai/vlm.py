"""
Vision-Language Model layer.

OCR gives us raw text but loses structure (which number is the PAN vs.
a phone number, which column in a bank statement is "credit" vs. "debit").
The VLM is given the actual image plus the OCR text and asked to reason
about layout — this two-pass OCR+VLM pattern is what actually earns the
"understands document images, forms, tables" claim on the diagram,
rather than just running OCR and calling it done.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from groq import Groq

from app.core.config import get_settings
from app.core.schemas import DocumentType

VLM_SYSTEM_PROMPT = """You are a document understanding assistant for a loan \
application system. You will be shown an image of a financial/identity \
document along with OCR-extracted text. Your job is to:

1. Classify the document type: one of aadhaar, pan, salary_slip, bank_statement, unknown
2. Extract structured fields relevant to that document type
3. Flag anything that looks inconsistent, cropped, or tampered

Respond ONLY with valid JSON matching this schema, no other text:
{
  "doc_type": "<one of the types above>",
  "fields": [{"name": "<field_name>", "value": "<value>", "confidence": <0-1 float>}],
  "summary": "<one sentence human-readable summary>",
  "quality_flags": ["<any issues, empty list if none>"]
}"""


class VLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.vlm_model

    def analyze_document(self, image_bytes: bytes, ocr_text: str) -> dict[str, Any]:
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": VLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"OCR extracted text (may contain errors):\n{ocr_text}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                        },
                    ],
                },
            ],
            temperature=0.0,
            max_tokens=800,
        )

        raw = response.choices[0].message.content
        return self._parse_json_response(raw)

    @staticmethod
    def _parse_json_response(raw: str) -> dict[str, Any]:
        """VLMs occasionally wrap JSON in markdown fences — strip defensively."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "doc_type": DocumentType.UNKNOWN.value,
                "fields": [],
                "summary": "Failed to parse document — please re-upload a clearer image.",
                "quality_flags": ["vlm_parse_error"],
            }


def get_vlm_client() -> VLMClient:
    return VLMClient()
