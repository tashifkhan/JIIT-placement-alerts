from datetime import datetime, timezone
from types import SimpleNamespace

from pymongo.errors import DuplicateKeyError

from clients import db_client
from model.notices import NoticeDocument
from scripts.migrate_structured_notices import normalize_student_rows
from services.database.notices import NoticeRepository
from services.database.placement_offers import PlacementOfferRepository
from services.database.users import UserRepository
from services.placement.analysis.helpers import to_float


class FakeCursor(list):
    def sort(self, *args, **kwargs):
        return self


def test_notice_duplicate_is_handled_without_check_then_insert():
    class DuplicateCollection:
        def find_one(self, query):
            raise AssertionError("save_notice must not check before inserting")

        def insert_one(self, document):
            raise DuplicateKeyError("duplicate notice id")

    repository = NoticeRepository()
    repository.notices_collection = DuplicateCollection()

    success, message = repository.save_notice(
        {"id": "notice-1", "title": "Notice", "content": "Body"}
    )

    assert success is False
    assert message == "Notice already exists"


def test_notice_document_normalizes_null_student_lists():
    notice = NoticeDocument(
        id="notice-null-students",
        shortlisted_students=None,
        selected_students=None,
    )

    assert notice.shortlisted_students == []
    assert notice.selected_students == []


def test_notice_repository_saves_null_shortlisted_students():
    class NoticeCollection:
        def __init__(self):
            self.document = None

        def insert_one(self, document):
            self.document = document
            return SimpleNamespace(inserted_id="mongo-id")

    repository = NoticeRepository()
    collection = NoticeCollection()
    repository.notices_collection = collection

    success, message = repository.save_notice(
        {
            "id": "notice-null-shortlist",
            "title": "General notice",
            "shortlisted_students": None,
        }
    )

    assert success is True
    assert message == "mongo-id"
    assert collection.document["shortlisted_students"] == []


def test_user_repository_builds_placement_year_filter_for_active_users(monkeypatch):
    class UsersCollection:
        def __init__(self):
            self.query = None

        def find(self, query):
            self.query = query
            return [{"user_id": 1, "selected_placement_year": "202627"}]

    collection = UsersCollection()
    repository = UserRepository()
    repository.users_collection = collection
    monkeypatch.setattr(
        repository,
        "_settings_for_defaults",
        lambda: SimpleNamespace(
            active_placement_year="202526", default_placement_year="202526"
        ),
    )

    users = repository.get_active_users("202627")

    assert users[0]["user_id"] == 1
    assert collection.query == {
        "is_active": True,
        "$or": [{"selected_placement_year": "202627"}],
    }


def test_company_identity_is_normalized_and_stale_match_is_cleared(monkeypatch):
    existing = {
        "_id": "offer-1",
        "company": "ACME Corp",
        "company_key": "acme corp",
        "roles": [],
        "students_selected": [],
        "number_of_offers": 0,
        "matched_job_id": "old-job",
        "related_job_id": "old-job",
        "matched_job": {"id": "old-job", "company": "ACME Corp"},
    }

    class OffersCollection:
        def __init__(self):
            self.find_query = None
            self.update_query = None
            self.update = None

        def find(self, query):
            self.find_query = query
            return FakeCursor([existing])

        def update_one(self, query, update):
            self.update_query = query
            self.update = update

    collection = OffersCollection()
    repository = PlacementOfferRepository()
    repository.placement_offers_collection = collection
    monkeypatch.setattr(
        repository, "_match_job_by_company", lambda company: None, raising=False
    )

    result = repository.save_placement_offers(
        [{"company": "  ACME   Corp  ", "roles": [], "students_selected": []}]
    )

    assert result["updated"] == 1
    assert collection.find_query == {"company_key": "acme corp"}
    assert collection.update_query == {"company_key": "acme corp"}
    assert collection.update["$set"]["company"] == "ACME Corp"
    assert collection.update["$set"]["company_key"] == "acme corp"
    assert set(collection.update["$unset"]) == {
        "matched_job_id",
        "related_job_id",
        "matched_job",
    }


def test_keyless_historical_company_is_adopted_before_company_key_update(monkeypatch):
    legacy_offer = {
        "_id": "legacy-offer",
        "company": "Acme Corp",
        "roles": [],
        "students_selected": [],
        "number_of_offers": 0,
    }

    class OffersCollection:
        def __init__(self):
            self.updates = []

        def find(self, query):
            if query == {"company_key": "acme corp"}:
                return FakeCursor([])
            return FakeCursor([legacy_offer])

        def update_one(self, query, update):
            self.updates.append((query, update))

    collection = OffersCollection()
    repository = PlacementOfferRepository()
    repository.placement_offers_collection = collection
    monkeypatch.setattr(
        repository, "_match_job_by_company", lambda company: None, raising=False
    )

    result = repository.save_placement_offers(
        [{"company": " acme   corp ", "roles": [], "students_selected": []}]
    )

    assert result["updated"] == 1
    assert collection.updates[0] == (
        {"_id": "legacy-offer"},
        {"$set": {"company_key": "acme corp"}},
    )
    assert collection.updates[1][0] == {"company_key": "acme corp"}
    assert collection.updates[1][1]["$set"]["company"] == "Acme Corp"


