"""Schemas for the Policies collection."""

from datetime import datetime

from pydantic import Field

from model.base import MongoModel


class TOCItem(MongoModel):
    """Table of contents item for a policy document."""

    id: str
    text: str
    level: int


class PolicySource(MongoModel):
    """Original source metadata for extracted policies."""

    from_: str | None = Field(default=None, alias="from")
    subject: str | None = None
    date: str | None = None
    audience: str | None = None


class PolicyDocument(MongoModel):
    """Placement policy stored in Policies."""

    slug: str
    title: str = "Placement Policy"
    description: str = ""
    badge: str = ""
    year: int
    updatedDates: list[str] = Field(default_factory=list)
    published: bool = True
    contentFormat: str = "markdown"
    content: str
    toc: list[TOCItem] = Field(default_factory=list)
    source: PolicySource | None = None
    notes: list[str] = Field(default_factory=list)
    createdAt: datetime | None = None
    updatedAt: datetime | None = None
