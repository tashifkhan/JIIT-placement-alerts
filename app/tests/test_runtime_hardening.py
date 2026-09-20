import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clients.superset_client import SupersetClientService, User
from clients.telegram_client import TelegramClient
from core import daemon
from servers import scheduler_server
from servers.bot_server import BotServer
from services.admin_telegram import AdminTelegramService
from services.database.jobs import JobRepository
from services.official_placement import OfficialPlacementData, OfficialPlacementService
from services.telegram import TelegramService
from services.web_push import WebPushService


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


def make_user(user_id):
    return SimpleNamespace(id=user_id)


def test_telegram_html_escapes_input_and_allows_safe_generated_links():
    source = (
        '<b onclick="bad">raw</b> **safe & bold** '
        '[site](https://example.com/?a=1&b=2) '
        '[bad](javascript:alert(1)) <person@example.com>\n> quoted'
    )

    result = TelegramService.convert_markdown_to_html(source)

    assert "&lt;b onclick=&quot;bad&quot;&gt;raw&lt;/b&gt;" in result
    assert "<b>safe &amp; bold</b>" in result
    assert '<a href="https://example.com/?a=1&amp;b=2">site</a>' in result
    assert '<a href="mailto:person@example.com">person@example.com</a>' in result
    assert "<i>quoted</i>" in result
    assert "javascript:" not in result


def test_long_unbroken_message_is_split_without_data_loss():
    service = TelegramService(bot_token="token", chat_id="chat")
    message = "x" * 10_005

    chunks = service.split_long_message(message, max_length=4000)

    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert "".join(chunks) == message


def test_user_send_splits_long_messages_without_data_loss(monkeypatch):
    service = TelegramService(bot_token="token", chat_id="chat")
    sent = []
    monkeypatch.setattr(
        service.client,
        "send_message",
        lambda text, **kwargs: sent.append(text) or True,
    )
    monkeypatch.setattr("services.telegram.time.sleep", lambda _seconds: None)
    message = "x" * 8_500

    assert service.send_to_user(42, message, parse_mode="")
    assert "".join(sent) == message
    assert all(len(chunk) <= 4_000 for chunk in sent)


def test_telegram_client_uses_json_retry_after_and_session(monkeypatch):
    first = Mock(status_code=429, headers={})
    first.json.return_value = {"parameters": {"retry_after": 7}}
    second = Mock(status_code=200, headers={})
    session = Mock()
    session.post.side_effect = [first, second]
    sleeps = []
    monkeypatch.setattr("clients.telegram_client.time.sleep", sleeps.append)
    client = TelegramClient(bot_token="secret", chat_id="1")
    client.session = session

    assert client.send_message("hello", retries=2)
    assert sleeps == [7]
    assert all(call.kwargs["timeout"] == 10 for call in session.post.call_args_list)


def test_telegram_client_does_not_log_token_from_request_exception(caplog):
    session = Mock()
    session.post.side_effect = requests.RequestException(
        "https://api.telegram.org/botVERY_SECRET/sendMessage"
    )
    client = TelegramClient(bot_token="VERY_SECRET", chat_id="1")
    client.session = session

    with caplog.at_level(logging.WARNING):
        assert not client.send_message("hello", retries=1)

    assert "VERY_SECRET" not in caplog.text
    assert "RequestException" in caplog.text


def test_admin_auth_uses_effective_user_and_fails_closed():
    configured = SimpleNamespace(
        admin_telegram_user_ids="[123]",
        telegram_chat_id="999",
    )
    service = AdminTelegramService(configured, Mock(), Mock())
    allowed_message = FakeMessage()
    denied_message = FakeMessage()

    allowed = asyncio.run(
        service._is_admin(
            SimpleNamespace(effective_user=make_user(123), message=allowed_message)
        )
    )
    denied = asyncio.run(
        service._is_admin(
            SimpleNamespace(effective_user=make_user(999), message=denied_message)
        )
    )

    assert allowed is True
    assert denied is False
    assert denied_message.replies

    empty = AdminTelegramService(
        SimpleNamespace(admin_telegram_user_ids="", telegram_chat_id="123"),
        Mock(),
        Mock(),
    )
    assert not asyncio.run(
        empty._is_admin(
            SimpleNamespace(effective_user=make_user(123), message=FakeMessage())
        )
    )


def test_userstats_routes_through_admin_check():
    admin = Mock()

    async def deny(_update):
        return False

    admin._is_admin = deny
    db = Mock()
    server = BotServer(
        settings=SimpleNamespace(telegram_bot_token=""),
        db_service=db,
        admin_service=admin,
    )

    asyncio.run(
        server.user_stats_command(
            SimpleNamespace(message=FakeMessage()), SimpleNamespace()
        )
    )

    db.get_users_stats.assert_not_called()


