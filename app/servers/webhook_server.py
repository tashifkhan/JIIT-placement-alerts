"""
Webhook Server

FastAPI-based server for:
- Web push notification subscriptions
- Status/health endpoints
- API endpoints for external integrations
"""

import json
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from core.config import Settings, get_settings, setup_logging

# ============================================================================
# Request/Response Models
# ============================================================================

APP_VERSION = "1.2.1"


class HealthResponse(BaseModel):
    """Health check response"""

    status: str
    version: str = APP_VERSION


class PushSubscription(BaseModel):
    """Web push subscription from client"""

    endpoint: str
    keys: dict[str, str]
    user_id: int = Field(..., gt=0)


class NotifyRequest(BaseModel):
    """Request to send notification"""

    message: str
    title: str | None = "SuperSet Update"
    channels: list[str] | None = None  # ["telegram", "web_push"]


class NotifyResponse(BaseModel):
    """Notification response"""

    success: bool
    results: dict[str, Any] = Field(default_factory=dict)


class StatsResponse(BaseModel):
    """Statistics response"""

    placement_stats: dict[str, Any] = Field(default_factory=dict)
    notice_stats: dict[str, Any] = Field(default_factory=dict)
    user_stats: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# App Factory
# ============================================================================


def create_app(
    settings: Settings | None = None,
    db_service: Any | None = None,
    notification_service: Any | None = None,
    web_push_service: Any | None = None,
) -> FastAPI:
    """
    Create FastAPI application with DI.

    Args:
        settings: Application settings
        db_service: Database service instance
        notification_service: Notification service instance
        web_push_service: Web push service instance

    Returns:
        Configured FastAPI app
    """
    settings = settings or get_settings()
    logger = logging.getLogger("WebhookServer")
    injected_db_service = db_service is not None

    try:
        configured_origins = json.loads(settings.cors_origins)
    except (json.JSONDecodeError, TypeError):
        logger.error("CORS_ORIGINS must be a JSON list", exc_info=True)
        configured_origins = []

    if not isinstance(configured_origins, list):
        logger.error("CORS_ORIGINS must be a JSON list")
        configured_origins = []

    cors_origins = list(
        dict.fromkeys(
            origin.strip()
            for origin in configured_origins
            if isinstance(origin, str) and origin.strip() and origin.strip() != "*"
        )
    )

    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def require_api_key(api_key: str | None = Depends(api_key_header)) -> None:
        """Require the configured API key and fail closed when it is absent."""
        if not settings.webhook_api_key:
            raise HTTPException(status_code=503, detail="Service unavailable")
        if api_key is None or not secrets.compare_digest(
            api_key, settings.webhook_api_key
        ):
            raise HTTPException(status_code=401, detail="Unauthorized")

    def sanitize_api_data(value: Any) -> Any:
        """Copy nested API data while removing private and internal details."""
        if isinstance(value, dict):
            return {
                key: (
                    "Operation failed"
                    if key == "error"
                    else sanitize_api_data(item)
                )
                for key, item in value.items()
                if key != "placements_raw"
            }
        if isinstance(value, list):
            return [sanitize_api_data(item) for item in value]
        if isinstance(value, tuple):
            return tuple(sanitize_api_data(item) for item in value)
        return value

    # App state for dependency injection
    app_state = {
        "settings": settings,
        "db_service": db_service,
        "global_db_service": None,
        "notification_service": notification_service,
        "web_push_service": web_push_service,
        "owned_db_services": [],
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """App lifecycle management"""
        logger.info("Starting webhook server...")

        # Setup services if not provided
        if app_state["db_service"] is None:
            from clients.db_client import DBClient
            from services.database import DatabaseService

            db_client = DBClient()
            db_client.connect()
            app_state["db_service"] = DatabaseService(db_client)
            app_state["owned_db_services"].append(app_state["db_service"])

        if app_state["global_db_service"] is None:
            if injected_db_service:
                # Tests and embedded deployments may intentionally provide one
                # combined repository facade.
                app_state["global_db_service"] = app_state["db_service"]
            else:
                from clients.db_client import DBClient
                from services.database import DatabaseService

                global_db_client = DBClient(use_global_database=True)
                global_db_client.connect()
                app_state["global_db_service"] = DatabaseService(global_db_client)
                app_state["owned_db_services"].append(
                    app_state["global_db_service"]
                )

        if app_state["web_push_service"] is None:
            from services.web_push import WebPushService

            app_state["web_push_service"] = WebPushService(
                db_service=app_state["global_db_service"]
            )

        if app_state["notification_service"] is None:
            from services.notification import NotificationService
            from services.telegram import TelegramService

            telegram = TelegramService(db_service=app_state["global_db_service"])
            app_state["notification_service"] = NotificationService(
                channels=[telegram, app_state["web_push_service"]],
                db_service=app_state["db_service"],
            )

        app.state.services = app_state
        logger.info("Webhook server started")

        yield

        # Cleanup
        for owned_db_service in reversed(app_state["owned_db_services"]):
            owned_db_service.close_connection()
        logger.info("Webhook server stopped")

    app = FastAPI(
        title="SuperSet Webhook Server",
        description="Webhook and API server for SuperSet notifications",
        version=APP_VERSION,
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=bool(cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"] if cors_origins else [],
        allow_headers=["Accept", "Content-Type", "X-API-Key"]
        if cors_origins
        else [],
    )

    # ========================================================================
    # Dependency Injection
    # ========================================================================

    def get_db(request: Request):
        return request.app.state.services["db_service"]

    def get_notification(request: Request):
        return request.app.state.services["notification_service"]

    def get_web_push(request: Request):
        return request.app.state.services["web_push_service"]

    # ========================================================================
    # Health Endpoints
    # ========================================================================

    @app.get("/", response_model=HealthResponse)
    async def root() -> HealthResponse:
        """Root endpoint - health check"""
        return HealthResponse(status="ok")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Health check endpoint"""
        return HealthResponse(status="healthy")

    # ========================================================================
    # Push Subscription Endpoints
    # ========================================================================

    @app.post("/api/push/subscribe", dependencies=[Depends(require_api_key)])
    def subscribe_push(
        subscription: PushSubscription,
        web_push=Depends(get_web_push),
    ) -> dict[str, bool]:
        """Subscribe to web push notifications"""
        if not web_push or not web_push.is_enabled:
            raise HTTPException(
                status_code=501,
                detail="Web push notifications not configured",
            )

        try:
            success = web_push.save_subscription(
                user_id=subscription.user_id,
                subscription={
                    "endpoint": subscription.endpoint,
                    "keys": subscription.keys,
                },
            )
            return {"success": success}
        except Exception:
            logger.error("Failed to save push subscription", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post("/api/push/unsubscribe", dependencies=[Depends(require_api_key)])
    def unsubscribe_push(
        subscription: PushSubscription,
        web_push=Depends(get_web_push),
    ) -> dict[str, bool]:
        """Unsubscribe from web push notifications"""
        if not web_push:
            raise HTTPException(status_code=501, detail="Web push not configured")

        try:
            success = web_push.remove_subscription(
                user_id=subscription.user_id,
                endpoint=subscription.endpoint,
            )
            return {"success": success}
        except Exception:
            logger.error("Failed to remove push subscription", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.get("/api/push/vapid-key")
    def get_vapid_key(web_push=Depends(get_web_push)) -> dict[str, str]:
        """Get VAPID public key for client subscription"""
        if not web_push:
            raise HTTPException(status_code=501, detail="Web push not configured")

        public_key = web_push.get_public_key()
        if not public_key:
            raise HTTPException(status_code=501, detail="VAPID key not configured")

        return {"publicKey": public_key}

    # ========================================================================
    # Notification Endpoints
    # ========================================================================

    @app.post(
        "/api/notify",
        response_model=NotifyResponse,
        dependencies=[Depends(require_api_key)],
    )
    def send_notification(
        request: NotifyRequest,
        notification=Depends(get_notification),
    ) -> NotifyResponse:
        """Send notification to specified channels"""
        if not notification:
            raise HTTPException(
                status_code=501, detail="Notification service not configured"
            )

        try:
            channels = request.channels or ["telegram", "web_push"]
            results = notification.broadcast(
                message=request.message,
                channels=channels,
                title=request.title,
            )
            return NotifyResponse(success=True, results=sanitize_api_data(results))
        except Exception:
            logger.error("Failed to broadcast notification", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post(
        "/api/notify/telegram", dependencies=[Depends(require_api_key)]
    )
    def send_telegram_notification(
        request: NotifyRequest,
        notification=Depends(get_notification),
    ) -> dict[str, bool]:
        """Send notification via Telegram only"""
        if not notification:
            raise HTTPException(
                status_code=501, detail="Notification service not configured"
            )

        try:
            result = notification.send_to_channel(request.message, "telegram")
            return {"success": result}
        except Exception:
            logger.error("Failed to send Telegram notification", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post(
        "/api/notify/web-push", dependencies=[Depends(require_api_key)]
    )
    def send_web_push_notification(
        request: NotifyRequest,
        notification=Depends(get_notification),
    ) -> dict[str, bool]:
        """Send notification via Web Push only"""
        if not notification:
            raise HTTPException(
                status_code=501, detail="Notification service not configured"
            )

        try:
            result = notification.send_to_channel(
                request.message, "web_push", title=request.title
            )
            return {"success": result}
        except Exception:
            logger.error("Failed to send web push notification", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    # ========================================================================
    # Stats Endpoints
    # ========================================================================

    @app.get(
        "/api/stats",
        response_model=StatsResponse,
        dependencies=[Depends(require_api_key)],
    )
    def get_stats(db=Depends(get_db)) -> StatsResponse:
        """Get all statistics"""
        if not db:
            raise HTTPException(status_code=501, detail="Database not configured")

        return StatsResponse(
            placement_stats=sanitize_api_data(db.get_placement_stats()),
            notice_stats=sanitize_api_data(db.get_notice_stats()),
            user_stats=sanitize_api_data(db.get_users_stats()),
        )

    @app.get(
        "/api/stats/placements", dependencies=[Depends(require_api_key)]
    )
    def get_placement_stats(db=Depends(get_db)) -> dict[str, Any]:
        """Get placement statistics"""
        if not db:
            raise HTTPException(status_code=501, detail="Database not configured")

        return sanitize_api_data(db.get_placement_stats())

    @app.get("/api/stats/notices", dependencies=[Depends(require_api_key)])
    def get_notice_stats(db=Depends(get_db)) -> dict[str, Any]:
        """Get notice statistics"""
        if not db:
            raise HTTPException(status_code=501, detail="Database not configured")

        return sanitize_api_data(db.get_notice_stats())

    @app.get("/api/stats/users", dependencies=[Depends(require_api_key)])
    def get_user_stats(db=Depends(get_db)) -> dict[str, Any]:
        """Get user statistics"""
        if not db:
            raise HTTPException(status_code=501, detail="Database not configured")

        return sanitize_api_data(db.get_users_stats())

    # ========================================================================
    # Webhook Endpoints (for external integrations)
    # ========================================================================

    @app.post("/webhook/update", dependencies=[Depends(require_api_key)])
    def trigger_update(
        notification=Depends(get_notification),
        db=Depends(get_db),
    ) -> dict[str, Any]:
        """Trigger update job via webhook"""
        if not notification or not db:
            raise HTTPException(status_code=501, detail="Services not configured")

        try:
            result = notification.send_unsent_notices(telegram=True, web=True)
            return {"success": True, "result": sanitize_api_data(result)}
        except Exception:
            logger.error("Failed to trigger webhook update", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    return app


# ============================================================================
# Standalone Runner
# ============================================================================


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the webhook server"""
    import uvicorn

    setup_logging()
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Webhook Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)
