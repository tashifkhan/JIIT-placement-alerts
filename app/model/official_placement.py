"""Schemas for official JIIT placement scrape snapshots and per-year batches."""

from typing import Literal

from pydantic import Field

from model.base import MongoModel


class RecruiterLogo(MongoModel):
    """Recruiter logo scraped from the official website."""

    src: str | None = None
    alt: str | None = None


class PackageDistribution(MongoModel):
    """Package distribution row scraped from official placement pages."""

    category: str
    average: str
    median: str


class PlacementHighlight(MongoModel):
    """Placement statistic displayed in a highlight card."""

    title: str
    description: str


class BatchInfo(MongoModel):
    """Official placement details for one graduating batch."""

    batch_name: str
    is_active: bool = False
    placement_pointers: list[str] = Field(default_factory=list)
    package_distribution: list[PackageDistribution] = Field(default_factory=list)
    highlights: list[PlacementHighlight] = Field(default_factory=list)


class OfficialPlacementDataDocument(MongoModel):
    """Full-page scrape snapshot stored in OfficialPlacementData."""

    scrape_timestamp: str
    content_hash: str | None = None
    main_heading: str | None = None
    intro_text: str | None = None
    recruiter_logos: list[RecruiterLogo] = Field(default_factory=list)
    batches: list[BatchInfo] = Field(default_factory=list)


class OfficialPlacementBatchDocument(MongoModel):
    """One graduating year in OfficialPlacementBatches.

    Live scrapes own ``source=live`` docs. Seeded docs are frozen and never
    overwritten by the scraper.
    """

    batch_name: str
    is_active: bool = False
    source: Literal["live", "seeded"] = "live"
    placement_pointers: list[str] = Field(default_factory=list)
    package_distribution: list[PackageDistribution] = Field(default_factory=list)
    highlights: list[PlacementHighlight] = Field(default_factory=list)
    updated_at: str
    scrape_timestamp: str | None = None
    seed_version: str | None = None
    provenance: str | None = None
