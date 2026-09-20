"""Schemas for the Policies collection."""

from datetime import datetime
from typing import List, Optional

from pydantic import Field

from model.base import MongoModel


class TOCItem(MongoModel):
    """Table of contents item for a policy document."""

    id: str
    text: str
    level: int


class PolicySource(MongoModel):
    """Original source metadata for extracted policies."""

    from_: Optional[str] = Field(default=None, alias="from")
    subject: Optional[str] = None
    date: Optional[str] = None
    audience: Optional[str] = None


class PolicyDocument(MongoModel):
    """Placement policy stored in Policies."""

    slug: str
    title: str = "Placement Policy"
    description: str = ""
    badge: str = ""
    year: int
    updatedDates: List[str] = Field(default_factory=list)
    published: bool = True
    contentFormat: str = "markdown"
    content: str
    toc: List[TOCItem] = Field(default_factory=list)
    source: Optional[PolicySource] = None
    notes: List[str] = Field(default_factory=list)
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
