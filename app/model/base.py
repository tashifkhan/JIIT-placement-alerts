"""Shared MongoDB model helpers."""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class MongoModel(BaseModel):
    """Base model for Mongo documents.

    Allows extra fields so historical documents and incremental schema changes can
    still be validated while the canonical fields stay documented here.
    """

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="allow",
        populate_by_name=True,
    )

    mongo_id: Optional[Any] = Field(default=None, alias="_id")
