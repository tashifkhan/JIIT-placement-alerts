"""
Centralized Configuration Management

This module provides type-safe configuration using Pydantic Settings.
All environment variables are validated and typed.
"""

import os
import logging
from typing import Optional
from functools import lru_cache


from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables.
    The .env file is automatically loaded if present.
    """

    # MongoDB
    mongo_connection_str: str = Field(
        default="",
        validation_alias="MONGO_CONNECTION_STR",
        description="MongoDB connection string",
    )

    # Telegram Bot
    telegram_bot_token: str = Field(
        default="",
        validation_alias="TELEGRAM_BOT_TOKEN",
        description="Telegram bot token from @BotFather",
    )
    telegram_chat_id: str = Field(
        default="",
        validation_alias="TELEGRAM_CHAT_ID",
        description="Default Telegram chat ID for notifications",
    )

    # SuperSet Credentials
    superset_credentials: str = Field(
        default="[]",
        validation_alias="SUPERSET_CREDENTIALS",
        description="JSON list of SuperSet credentials [{'email': '...', 'password': '...'}]",
    )

    # Google AI (Gemini)
    google_api_key: str = Field(
        default="",
        validation_alias="GOOGLE_API_KEY",
        description="Google API key for Gemini LLM",
    )

    # Placement Email (for reading offer letters)
    placement_email: str = Field(
        default="",
        validation_alias="PLCAMENT_EMAIL",
        description="Email address for placement offers",
    )
    placement_app_password: str = Field(
        default="",
        validation_alias="PLCAMENT_APP_PASSWORD",
        description="App password for placement email",
    )

    # Web Push (VAPID keys)
    vapid_private_key: str = Field(
        default="",
        validation_alias="VAPID_PRIVATE_KEY",
        description="VAPID private key for web push",
    )
    vapid_public_key: str = Field(
        default="",
        validation_alias="VAPID_PUBLIC_KEY",
        description="VAPID public key for web push",
    )
    vapid_email: str = Field(
        default="",
        validation_alias="VAPID_EMAIL",
        description="Contact email for VAPID",
    )

    # Server Configuration
    webhook_port: int = Field(
        default=8000,
        validation_alias="WEBHOOK_PORT",
        description="Port for webhook server",
    )
    webhook_host: str = Field(
        default="0.0.0.0",
        validation_alias="WEBHOOK_HOST",
        description="Host for webhook server",
    )

    # Daemon Mode
    daemon_mode: bool = Field(
        default=False,
        validation_alias="DAEMON_MODE",
        description="Run in daemon mode (suppress stdout)",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
        description="Logging level",
    )
    log_file: str = Field(
        default="logs/superset_bot.log",
        validation_alias="LOG_FILE",
        description="Log file path",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra env vars


# Global daemon mode flag (for backward compatibility)
_DAEMON_MODE = False


def set_daemon_mode(enabled: bool = True) -> None:
    """Set the global daemon mode flag"""
    global _DAEMON_MODE
    _DAEMON_MODE = enabled


def is_daemon_mode() -> bool:
    """Check if running in daemon mode"""
    return _DAEMON_MODE


def safe_print(*args, **kwargs) -> None:
    """Print only if not in daemon mode"""
    if not _DAEMON_MODE:
        print(*args, **kwargs)
    else:
        logger = logging.getLogger("SuperSetBot")
        msg = " ".join(str(arg) for arg in args)
        if msg:
            logger.info(msg)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get settings instance (cached).

    Settings are loaded once and cached for the lifetime of the process.
    """
    from dotenv import load_dotenv

    load_dotenv()
    return Settings()


def setup_logging(settings: Optional[Settings] = None) -> logging.Logger:
    """
    Setup logging configuration.

    Args:
        settings: Optional settings object. If None, uses get_settings().

    Returns:
        Root logger instance
    """
    settings = settings or get_settings()

    # Create logs directory if needed
    log_dir = os.path.dirname(settings.log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Configure logging format
    log_format = (
        "%(asctime)s - %(name)s - %(levelname)s - "
        "%(funcName)s:%(lineno)d - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    # Determine log level
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Configure handlers
    handlers: list[logging.Handler] = [logging.FileHandler(settings.log_file, mode="a", encoding="utf-8")]

    if not settings.daemon_mode:
        handlers.append(logging.StreamHandler())

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        handlers=handlers,
    )

    # Reduce noise from third-party libraries
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger = logging.getLogger("SuperSetBot")
    logger.info(
        f"Logging initialized. Level: {settings.log_level}, "
        f"Daemon: {settings.daemon_mode}"
    )

    return logger
