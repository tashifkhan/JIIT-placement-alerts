"""Schemas for the OfficialPlacementData collection."""

from typing import List, Optional

from pydantic import Field

from model.base import MongoModel


class RecruiterLogo(MongoModel):
    """Recruiter logo scraped from the official website."""

    src: Optional[str] = None
    alt: Optional[str] = None


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
    placement_pointers: List[str] = Field(default_factory=list)
    package_distribution: List[PackageDistribution] = Field(default_factory=list)
    highlights: List[PlacementHighlight] = Field(default_factory=list)


class OfficialPlacementDataDocument(MongoModel):
    """Scraped official placement data stored in OfficialPlacementData."""

    scrape_timestamp: str
    content_hash: Optional[str] = None
    main_heading: Optional[str] = None
    intro_text: Optional[str] = None
    recruiter_logos: List[RecruiterLogo] = Field(default_factory=list)
    batches: List[BatchInfo] = Field(default_factory=list)
