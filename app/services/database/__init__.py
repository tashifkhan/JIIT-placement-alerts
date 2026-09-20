"""Database service and collection-specific repositories."""

import logging

from clients.db_client import DBClient
from services.database.jobs import JobRepository
from services.database.notices import NoticeRepository
from services.database.official_placement import OfficialPlacementRepository
from services.database.placement_offers import PlacementOfferRepository
from services.database.policies import PolicyRepository
from services.database.users import UserRepository


class DatabaseService(
    NoticeRepository,
    JobRepository,
    PlacementOfferRepository,
    OfficialPlacementRepository,
    UserRepository,
    PolicyRepository,
):
    """
    Database service implementing the app's persistence API.

    Repositories mixed into this facade:
    - NoticeRepository: Notices collection
    - JobRepository: Jobs collection
    - PlacementOfferRepository: PlacementOffers collection and stats
    - OfficialPlacementRepository: OfficialPlacementData and OfficialPlacementBatches
    - UserRepository: Users and PlacementYears collections
    - PolicyRepository: Policies collection
    """

    def __init__(self, db_client: DBClient):
        """
        Initialize database service.

        Args:
            db_client: Initialized DBClient instance.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_client = db_client

        self.notices_collection = db_client.notices_collection
        self.jobs_collection = db_client.jobs_collection
        self.placement_offers_collection = db_client.placement_offers_collection
        self.users_collection = db_client.users_collection
        self.policies_collection = db_client.policies_collection
        self.official_placement_data_collection = (
            db_client.official_placement_data_collection
        )
        self.official_placement_batches_collection = (
            db_client.official_placement_batches_collection
        )
        self.placement_years_collection = db_client.placement_years_collection

        self.logger.info("Initializing DatabaseService with DBClient")

    def close_connection(self) -> None:
        """Close MongoDB connection."""
        if self.db_client:
            self.db_client.close_connection()

__all__ = [
    "DatabaseService",
    "JobRepository",
    "NoticeRepository",
    "OfficialPlacementRepository",
    "PlacementOfferRepository",
    "PolicyRepository",
    "UserRepository",
]
