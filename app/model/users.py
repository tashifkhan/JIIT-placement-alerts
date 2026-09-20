"""Schemas for the Users collection."""

from datetime import datetime
from typing import Optional

from model.base import MongoModel


class UserDocument(MongoModel):
    """Telegram user stored in Users."""

    user_id: int
    chat_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = True
    selected_placement_year: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
