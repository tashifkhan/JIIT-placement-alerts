"""
Webhook Server

FastAPI-based server for:
- Web push notification subscriptions
- Status/health endpoints
- API endpoints for external integrations
"""

import logging
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import Settings, get_settings, setup_logging


# ============================================================================
# Request/Response Models
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response"""

    status: str
    version: str = "1.2.1"


class PushSubscription(BaseModel):
    """Web push subscription from client"""

    endpoint: str
    keys: Dict[str, str]
    user_id: Optional[int] = None


class NotifyRequest(BaseModel):
    """Request to send notification"""

    message: str
    title: Optional[str] = "SuperSet Update"
    channels: Optional[List[str]] = None  # ["telegram", "web_push"]


class NotifyResponse(BaseModel):
    """Notification response"""

    success: bool
    results: Dict[str, Any] = {}


class StatsResponse(BaseModel):
    """Statistics response"""

    placement_stats: Dict[str, Any] = {}
    notice_stats: Dict[str, Any] = {}
    user_stats: Dict[str, Any] = {}


# ============================================================================
# App Factory
# ============================================================================


def create_app(
    settings: Optional[Settings] = None,
    db_service: Optional[Any] = None,
    notification_service: Optional[Any] = None,
    web_push_service: Optional[Any] = None,
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

    # App state for dependency injection
    app_state = {
        "settings": settings,
        "db_service": db_service,
        "notification_service": notification_service,
        "web_push_service": web_push_service,
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """App lifecycle management"""
        logger = logging.getLogger("WebhookServer")
        logger.info("Starting webhook server...")

        # Setup services if not provided
        if app_state["db_service"] is None:
            from services.database_service import DatabaseService

            app_state["db_service"] = DatabaseService()

        if app_state["web_push_service"] is None:
            from services.web_push_service import WebPushService

            app_state["web_push_service"] = WebPushService(
                db_service=app_state["db_service"]
            )

        if app_state["notification_service"] is None:
            from services.notification_service import NotificationService
            from services.telegram_service import TelegramService

            telegram = TelegramService(db_service=app_state["db_service"])
            app_state["notification_service"] = NotificationService(
                channels=[telegram, app_state["web_push_service"]],
                db_service=app_state["db_service"],
            )

        app.state.services = app_state
        logger.info("Webhook server started")

        yield

        # Cleanup
        if app_state["db_service"]:
            app_state["db_service"].close_connection()
        logger.info("Webhook server stopped")

    app = FastAPI(
        title="SuperSet Webhook Server",
        description="Webhook and API server for SuperSet notifications",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
    async def root():
        """Root endpoint - health check"""
        return HealthResponse(status="ok")

    @app.get("/health", response_model=HealthResponse)
    async def health():
        """Health check endpoint"""
        return HealthResponse(status="healthy")

    # ========================================================================
    # Push Subscription Endpoints
    # ========================================================================

    @app.post("/api/push/subscribe")
    async def subscribe_push(
        subscription: PushSubscription,
        web_push=Depends(get_web_push),
    ):
        """Subscribe to web push notifications"""
        if not web_push or not web_push.is_enabled:
            raise HTTPException(
                status_code=501,
                detail="Web push notifications not configured",
            )

        try:
            success = web_push.save_subscription(
                user_id=subscription.user_id or 0,
                subscription={
                    "endpoint": subscription.endpoint,
                    "keys": subscription.keys,
                },
            )
            return {"success": success}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/push/unsubscribe")
    async def unsubscribe_push(
        subscription: PushSubscription,
        web_push=Depends(get_web_push),
    ):
        """Unsubscribe from web push notifications"""
        if not web_push:
            raise HTTPException(status_code=501, detail="Web push not configured")

        try:
            success = web_push.remove_subscription(
                user_id=subscription.user_id or 0,
                endpoint=subscription.endpoint,
            )
            return {"success": success}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/push/vapid-key")
    async def get_vapid_key(web_push=Depends(get_web_push)):
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

    @app.post("/api/notify", response_model=NotifyResponse)
    async def send_notification(
        request: NotifyRequest,
        notification=Depends(get_notification),
    ):
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
            return NotifyResponse(success=True, results=results)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/notify/telegram")
    async def send_telegram_notification(
        request: NotifyRequest,
        notification=Depends(get_notification),
    ):
        """Send notification via Telegram only"""
        if not notification:
            raise HTTPException(
                status_code=501, detail="Notification service not configured"
            )

        try:
            result = notification.send_to_channel(request.message, "telegram")
            return {"success": result}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/notify/web-push")
    async def send_web_push_notification(
        request: NotifyRequest,
        notification=Depends(get_notification),
    ):
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
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ========================================================================
    # Stats Endpoints
    # ========================================================================

    @app.get("/api/stats", response_model=StatsResponse)
    async def get_stats(db=Depends(get_db)):
        """Get all statistics"""
        if not db:
            raise HTTPException(status_code=501, detail="Database not configured")

        return StatsResponse(
            placement_stats=db.get_placement_stats(),
            notice_stats=db.get_notice_stats(),
            user_stats=db.get_users_stats(),
        )

    @app.get("/api/stats/placements")
    async def get_placement_stats(db=Depends(get_db)):
        """Get placement statistics"""
        if not db:
            raise HTTPException(status_code=501, detail="Database not configured")

        return db.get_placement_stats()

    @app.get("/api/stats/notices")
    async def get_notice_stats(db=Depends(get_db)):
        """Get notice statistics"""
        if not db:
            raise HTTPException(status_code=501, detail="Database not configured")

        return db.get_notice_stats()

    @app.get("/api/stats/users")
    async def get_user_stats(db=Depends(get_db)):
        """Get user statistics"""
        if not db:
            raise HTTPException(status_code=501, detail="Database not configured")

        return db.get_users_stats()

    # ========================================================================
    # Webhook Endpoints (for external integrations)
    # ========================================================================

    @app.post("/webhook/update")
    async def trigger_update(
        notification=Depends(get_notification),
        db=Depends(get_db),
    ):
        """Trigger update job via webhook"""
        if not notification or not db:
            raise HTTPException(status_code=501, detail="Services not configured")

        try:
            result = notification.send_unsent_notices(telegram=True, web=True)
            return {"success": True, "result": result}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app


# ============================================================================
# Standalone Runner
# ============================================================================


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the webhook server"""
    import uvicorn

    setup_logging()
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Webhook Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)
