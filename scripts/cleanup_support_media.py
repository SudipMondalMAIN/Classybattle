"""
Delete Cloudinary support-chat attachments older than the retention
window (default 14 days, see settings.SUPPORT_MEDIA_RETENTION_DAYS).

Run this on a daily cron (e.g. Render Cron Job):
    python -m scripts.cleanup_support_media

Everything uploaded via CloudinaryMediaService is tagged "support_chat",
so this only ever touches chat attachments -- nothing else in the
Cloudinary account is affected. The message row + media_url in Postgres
are left as-is (history is kept for the transcript); the URL will just
404 once Cloudinary has deleted the underlying asset.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.config.settings import settings
from app.core.logging import get_logger
from app.storage.cloudinary_service import SUPPORT_CHAT_TAG, _configured

logger = get_logger("cleanup_support_media")


def _delete_expired_for_resource_type(resource_type: str, cutoff: datetime) -> int:
    import cloudinary.api

    deleted = 0
    next_cursor = None
    while True:
        resp = cloudinary.api.resources_by_tag(
            SUPPORT_CHAT_TAG,
            resource_type=resource_type,
            max_results=500,
            next_cursor=next_cursor,
        )
        stale_ids = [
            r["public_id"]
            for r in resp.get("resources", [])
            if datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < cutoff
        ]
        if stale_ids:
            cloudinary.api.delete_resources(stale_ids, resource_type=resource_type)
            deleted += len(stale_ids)

        next_cursor = resp.get("next_cursor")
        if not next_cursor:
            break

    return deleted


def run() -> None:
    if not _configured():
        logger.warning("cleanup_support_media_skipped_not_configured")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.SUPPORT_MEDIA_RETENTION_DAYS)
    total = 0
    for resource_type in ("image", "video"):
        count = _delete_expired_for_resource_type(resource_type, cutoff)
        total += count
        logger.info("cleanup_support_media_resource_done", resource_type=resource_type, deleted=count)

    logger.info("cleanup_support_media_done", total_deleted=total, cutoff=cutoff.isoformat())


if __name__ == "__main__":
    run()
