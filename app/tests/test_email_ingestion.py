"""Regression tests for email ingestion identity, IMAP, and privacy behavior."""

from datetime import datetime as RealDateTime
from types import SimpleNamespace

import pytest

from clients.google_groups_client import GoogleGroupsClient
from core.year_context import extract_year_from_email_data, normalize_year
from services.email_notice import document_builder
from services.email_notice.document_builder import EmailNoticeDocumentMixin
from services.email_notice.graph import EmailNoticeGraphMixin
from services.email_notice.models import ExtractedNotice


RAW_EMAIL = b"""From: Placement Cell <placement@example.edu>
To: alerts+202526@example.com
Subject: =?utf-8?Q?Placement_=E2=80=93_?= =?iso-8859-1?Q?Caf=E9?=
Message-ID: <message-1@example.edu>
Date: Tue, 21 Jul 2026 10:30:00 +0530
Content-Type: text/plain; charset=utf-8

Interview notice body.
"""


class FakeIMAP:
    """Small IMAP fake that records UID commands."""

    instances = []

    def __init__(self, host, timeout):
        self.host = host
        self.timeout = timeout
        self.commands = []
        self.logout_calls = 0
        self.__class__.instances.append(self)

    def login(self, email_address, password):
        return "OK", [b"authenticated"]

    def select(self, folder):
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.commands.append((command, args))
        if command == "search":
            return "OK", [b"42"]
        if command == "fetch":
            return "OK", [(b"42 (UID 42 BODY[])", RAW_EMAIL)]
        if command == "store":
            return "OK", [b"42"]
        raise AssertionError(f"Unexpected UID command: {command}")

    def logout(self):
        self.logout_calls += 1
        return "BYE", [b"logout"]


class NoticeBuilder(EmailNoticeDocumentMixin):
    """Minimal concrete builder for document identity tests."""

    db_service = None
    _jobs_cache = None
    logger = SimpleNamespace(warning=lambda *args, **kwargs: None)


class FixedDateTimeOne:
    @classmethod
    def now(cls, tz=None):
        return RealDateTime(2025, 1, 1, tzinfo=tz)


class FixedDateTimeTwo:
    @classmethod
    def now(cls, tz=None):
        return RealDateTime(2026, 1, 1, tzinfo=tz)


def _notice():
    return ExtractedNotice(
        is_notice=True,
        title="Interview Notice",
        content="Interview details for eligible students.",
        type="announcement",
    )


def _email_data(message_id="<message-1@example.edu>"):
    return {
        "message_id": message_id,
        "email_id": "42",
        "imap_uid": "42",
        "sender": "Placement Cell <placement@example.edu>",
        "subject": "Interview Notice",
        "body": "Interview details for eligible students.",
        "time_sent": "",
        "to": "alerts+202526@example.edu",
    }


def test_fetch_uses_body_peek_and_preserves_unseen(monkeypatch):
    FakeIMAP.instances.clear()
    monkeypatch.setattr("clients.google_groups_client.imaplib.IMAP4_SSL", FakeIMAP)
    client = GoogleGroupsClient("alerts@example.edu", "app-password")

    email_data = client.fetch_email("42", mark_as_read=False)

    connection = FakeIMAP.instances[0]
    assert ("fetch", (b"42", "(BODY.PEEK[])")) in connection.commands
    assert not any(command == "store" for command, _ in connection.commands)
    assert email_data["email_id"] == "42"
    assert email_data["imap_uid"] == "42"
    assert email_data["message_id"] == "<message-1@example.edu>"
    assert email_data["subject"] == "Placement \u2013 Caf\u00e9"
    assert connection.timeout == 30.0
    assert connection.logout_calls == 1


def test_bulk_fetch_reuses_one_connection(monkeypatch):
    FakeIMAP.instances.clear()
    monkeypatch.setattr("clients.google_groups_client.imaplib.IMAP4_SSL", FakeIMAP)
    client = GoogleGroupsClient("alerts@example.edu", "app-password")

    emails = client.fetch_unread_emails(mark_as_read=False)

    assert len(emails) == 1
    assert len(FakeIMAP.instances) == 1
    assert FakeIMAP.instances[0].logout_calls == 1


def test_notice_id_is_stable_across_processing_times(monkeypatch):
    builder = NoticeBuilder()
    monkeypatch.setattr(document_builder, "datetime", FixedDateTimeOne)
    first = builder._create_notice_document(_notice(), _email_data())
    monkeypatch.setattr(document_builder, "datetime", FixedDateTimeTwo)
    second = builder._create_notice_document(_notice(), _email_data())

    assert first.id == second.id
    assert first.createdAt != second.createdAt
    assert first.model_dump()["id"] == first.id
    assert "_id" not in first.model_dump()


def test_distinct_message_ids_produce_distinct_notice_ids():
    builder = NoticeBuilder()

    first = builder._create_notice_document(_notice(), _email_data("<one@example.edu>"))
    second = builder._create_notice_document(_notice(), _email_data("<two@example.edu>"))

    assert first.id != second.id


def test_year_alias_is_read_only_from_recipient_headers():
    assert extract_year_from_email_data({"body": "Send to alerts+202526@example.edu"}) is None
    assert (
        extract_year_from_email_data({"delivered_to": "alerts+2025-26@example.edu"})
        == "202526"
    )


@pytest.mark.parametrize("year", ["123456", "202599"])
def test_invalid_academic_year_is_rejected(year):
    with pytest.raises(ValueError):
        normalize_year(year)


def test_policy_extraction_handles_null_slug_and_uses_time_sent(monkeypatch):
    captured = {}

    class FakePolicyPrompt:
        def __or__(self, llm):
            return self

        def invoke(self, values):
            captured.update(values)
            return SimpleNamespace(
                content='[{"slug": null, "badge": null, "updatedDates": null, '
                '"title": "Placement Policy", "content": "Policy", '
                '"description": "Summary"}]'
            )

    monkeypatch.setattr(
        "services.email_notice.graph.POLICY_EXTRACTION_PROMPT", FakePolicyPrompt()
    )
    graph = EmailNoticeGraphMixin()
    graph.llm = object()
    state = {
        "email": {
            "subject": "Policy update",
            "sender": "Placement Cell",
            "time_sent": "2026-07-21T10:30:00+05:30",
            "date": "wrong-date",
            "body": "Policy body",
        }
    }

    result = graph._extract_policy_update(state, {})

    assert result["extracted_policy"].year is None
    assert "2026-07-21T10:30:00+05:30" in captured["email_content"]
    assert "wrong-date" not in captured["email_content"]
