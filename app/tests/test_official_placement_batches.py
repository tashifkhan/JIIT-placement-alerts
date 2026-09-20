"""Tests for per-year official placement batch persistence."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from services.database.official_placement import OfficialPlacementRepository
from services.official_placement import OfficialPlacementService


class FakeBatchesCollection:
    def __init__(self):
        self.docs = {}
        self.update_many_calls = []

    def find_one(self, query):
        return self.docs.get(query.get("batch_name"))

    def update_one(self, query, update, upsert=False):
        name = query["batch_name"]
        payload = dict(update.get("$set") or {})
        existed = name in self.docs
        if existed:
            self.docs[name].update(payload)
            return SimpleNamespace(upserted_id=None, acknowledged=True)
        if upsert:
            self.docs[name] = payload
            return SimpleNamespace(upserted_id=f"id-{name}", acknowledged=True)
        return SimpleNamespace(upserted_id=None, acknowledged=True)

    def update_many(self, query, update):
        self.update_many_calls.append((query, update))
        modified = 0
        names = set(query.get("batch_name", {}).get("$nin") or [])
        source = query.get("source")
        for name, doc in list(self.docs.items()):
            if names and name in names:
                continue
            if source and doc.get("source") != source:
                continue
            if "batch_name" in query and "$nin" in query["batch_name"]:
                if name in query["batch_name"]["$nin"]:
                    continue
            doc.update(update.get("$set") or {})
            modified += 1
        return SimpleNamespace(modified_count=modified)


def test_live_sync_upserts_and_skips_seeded_batches():
    collection = FakeBatchesCollection()
    collection.docs["2025"] = {
        "batch_name": "2025",
        "source": "seeded",
        "highlights": [{"title": "260+", "description": "Quality Companies Visited So Far"}],
        "is_active": False,
    }
    collection.docs["2026"] = {
        "batch_name": "2026",
        "source": "live",
        "highlights": [{"title": "old", "description": "old"}],
        "is_active": True,
    }

    repo = OfficialPlacementRepository()
    repo.db_client = SimpleNamespace(official_placement_batches_collection=collection)
    repo.logger = Mock()

    ok = repo.sync_official_placement_batches_from_scrape(
        [
            {
                "batch_name": "2027",
                "is_active": True,
                "highlights": [
                    {"title": "81", "description": "Quality Companies Visited So Far"}
                ],
            },
            {
                "batch_name": "2026",
                "is_active": False,
                "highlights": [
                    {"title": "494", "description": "Quality Companies Visited So Far"}
                ],
            },
        ],
        scrape_timestamp="2026-09-20T12:00:00",
    )

    assert ok is True
    assert collection.docs["2025"]["source"] == "seeded"
    assert collection.docs["2025"]["highlights"][0]["title"] == "260+"
    assert collection.docs["2027"]["source"] == "live"
    assert collection.docs["2027"]["is_active"] is True
    assert collection.docs["2026"]["highlights"][0]["title"] == "494"
    assert collection.docs["2026"]["is_active"] is False


def test_missing_live_year_is_frozen_as_seeded():
    collection = FakeBatchesCollection()
    collection.docs["2026"] = {
        "batch_name": "2026",
        "source": "live",
        "is_active": True,
        "highlights": [{"title": "474", "description": "Quality Companies Visited So Far"}],
    }

    repo = OfficialPlacementRepository()
    repo.db_client = SimpleNamespace(official_placement_batches_collection=collection)
    repo.logger = Mock()

    repo.sync_official_placement_batches_from_scrape(
        [
            {
                "batch_name": "2027",
                "is_active": True,
                "highlights": [
                    {"title": "81", "description": "Quality Companies Visited So Far"}
                ],
            }
        ],
        scrape_timestamp="2026-09-20T12:00:00",
    )

    assert collection.docs["2026"]["source"] == "seeded"
    assert collection.docs["2026"]["is_active"] is False
    assert collection.docs["2026"]["highlights"][0]["title"] == "474"


def test_seed_skips_live_batches_and_loads_default_file():
    collection = FakeBatchesCollection()
    collection.docs["2026"] = {
        "batch_name": "2026",
        "source": "live",
        "highlights": [{"title": "494", "description": "Quality Companies Visited So Far"}],
    }

    repo = OfficialPlacementRepository()
    repo.db_client = SimpleNamespace(official_placement_batches_collection=collection)
    repo.logger = Mock()
    service = OfficialPlacementService(db_service=repo)

    seed_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "official_placement_batches_seed.json"
    )
    stats = service.seed_batches(seed_path=seed_path)

    assert stats["inserted"] >= 2
    assert stats["skipped_live"] == 0
    assert "2025" in collection.docs
    assert collection.docs["2025"]["source"] == "seeded"
    assert "2024" in collection.docs
    assert collection.docs["2024"]["highlights"][0]["title"] == "252+"

    # Seeding again without overwrite should skip existing seeded docs.
    again = service.seed_batches(seed_path=seed_path)
    assert again["skipped_existing"] >= 2
