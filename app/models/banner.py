"""
Banner model — promotional banners shown on the app home screen.

Admin uploads the image directly (stored via StorageService) and can
optionally attach a title + redirect link. Everything except the image
itself is optional so admin can post a plain image banner with nothing
else attached.
"""
from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class Banner(BaseModel):
    """A single promotional banner. Admin adds/removes these from the admin panel."""

    __tablename__ = "banners"

    image_url: Mapped[str] = mapped_column(Text, nullable=False)

    # Everything below is optional.
    title: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    redirect_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<Banner id={self.id} title={self.title!r}>"