def test_scheduler_uses_one_stable_update_cron(monkeypatch):
    class FakeScheduler:
        def __init__(self, **kwargs):
            self.jobs = []
            self.running = False

        def add_job(self, function, **kwargs):
            self.jobs.append((function, kwargs))

        def start(self):
            self.running = True

    monkeypatch.setattr(scheduler_server, "AsyncIOScheduler", FakeScheduler)
    server = scheduler_server.SchedulerServer(settings=SimpleNamespace())
    server.setup_scheduler()

    update_jobs = [job for job in server.scheduler.jobs if job[1]["id"] == "scheduled_update"]
    assert len(update_jobs) == 1
    options = update_jobs[0][1]
    assert options["hour"] == "0,8-23"
    assert options["replace_existing"] is True
    assert options["coalesce"] is True
    assert options["max_instances"] == 1
    assert options["misfire_grace_time"] > 0


def test_scheduler_overlap_guard_skips_when_locked():
    server = scheduler_server.SchedulerServer(settings=SimpleNamespace())

    async def run_test():
        async with server._update_lock:
            await server.run_scheduled_update()

    asyncio.run(run_test())


class FakeCollection:
    def __init__(self):
        self.calls = []

    def update_one(self, query, update):
        self.calls.append((query, update))
        return SimpleNamespace(matched_count=1)

    def update_many(self, query, update):
        self.calls.append((query, update))
        return SimpleNamespace(matched_count=1)


def test_web_push_validates_and_persists_subscriptions_atomically():
    collection = FakeCollection()
    service = WebPushService(db_service=SimpleNamespace(users_collection=collection))
    subscription = {
        "endpoint": "https://push.example/subscription",
        "keys": {"p256dh": "public-key", "auth": "auth-key"},
    }

    assert service.save_subscription(42, subscription)
    assert isinstance(collection.calls[0][1], list)
    assert service.remove_subscription(42, subscription["endpoint"])
    assert collection.calls[1][1] == {
        "$pull": {"push_subscriptions": {"endpoint": subscription["endpoint"]}}
    }
    assert not service.save_subscription(
        42,
        {"endpoint": "javascript:bad", "keys": subscription["keys"]},
    )


def test_expired_web_push_subscription_is_removed_globally():
    collection = FakeCollection()
    service = WebPushService(db_service=SimpleNamespace(users_collection=collection))

    service._remove_subscription({"endpoint": "https://push.example/expired"})

    assert collection.calls == [
        (
            {"push_subscriptions.endpoint": "https://push.example/expired"},
            {
                "$pull": {
                    "push_subscriptions": {
                        "endpoint": "https://push.example/expired"
                    }
                }
            },
        )
    ]


def test_web_push_reports_explicit_noop_without_subscriptions():
    service = WebPushService(
        vapid_private_key="configured",
        vapid_public_key="public",
        vapid_email="admin@example.com",
        db_service=SimpleNamespace(get_active_users=lambda _year=None: []),
    )

    result = service.broadcast_to_all_users("message", placement_year="202526")

    assert result == {
        "success": 0,
        "failed": 0,
        "total": 0,
        "noop": True,
    }


def test_daemon_refuses_to_signal_unrelated_pid(monkeypatch):
    signals = []
    monkeypatch.setattr(daemon, "read_pid_file", lambda _name: 1234)
    monkeypatch.setattr(daemon, "_is_expected_daemon_process", lambda *_args: False)
    monkeypatch.setattr(daemon.os, "kill", lambda *args: signals.append(args))

    assert daemon.stop_daemon("scheduler") is False
    assert signals == []


def test_superset_session_requests_have_timeouts_and_safe_deduplication():
    responses = []
    for notices in (
        [
            {
                "identifier": "one",
                "title": "One",
                "content": "",
                "lastModifiedOn": None,
                "publishedAt": 1,
            },
            {"title": "missing identifier"},
        ],
        [
            {
                "identifier": "one",
                "title": "Duplicate",
                "content": "",
                "publishedAt": 1,
            },
            {
                "identifier": "two",
                "title": "Two",
                "content": "",
                "publishedAt": 2,
            },
        ],
    ):
        response = Mock()
        response.json.return_value = notices
        responses.append(response)

    session = Mock()
    session.get.side_effect = responses
    client = SupersetClientService()
    client.session = session
    users = [
        User(
            userId=index,
            username=f"user{index}",
            name="User",
            emailHash="hash",
            sessionKey="session",
            uuid=f"uuid{index}",
            refreshToken="refresh",
            userProfilePhotoId="photo",
            userModes=[],
            permissions=[],
            emailVerified=True,
            enableMfa=False,
        )
        for index in (1, 2)
    ]

    notices = client.get_notices(users)

    assert [notice.id for notice in notices] == ["two", "one"]
    assert all(
        call.kwargs["timeout"] == client.request_timeout
        for call in session.get.call_args_list
    )


def test_official_placement_save_failure_is_reported():
    data = OfficialPlacementData(scrape_timestamp="now")
    db = Mock()
    db.save_official_placement_data.return_value = False
    service = OfficialPlacementService(db_service=db)
    service.scrape = Mock(return_value=data)

    assert service.scrape_and_save() is None


def test_jobs_are_sorted_by_source_created_at():
    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = []
    collection = Mock()
    collection.find.return_value = cursor
    repository = JobRepository()
    repository.jobs_collection = collection

    assert repository.get_all_jobs() == []
    cursor.sort.assert_called_once_with("createdAt", -1)
