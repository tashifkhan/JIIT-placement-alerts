"""Schemas for the Users collection."""

from datetime import datetime

from model.base import MongoModel


class UserDocument(MongoModel):
    """Telegram user stored in Users."""

    user_id: int
    chat_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool = True
    selected_placement_year: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
