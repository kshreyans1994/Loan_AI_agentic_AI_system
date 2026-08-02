"""
Object storage — S3-compatible (works against real AWS S3 or a
self-hosted MinIO by setting `object_storage_endpoint_url`).

Used for two things per the diagram's Infrastructure Flow:
  - persisting the ORIGINAL uploaded file (salary slip, bank statement)
    alongside the OCR/extraction result, for audit/compliance — "what
    did the applicant actually submit" needs to survive independently
    of whatever the extraction pipeline read from it
  - storing policy PDFs (Credit_Policy_2027.pdf etc.) that get chunked
    into knowledge_chunks for RAG — the source PDF stays retrievable
    for a human to check the chunking against the original

Disabled by default (`Settings.object_storage_enabled = False`) so a
local/demo run doesn't need real S3/MinIO credentials to start up —
callers should check `is_enabled` before calling put/get rather than
relying on an exception, since "storage not configured" is an expected
state in dev, not an error condition.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings


class ObjectStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None

    @property
    def is_enabled(self) -> bool:
        return self.settings.object_storage_enabled

    @property
    def client(self):
        if self._client is None:
            import boto3  # imported lazily so boto3 isn't required unless storage is actually used

            self._client = boto3.client(
                "s3",
                endpoint_url=self.settings.object_storage_endpoint_url,  # None -> real AWS S3
                aws_access_key_id=self.settings.object_storage_access_key,
                aws_secret_access_key=self.settings.object_storage_secret_key,
                region_name=self.settings.object_storage_region,
            )
        return self._client

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str | None:
        """Returns the storage key on success, None if storage isn't
        enabled (a no-op, not an error — see module docstring)."""
        if not self.is_enabled:
            return None
        self.client.put_object(
            Bucket=self.settings.object_storage_bucket, Key=key, Body=data, ContentType=content_type
        )
        return key

    def get_bytes(self, key: str) -> bytes | None:
        if not self.is_enabled:
            return None
        response = self.client.get_object(Bucket=self.settings.object_storage_bucket, Key=key)
        return response["Body"].read()

    def presigned_url(self, key: str, expires_in: int = 3600) -> str | None:
        if not self.is_enabled:
            return None
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.object_storage_bucket, "Key": key},
            ExpiresIn=expires_in,
        )


@lru_cache
def get_object_storage() -> ObjectStorage:
    return ObjectStorage()
