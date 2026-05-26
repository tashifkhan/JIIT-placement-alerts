"""
Database Client

Handles the raw MongoDB connection and provides access to collections.
Decoupled from the business logic service.
"""

import logging
from typing import Optional
from pymongo import MongoClient

from core.config import get_settings, safe_print
from core.year_context import database_name_for_year, normalize_year


class DBClient:
    """
    Database client for handling MongoDB connections.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        database_name: Optional[str] = None,
        placement_year: Optional[str] = None,
        use_global_database: bool = False,
    ):
        """
        Initialize database client.

        Args:
            connection_string: MongoDB connection string. If None, reads from env.
            database_name: MongoDB database name. If None, reads from env.
            placement_year: Placement year used to derive database name.
            use_global_database: Use global bot database instead of a year database.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        settings = get_settings()
        self.connection_string = connection_string or settings.mongo_connection_str
        if use_global_database:
            self.database_name = database_name or settings.global_database_name
        else:
            resolved_year = normalize_year(placement_year or settings.active_placement_year)
            if placement_year:
                self.database_name = database_name or database_name_for_year(resolved_year)
            else:
                self.database_name = (
                    database_name
                    or settings.mongo_database_name
                    or database_name_for_year(resolved_year)
                )

        self.client: Optional[MongoClient] = None
        self.db = None

        # Collections
        self._notices_collection = None
        self._jobs_collection = None
        self._placement_offers_collection = None
        self._users_collection = None
        self._policies_collection = None
        self._official_placement_data_collection = None
        self._placement_years_collection = None

    def connect(self) -> None:
        """Establish database connection"""
        self.logger.info("Attempting to connect to MongoDB")
        try:
            if not self.connection_string:
                error_msg = "MONGO_CONNECTION_STR not found in environment variables"
                self.logger.error(error_msg)
                raise ValueError(error_msg)

            self.client = MongoClient(self.connection_string)
            self.db = self.client[self.database_name]

            # Initialize collections
            self._notices_collection = self.db["Notices"]
            self._jobs_collection = self.db["Jobs"]
            self._placement_offers_collection = self.db["PlacementOffers"]
            self._users_collection = self.db["Users"]
            self._policies_collection = self.db["Policies"]
            self._official_placement_data_collection = self.db["OfficialPlacementData"]
            self._placement_years_collection = self.db["PlacementYears"]

            # Test connection
            self.client.admin.command("ping")
            success_msg = "Successfully connected to MongoDB"
            self.logger.info(success_msg)
            safe_print(success_msg)

        except Exception as e:
            error_msg = f"Failed to connect to MongoDB: {e}"
            self.logger.error(error_msg, exc_info=True)
            safe_print(error_msg)
            raise

    def close_connection(self) -> None:
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            self.logger.info("MongoDB connection closed")
            safe_print("MongoDB connection closed")

    @property
    def notices_collection(self):
        return self._notices_collection

    @property
    def jobs_collection(self):
        return self._jobs_collection

    @property
    def placement_offers_collection(self):
        return self._placement_offers_collection

    @property
    def users_collection(self):
        return self._users_collection

    @property
    def policies_collection(self):
        return self._policies_collection

    @property
    def official_placement_data_collection(self):
        return self._official_placement_data_collection

    @property
    def placement_years_collection(self):
        return self._placement_years_collection
