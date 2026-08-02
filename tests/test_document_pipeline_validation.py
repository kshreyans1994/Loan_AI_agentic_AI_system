from app.core.schemas import DocumentType, ExtractedField
from app.document_ai.pipeline import _validate_fields


def test_valid_pan_passes():
    fields = [ExtractedField(name="pan_number", value="ABCDE1234F", confidence=0.9)]
    errors = _validate_fields(DocumentType.PAN, fields)
    assert errors == []


def test_invalid_pan_format_fails():
    fields = [ExtractedField(name="pan_number", value="12345ABCDE", confidence=0.9)]
    errors = _validate_fields(DocumentType.PAN, fields)
    assert len(errors) == 1
    assert "PAN" in errors[0]


def test_valid_aadhaar_passes():
    fields = [ExtractedField(name="aadhaar_number", value="1234 5678 9012", confidence=0.9)]
    errors = _validate_fields(DocumentType.AADHAAR, fields)
    assert errors == []


def test_invalid_aadhaar_too_short_fails():
    fields = [ExtractedField(name="aadhaar_number", value="1234 5678", confidence=0.9)]
    errors = _validate_fields(DocumentType.AADHAAR, fields)
    assert len(errors) == 1


def test_salary_slip_missing_income_field_fails():
    fields = [ExtractedField(name="employer_name", value="Acme Corp", confidence=0.9)]
    errors = _validate_fields(DocumentType.SALARY_SLIP, fields)
    assert len(errors) == 1
    assert "income" in errors[0].lower()
