"""
AppVersion model — drives the Flutter app's splash-screen update check.

One row per platform (android/ios). Admin edits this via the admin
endpoints below; the mobile app hits the public `/app/version/check`
endpoint on splash and decides whether to show a soft or forced
update dialog based on the response.
"""
import enum

from sqlalchemy import Boolean, Enum, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class AppPlatform(str, enum.Enum):
    ANDROID = "android"
    IOS = "ios"


class AppVersion(BaseModel):
    """Latest/minimum supported version info for a given platform."""

    __tablename__ = "app_versions"
    __table_args__ = (
        UniqueConstraint("platform", name="uq_app_versions_platform"),
    )

    platform: Mapped[AppPlatform] = mapped_column(
        Enum(
            AppPlatform,
            name="app_platform",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        index=True,
    )

    # Newest version published to the store.
    latest_version: Mapped[str] = mapped_column(String(20), nullable=False)
    latest_build_number: Mapped[int] = mapped_column(nullable=False, default=1)

    # Any installed version below this is force-blocked.
    min_supported_version: Mapped[str] = mapped_column(String(20), nullable=False)

    force_update: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    update_url: Mapped[str] = mapped_column(String(500), nullable=False)

    update_title: Mapped[str] = mapped_column(
        String(150), nullable=False, default="Update Available"
    )
    update_message: Mapped[str] = mapped_column(
        Text, nullable=False, default="A new version of the app is available."
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<AppVersion platform={self.platform} latest={self.latest_version}>"