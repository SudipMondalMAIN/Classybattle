"""
Maintenance schemas -- standalone kill-switch, unrelated to app_version.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MaintenanceUpsert(BaseModel):
    """Body for the admin toggle endpoint. Only is_enabled is required --
    title/message/status_url are optional and, when omitted, leave
    whatever was previously configured untouched (or fall back to a
    sensible default the first time maintenance is ever turned on)."""

    is_enabled: bool
    title: Optional[str] = Field(default=None, max_length=150)
    message: Optional[str] = None
    status_url: Optional[str] = Field(default=None, max_length=500)


class MaintenanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_enabled: bool
    title: str
    message: str
    status_url: str
    created_at: datetime
    updated_at: datetime


class MaintenanceCheckResponse(BaseModel):
    """What the Flutter splash screen consumes -- deliberately tiny and
    separate from AppVersionCheckResponse."""

    is_enabled: bool
    title: str
    message: str
    status_url: str
