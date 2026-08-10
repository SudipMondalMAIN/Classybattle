"""
Reusable Supabase Storage service.

Phase 1 provides the client + generic upload/download/delete helpers only.
Tournament-specific upload flows (screenshots, proofs, etc.) are wired
up in a later phase.
"""
from functools import lru_cache
from typing import Optional

from app.config.settings import settings
from app.core.exceptions import ExternalServiceException
from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache
def get_supabase_client():
    """Lazily create and cache the Supabase client."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        logger.warning("supabase_credentials_missing")
        return None

    from supabase import Client, create_client

    client: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return client


class StorageService:
    """Reusable wrapper around Supabase Storage for future upload flows."""

    def __init__(self, bucket: Optional[str] = None) -> None:
        self.bucket = bucket or settings.SUPABASE_STORAGE_BUCKET
        self._bucket_checked = False

    def _client_or_raise(self):
        client = get_supabase_client()
        if client is None:
            raise ExternalServiceException("Storage service is not configured")
        return client

    def _ensure_bucket(self, client) -> None:
        """Create the bucket on first use if it doesn't exist yet.

        Buckets aren't provisioned automatically by Supabase — a bucket
        used from code (e.g. a new "banner-assets" bucket) has to exist
        before .upload() will work, otherwise the SDK raises a raw
        StorageException that previously surfaced as an unhandled 500.
        """
        if self._bucket_checked:
            return
        from storage3.exceptions import StorageException

        try:
            client.storage.get_bucket(self.bucket)
        except StorageException:
            try:
                client.storage.create_bucket(self.bucket, options={"public": True})
            except StorageException as exc:
                # Ignore "already exists" races; anything else is real.
                if "already exists" not in str(exc).lower():
                    raise ExternalServiceException(
                        f"Could not prepare storage bucket '{self.bucket}': {exc}"
                    ) from exc
        self._bucket_checked = True

    async def upload_file(self, path: str, file_bytes: bytes, content_type: str) -> str:
        """Upload a file and return its public URL."""
        from storage3.exceptions import StorageException

        client = self._client_or_raise()
        self._ensure_bucket(client)
        try:
            client.storage.from_(self.bucket).upload(
                path, file_bytes, {"content-type": content_type}
            )
        except StorageException as exc:
            raise ExternalServiceException(f"Image upload failed: {exc}") from exc
        return client.storage.from_(self.bucket).get_public_url(path)

    async def delete_file(self, path: str) -> None:
        client = self._client_or_raise()
        client.storage.from_(self.bucket).remove([path])

    async def get_public_url(self, path: str) -> str:
        client = self._client_or_raise()
        return client.storage.from_(self.bucket).get_public_url(path)


storage_service = StorageService()

