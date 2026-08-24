"""
Maintenance model — a standalone kill-switch the Flutter app checks on
splash, completely independent from AppVersion/force-update. Maintenance
is "take the whole app offline for everyone right now", which is a
different concern from "you're on an old app version" -- keeping them as
separate tables/endpoints/screens means turning maintenance on or off can
never accidentally touch version/force-update config, and vice versa.
"""
from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class MaintenanceConfig(BaseModel):
    """Single global row (not per-platform) read by every app instance on
    splash via GET /app/maintenance/check. When is_enabled is true, the
    app shows a blocking 'Under Maintenance' screen with a button to
    status_url, no matter what version is installed."""

    __tablename__ = "maintenance_config"

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    title: Mapped[str] = mapped_column(
        String(150), nullable=False, default="Under Maintenance"
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="ClassyBattle is currently undergoing scheduled maintenance. Please check back shortly.",
    )
    status_url: Mapped[str] = mapped_column(
        String(500), nullable=False, default="https://status.classybattle.online"
    )

    def __repr__(self) -> str:
        return f"<MaintenanceConfig enabled={self.is_enabled}>"
