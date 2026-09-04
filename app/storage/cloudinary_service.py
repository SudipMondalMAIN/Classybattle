"""
Cloudinary storage for support-chat media (images/videos).

Kept separate from StorageService (Supabase) because chat attachments
are meant to be short-lived -- everything uploaded here is tagged
"support_chat" and swept by scripts/cleanup_support_media.py after
settings.SUPPORT_MEDIA_RETENTION_DAYS. Cloudinary's own free-tier
uploads don't support a native "expire after N days" option, so
retention is enforced by that scheduled job rather than at upload time.
"""
from functools import lru_cache
from typing import Optional
from uuid import uuid4

from app.config.settings import settings
from app.core.exceptions import ExternalServiceException
from app.core.logging import get_logger

logger = get_logger(__name__)

SUPPORT_CHAT_TAG = "support_chat"


@lru_cache
def _configured() -> bool:
    if not (settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET):
        logger.warning("cloudinary_credentials_missing")
        return False

    import cloudinary

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    return True


class CloudinaryMediaService:
    """Upload/delete helpers for support chat image & video attachments."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    def _require_configured(self) -> None:
        if not _configured():
            raise ExternalServiceException("Media upload service is not configured")

    async def upload(self, file_bytes: bytes, content_type: str, resource_type: str) -> dict:
        """Upload an image or video and return {url, public_id, resource_type}.

        resource_type is "image" or "video" -- Cloudinary needs this
        upfront (it can't reliably infer video vs image from raw bytes
        for every mobile-recorded format).
        """
        self._require_configured()
        import cloudinary.uploader

        public_id = f"support_chat/{self.session_id}/{uuid4().hex}"
        try:
            result = cloudinary.uploader.upload(
                file_bytes,
                public_id=public_id,
                resource_type=resource_type,
                tags=[SUPPORT_CHAT_TAG, f"session:{self.session_id}"],
                overwrite=False,
            )
        except Exception as exc:  # noqa: BLE001 -- cloudinary raises its own Error type
            raise ExternalServiceException(f"Media upload failed: {exc}") from exc

        return {
            "url": result["secure_url"],
            "public_id": result["public_id"],
            "resource_type": result.get("resource_type", resource_type),
        }

    @staticmethod
    async def delete(public_id: str, resource_type: str = "image") -> None:
        if not _configured():
            return
        import cloudinary.uploader

        try:
            cloudinary.uploader.destroy(public_id, resource_type=resource_type)
        except Exception:  # noqa: BLE001
            logger.warning("cloudinary_delete_failed", public_id=public_id)
