"""The likely on-campus tag on placement offers."""

from types import SimpleNamespace

import pytest

from services.database.placement_offers import PlacementOfferRepository
from services.placement.extraction.graph import PlacementGraphMixin
from services.placement.extraction.models import PlacementOffer, RolePackage, Student

JOBS = [
    {"id": "acme-sde", "company": "Acme Corp", "job_profile": "Software Engineer"},
    {"id": "tcs-ninja", "company": "Tata Consultancy Services", "job_profile": "Ninja"},
]


class FakeCursor(list):
    def sort(self, *args, **kwargs):
        return self


def _offer(company="Acme Corp", role="Software Engineer"):
    return PlacementOffer(
        company=company,
        roles=[RolePackage(role=role, package=12.0)],
        job_location=["Noida"],
        students_selected=[Student(name="Riya Sharma", enrollment_number="22103001")],
        number_of_offers=1,
    )


def _graph(monkeypatch, payload, jobs=JOBS):
    sent = []

    class FakePrompt:
        def __or__(self, llm):
            return self

        def invoke(self, values):
            sent.append(values)
            return SimpleNamespace(content=payload)

    monkeypatch.setattr(
        "services.placement.extraction.graph.OFFER_ON_CAMPUS_PROMPT", FakePrompt()
    )
    graph = PlacementGraphMixin()
    graph.llm = object()
    graph.likely_on_campus_min_confidence = 0.7
    graph._get_jobs = lambda: jobs
    graph.logger = SimpleNamespace(
        warning=lambda *args, **kwargs: None,
        exception=lambda *args, **kwargs: None,
    )
    return graph, sent


@pytest.mark.parametrize(
    ("payload", "likely", "confidence"),
    [
        ('{"likely_on_campus": true, "confidence": 0.91, "best_job_id": "acme-sde"}', True, 0.91),
        ('{"likely_on_campus": true, "confidence": 0.95, "best_job_id": "invented"}', False, None),
        ('{"likely_on_campus": true, "confidence": 0.65, "best_job_id": "acme-sde"}', False, 0.65),
        ("not json at all", False, None),
    ],
)
def test_offer_tag_validates_job_id_and_threshold(monkeypatch, payload, likely, confidence):
    graph, _ = _graph(monkeypatch, payload)
    state = {"email": {"subject": "Acme results"}, "extracted_offer": _offer()}

    offer = graph._classify_on_campus(state)["extracted_offer"]

    assert offer.likely_on_campus is likely
    assert offer.on_campus_confidence == confidence


def test_offer_with_no_candidate_drive_skips_the_llm(monkeypatch):
    graph, sent = _graph(monkeypatch, '{"likely_on_campus": true}')
    state = {"email": {"subject": "x"}, "extracted_offer": _offer(company="Zzyzx Labs", role="")}

    offer = graph._classify_on_campus(state)["extracted_offer"]

    assert sent == []
    assert offer.likely_on_campus is False
    assert offer.on_campus_confidence is None


def test_student_rows_never_reach_the_judge(monkeypatch):
    graph, sent = _graph(
        monkeypatch,
        '{"likely_on_campus": true, "confidence": 0.9, "best_job_id": "acme-sde"}',
    )
    graph._classify_on_campus({"email": {"subject": "Acme"}, "extracted_offer": _offer()})

    rendered = str(sent[0])
    assert "Riya Sharma" not in rendered
    assert "22103001" not in rendered


def test_acronym_offer_matches_expanded_company(monkeypatch):
    graph, sent = _graph(
        monkeypatch,
        '{"likely_on_campus": true, "confidence": 0.88, "best_job_id": "tcs-ninja"}',
    )
    offer = graph._classify_on_campus(
        {"email": {"subject": "TCS"}, "extracted_offer": _offer(company="TCS", role="Ninja")}
    )["extracted_offer"]

    assert "tcs-ninja" in sent[0]["candidates"]
    assert offer.likely_on_campus is True


def _save_over(monkeypatch, existing, incoming):
    class OffersCollection:
        update = None

        def find(self, query):
            return FakeCursor([existing])

        def update_one(self, query, update):
            OffersCollection.update = update

    repository = PlacementOfferRepository()
    repository.placement_offers_collection = OffersCollection()
    monkeypatch.setattr(repository, "_match_job_by_company", lambda company: None, raising=False)
    repository.save_placement_offers(
        [{"company": "Acme Corp", "roles": [], "students_selected": [], **incoming}]
    )
    return OffersCollection.update["$set"]


def _existing(**campus):
    return {
        "_id": "offer-1",
        "company": "Acme Corp",
        "company_key": "acme corp",
        "roles": [],
        "students_selected": [],
        "number_of_offers": 0,
        **campus,
    }


def test_later_failed_email_does_not_clear_an_earned_tag(monkeypatch):
    saved = _save_over(
        monkeypatch,
        _existing(likely_on_campus=True, on_campus_confidence=0.92),
        {"likely_on_campus": False, "on_campus_confidence": None},
    )

    assert saved["likely_on_campus"] is True
    assert saved["on_campus_confidence"] == 0.92


def test_later_email_can_earn_the_tag(monkeypatch):
    saved = _save_over(
        monkeypatch,
        _existing(likely_on_campus=False, on_campus_confidence=0.3),
        {"likely_on_campus": True, "on_campus_confidence": 0.81},
    )

    assert saved["likely_on_campus"] is True
    assert saved["on_campus_confidence"] == 0.81


def test_untagged_company_takes_the_first_assessment(monkeypatch):
    saved = _save_over(
        monkeypatch,
        _existing(),
        {"likely_on_campus": False, "on_campus_confidence": 0.2},
    )

    assert saved["likely_on_campus"] is False
    assert saved["on_campus_confidence"] == 0.2


def test_judge_output_with_trailing_text_still_parses():
    from services.campus_match import parse_campus_decision

    likely, confidence, job = parse_campus_decision(
        '{"likely_on_campus": true, "confidence": 0.9, "best_job_id": "acme-sde"}\n\n'
        "The offer matches the Acme drive.",
        [{"id": "acme-sde"}],
        0.7,
    )

    assert likely is True
    assert confidence == 0.9
    assert job == {"id": "acme-sde"}
