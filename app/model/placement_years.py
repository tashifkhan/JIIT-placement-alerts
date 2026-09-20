"""Schemas for the PlacementYears collection."""

from datetime import datetime
from typing import Optional

from model.base import MongoModel


class PlacementYearDocument(MongoModel):
    """Placement year metadata stored in the global PlacementYears collection."""

    year: str
    label: str
    database_name: str
    is_active: bool = True
    is_default: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