def test_index_creation_is_complete_and_duplicate_failure_is_nonfatal(monkeypatch):
    created_indexes = []

    class FakeCollection:
        def __init__(self, name):
            self.name = name

        def create_index(self, keys, **options):
            created_indexes.append((self.name, keys, options))
            if self.name == "Notices":
                raise DuplicateKeyError("historical duplicate")

    class FakeDatabase:
        def __init__(self):
            self.collections = {}

        def __getitem__(self, name):
            return self.collections.setdefault(name, FakeCollection(name))

    class FakeAdmin:
        def command(self, command):
            assert command == "ping"

    class FakeMongoClient:
        def __init__(self, connection_string):
            self.admin = FakeAdmin()
            self.databases = {}

        def __getitem__(self, name):
            return self.databases.setdefault(name, FakeDatabase())

    monkeypatch.setattr(db_client, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(
        db_client,
        "get_settings",
        lambda: SimpleNamespace(
            mongo_connection_str="mongodb://fake",
            active_placement_year="202526",
            mongo_database_name="2025-26",
            global_database_name="global",
        ),
    )

    client = db_client.DBClient()
    client.connect()

    assert {options["name"] for _, _, options in created_indexes} == {
        "notices_id_unique",
        "jobs_id_unique",
        "users_user_id_unique",
        "placement_offers_company_key_unique",
        "placement_years_year_unique",
        "official_placement_batches_batch_name_unique",
    }
    index_options = {options["name"]: options for _, _, options in created_indexes}
    assert index_options["notices_id_unique"]["unique"] is True
    assert index_options["notices_id_unique"]["partialFilterExpression"] == {
        "id": {"$type": "string"}
    }
    assert index_options["jobs_id_unique"]["partialFilterExpression"] == {
        "id": {"$type": "string"}
    }
    assert index_options["placement_offers_company_key_unique"][
        "partialFilterExpression"
    ] == {"company_key": {"$type": "string"}}


def test_package_values_are_normalized_for_statistics():
    assert to_float(29) == 29
    assert to_float(2_900_000) == 29
    assert to_float(25_000) is None


def test_legacy_user_import_is_insert_only(monkeypatch):
    calls = []

    class UsersCollection:
        def update_one(self, query, update, upsert=False):
            calls.append((query, update, upsert))
            return SimpleNamespace(upserted_id="new-user")

    repository = UserRepository()
    repository.users_collection = UsersCollection()

    imported = repository.import_legacy_users(
        [{"user_id": 42, "chat_id": 42, "is_active": True}],
        "202526",
    )

    assert imported == 1
    assert calls[0][0] == {"user_id": 42}
    assert "$setOnInsert" in calls[0][1]
    assert "$set" not in calls[0][1]
    assert calls[0][1]["$setOnInsert"]["selected_placement_year"] == "202526"
    assert calls[0][2] is True


def test_each_student_keeps_the_date_they_first_received_an_offer(monkeypatch):
    first_offer = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    later_offer = "2026-01-08T10:00:00+00:00"
    repeated_update = "2026-01-10T10:00:00+00:00"
    existing = {
        "_id": "amazon-offer",
        "company": "Amazon",
        "company_key": "amazon",
        "roles": [],
        "students_selected": [
            {"name": f"Student {index}", "enrollment_number": str(index)}
            for index in range(1, 7)
        ],
        "number_of_offers": 6,
        "created_at": first_offer,
        "createdAt": int(first_offer.timestamp() * 1000),
    }

    class OffersCollection:
        def __init__(self, document):
            self.document = document

        def find(self, query):
            return FakeCursor([self.document])

        def update_one(self, query, update):
            self.document.update(update.get("$set", {}))
            for field in update.get("$unset", {}):
                self.document.pop(field, None)
            return SimpleNamespace(modified_count=1)

    collection = OffersCollection(existing)
    repository = PlacementOfferRepository()
    repository.placement_offers_collection = collection
    monkeypatch.setattr(
        repository, "_match_job_by_company", lambda _company: None, raising=False
    )

    first_result = repository.save_placement_offers(
        [
            {
                "company": "Amazon",
                "roles": [],
                "students_selected": [
                    {"name": "Student 8", "enrollment_number": "8"}
                ],
                "time_sent": later_offer,
            }
        ]
    )

    students = {
        student["enrollment_number"]: student
        for student in collection.document["students_selected"]
    }
    assert first_result["updated"] == 1
    assert all(
        students[str(index)]["offer_received_at"] == first_offer
        for index in range(1, 7)
    )
    assert students["8"]["offer_received_at"] == datetime(
        2026, 1, 8, 10, 0, tzinfo=timezone.utc
    )
    assert first_result["events"][0]["newly_added_students"][0][
        "offerReceivedAt"
    ] == int(datetime(2026, 1, 8, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)

    repository.save_placement_offers(
        [
            {
                "company": "Amazon",
                "roles": [],
                "students_selected": [
                    {"name": "Student 8", "enrollment_number": "8"}
                ],
                "time_sent": repeated_update,
            }
        ]
    )

    student_eight = next(
        student
        for student in collection.document["students_selected"]
        if student["enrollment_number"] == "8"
    )
    assert student_eight["offer_received_at"] == datetime(
        2026, 1, 8, 10, 0, tzinfo=timezone.utc
    )


def test_migration_prefers_student_notice_date_over_parent_offer_date():
    original_offer = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later_offer = datetime(2026, 1, 8, tzinfo=timezone.utc)

    rows = normalize_student_rows(
        [
            {"name": "Student 1", "enrollment_number": "1"},
            {"name": "Student 8", "enrollment_number": "8"},
        ],
        roles=[],
        location=None,
        joining_date=None,
        offer_received_at=original_offer,
        student_offer_dates={"enrollment:8": later_offer},
    )

    assert rows[0]["offer_received_at"] == original_offer
    assert rows[1]["offer_received_at"] == later_offer
