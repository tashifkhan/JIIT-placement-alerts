import json

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from servers.webhook_server import APP_VERSION, create_app

API_KEY = "test-webhook-key"
ALLOWED_ORIGIN = "https://dashboard.example.com"
NOTIFY_BODY = {"message": "Test notification"}
SUBSCRIPTION_BODY = {
    "endpoint": "https://push.example.com/subscription",
    "keys": {"auth": "auth-key", "p256dh": "public-key"},
    "user_id": 42,
}
PROTECTED_REQUESTS = [
    ("GET", "/api/stats", None),
    ("GET", "/api/stats/placements", None),
    ("GET", "/api/stats/notices", None),
    ("GET", "/api/stats/users", None),
    ("POST", "/api/notify", NOTIFY_BODY),
    ("POST", "/api/notify/telegram", NOTIFY_BODY),
    ("POST", "/api/notify/web-push", NOTIFY_BODY),
    ("POST", "/api/push/subscribe", SUBSCRIPTION_BODY),
    ("POST", "/api/push/unsubscribe", SUBSCRIPTION_BODY),
    ("POST", "/webhook/update", None),
]


class FakeDatabaseService:
    def __init__(self) -> None:
        self.placement_stats = {
            "total": 2,
            "placements_raw": [{"student": "private"}],
            "nested": {
                "placements_raw": [{"student": "also-private"}],
                "visible": True,
            },
            "rows": [{"placements_raw": ["private"], "count": 1}],
        }

    def get_placement_stats(self):
        return self.placement_stats

    def get_notice_stats(self):
        return {"total": 3}

    def get_users_stats(self):
        return {"total": 4}

    def close_connection(self) -> None:
        pass


class FakeNotificationService:
    def broadcast(self, **kwargs):
        return {"telegram": True}

    def send_to_channel(self, *args, **kwargs):
        return True

    def send_unsent_notices(self, **kwargs):
        return {"sent": 1}


class FakeWebPushService:
    is_enabled = True

    def save_subscription(self, **kwargs):
        return True

    def remove_subscription(self, **kwargs):
        return True

    def get_public_key(self):
        return "public-vapid-key"


@pytest.fixture
def fake_db():
    return FakeDatabaseService()


@pytest.fixture
def client(fake_db):
    settings = Settings(
        _env_file=None,
        WEBHOOK_API_KEY=API_KEY,
        CORS_ORIGINS=json.dumps([ALLOWED_ORIGIN]),
    )
    app = create_app(
        settings=settings,
        db_service=fake_db,
        notification_service=FakeNotificationService(),
        web_push_service=FakeWebPushService(),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("method,path,payload", PROTECTED_REQUESTS)
@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_protected_routes_reject_missing_and_wrong_keys(
    client, method, path, payload, headers
):
    request_args = {"headers": headers}
    if payload is not None:
        request_args["json"] = payload

    response = client.request(method, path, **request_args)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize("method,path,payload", PROTECTED_REQUESTS)
def test_protected_routes_accept_correct_key(client, method, path, payload):
    request_args = {"headers": {"X-API-Key": API_KEY}}
    if payload is not None:
        request_args["json"] = payload

    response = client.request(method, path, **request_args)

    assert response.status_code == 200


def test_protected_routes_fail_closed_without_configured_key(fake_db):
    settings = Settings(_env_file=None, WEBHOOK_API_KEY="")
    app = create_app(
        settings=settings,
        db_service=fake_db,
        notification_service=FakeNotificationService(),
        web_push_service=FakeWebPushService(),
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/api/stats", headers={"X-API-Key": "any-key"}
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}


def test_health_and_vapid_key_are_public(client):
    health_response = client.get("/health")
    vapid_response = client.get("/api/push/vapid-key")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "healthy", "version": APP_VERSION}
    assert vapid_response.status_code == 200
    assert vapid_response.json() == {"publicKey": "public-vapid-key"}


@pytest.mark.parametrize("path", ["/api/stats", "/api/stats/placements"])
def test_placement_stats_strip_raw_records_without_mutating_repository_output(
    client, fake_db, path
):
    response = client.get(path, headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert "placements_raw" not in response.text
    assert fake_db.placement_stats["placements_raw"] == [{"student": "private"}]
    assert "placements_raw" in fake_db.placement_stats["nested"]
    assert "placements_raw" in fake_db.placement_stats["rows"][0]


def test_cors_allows_only_configured_origin_with_explicit_options(client):
    allowed_response = client.options(
        "/api/stats",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    denied_response = client.get(
        "/health", headers={"Origin": "https://untrusted.example.com"}
    )

    assert allowed_response.status_code == 200
    assert allowed_response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert allowed_response.headers["access-control-allow-credentials"] == "true"
    assert "*" not in allowed_response.headers["access-control-allow-methods"]
    assert "*" not in allowed_response.headers["access-control-allow-headers"]
    assert "access-control-allow-origin" not in denied_response.headers
