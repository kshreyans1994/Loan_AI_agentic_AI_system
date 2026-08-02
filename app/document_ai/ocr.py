"""
OCR extraction layer.

Uses pytesseract (Tesseract) for text extraction. This is intentionally
kept behind a small interface (OCREngine) so it can be swapped for a
cloud OCR provider (Azure Document Intelligence, AWS Textract, Google
Document AI) without touching any calling code — that swap is a common
follow-up question in system design interviews, so the seam is real,
not decorative.
"""
from __future__ import annotations

import io
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pytesseract
from PIL import Image


@dataclass
class OCRResult:
    text: str
    mean_confidence: float  # 0.0 - 1.0
    word_confidences: list[float]


class OCREngine(ABC):
    @abstractmethod
    def extract(self, image_bytes: bytes) -> OCRResult:
        ...


class TesseractOCREngine(OCREngine):
    """Local, dependency-light OCR — good default for a portfolio/demo build."""

    def extract(self, image_bytes: bytes) -> OCRResult:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # image_to_data gives per-word confidence, which is what lets us
        # compute a real confidence score instead of hardcoding one.
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

        words = []
        confidences = []
        for word, conf in zip(data["text"], data["conf"]):
            word = word.strip()
            conf = float(conf)
            if word and conf >= 0:  # tesseract returns -1 for non-text regions
                words.append(word)
                confidences.append(conf / 100.0)

        text = " ".join(words)
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(text=text, mean_confidence=mean_conf, word_confidences=confidences)


def get_ocr_engine() -> OCREngine:
    return TesseractOCREngine()
