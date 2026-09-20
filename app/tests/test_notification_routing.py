from types import SimpleNamespace

from runners import notification_runner
from services.notification import NotificationService


class FakeNoticeDatabase:
    def __init__(self):
        self.notice = {
            "_id": "notice-1",
            "id": "notice-1",
            "title": "Test notice",
            "content": "Test content",
            "delivery_status": {},
            "sent_to_telegram": False,
        }

    def get_pending_notices(self, channels):
        pending = [
            channel
            for channel in channels
            if not self.notice["delivery_status"].get(channel)
            and not (
                channel == "telegram" and self.notice.get("sent_to_telegram")
            )
        ]
        return [self.notice] if pending else []

    def mark_channel_delivered(self, post_id, channel):
        assert post_id == self.notice["_id"]
        self.notice["delivery_status"][channel] = True
        if channel == "telegram":
            self.notice["sent_to_telegram"] = True
        return True

    def close_connection(self):
        pass


class FakeChannel:
    def __init__(self, channel_name, outcomes):
        self.channel_name = channel_name
        self.outcomes = list(outcomes)
        self.calls = []

    def broadcast_to_all_users(self, message, **kwargs):
        self.calls.append(kwargs)
        return self.outcomes.pop(0)


def test_failed_channel_retry_does_not_duplicate_successful_channel():
    database = FakeNoticeDatabase()
    telegram = FakeChannel(
        "telegram", [{"success": 1, "failed": 0, "total": 1}]
    )
    web = FakeChannel(
        "web_push",
        [
            {"success": 0, "failed": 1, "total": 1},
            {"success": 1, "failed": 0, "total": 1},
        ],
    )
    service = NotificationService(
        channels=[telegram, web],
        db_service=database,
        placement_year="202526",
    )

    first = service.send_unsent_notices(telegram=True, web=True)
    second = service.send_unsent_notices(telegram=True, web=True)

    assert first["failed"] == 1
    assert second["sent"] == 1
    assert len(telegram.calls) == 1
    assert len(web.calls) == 2
    assert telegram.calls[0]["placement_year"] == "202526"
    assert database.notice["delivery_status"] == {
        "telegram": True,
        "web_push": True,
    }


def test_zero_recipient_delivery_requires_explicit_noop_state():
    failed_database = FakeNoticeDatabase()
    empty_channel = FakeChannel(
        "telegram", [{"success": 0, "failed": 0, "total": 0}]
    )
    failed = NotificationService(
        channels=[empty_channel], db_service=failed_database
    ).send_unsent_notices(telegram=True)

    assert failed["failed"] == 1
    assert failed_database.notice["delivery_status"] == {}

    disabled_database = FakeNoticeDatabase()
    disabled_channel = FakeChannel(
        "telegram",
        [{"success": 0, "failed": 0, "total": 0, "disabled": True}],
    )
    succeeded = NotificationService(
        channels=[disabled_channel], db_service=disabled_database
    ).send_unsent_notices(telegram=True)

    assert succeeded["sent"] == 1
    assert disabled_database.notice["delivery_status"]["telegram"] is True


def test_injected_database_is_a_single_scoped_run(monkeypatch):
    database = FakeNoticeDatabase()
    telegram = FakeChannel(
        "telegram", [{"success": 1, "failed": 0, "total": 1}]
    )

    class UnexpectedDBClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Injected mode must not open another database")

    monkeypatch.setattr("clients.db_client.DBClient", UnexpectedDBClient)

    result = notification_runner.send_updates(
        telegram=True,
        db_service=database,
        telegram_service=telegram,
    )

    assert result["sent"] == 1
    assert len(telegram.calls) == 1


def test_multi_year_run_opens_one_global_db_and_filters_users(monkeypatch):
    clients = []
    broadcasts = []

    class FakeDBClient:
        def __init__(self, database_name=None, use_global_database=False, **kwargs):
            self.database_name = "global" if use_global_database else database_name
            self.use_global_database = use_global_database
            self.closed = False
            clients.append(self)

        def connect(self):
            pass

        def close_connection(self):
            self.closed = True

    class FakeDatabaseService:
        def __init__(self, client):
            self.client = client
            self.notice = {
                "_id": client.database_name,
                "title": client.database_name,
                "content": "content",
                "delivery_status": {},
            }

        def get_active_users(self, placement_year=None):
            users = [
                {"user_id": 1, "selected_placement_year": "202526"},
                {"user_id": 2, "selected_placement_year": "202627"},
            ]
            return [
                user
                for user in users
                if user["selected_placement_year"] == placement_year
            ]

        def get_pending_notices(self, channels):
            if self.client.use_global_database:
                return []
            return [self.notice]

        def mark_channel_delivered(self, post_id, channel):
            self.notice["delivery_status"][channel] = True
            return True

        def close_connection(self):
            self.client.close_connection()

    class FakeTelegramService:
        channel_name = "telegram"

        def __init__(self, db_service):
            self.db_service = db_service

        def broadcast_to_all_users(self, message, **kwargs):
            users = self.db_service.get_active_users()
            broadcasts.append((kwargs["placement_year"], [u["user_id"] for u in users]))
            return {"success": len(users), "failed": 0, "total": len(users)}

    monkeypatch.setattr("clients.db_client.DBClient", FakeDBClient)
    monkeypatch.setattr(notification_runner, "DatabaseService", FakeDatabaseService)
    monkeypatch.setattr(notification_runner, "TelegramService", FakeTelegramService)
    monkeypatch.setattr(
        notification_runner, "get_settings", lambda: SimpleNamespace()
    )
    monkeypatch.setattr(
        notification_runner,
        "get_configured_placement_years",
        lambda settings: ["202526", "202627"],
    )

    result = notification_runner.send_updates(telegram=True)

    assert [client.database_name for client in clients] == [
        "global",
        "2025-26",
        "2026-27",
    ]
    assert sum(client.use_global_database for client in clients) == 1
    assert broadcasts == [("202526", [1]), ("202627", [2])]
    assert result["sent"] == 2
    assert all(client.closed for client in clients)
