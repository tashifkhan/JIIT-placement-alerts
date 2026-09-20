"""
Centralized Configuration Management

This module provides type-safe configuration using Pydantic Settings.
All environment variables are validated and typed.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    mongo_database_name: str = Field(
        default="",
        validation_alias="MONGO_DATABASE_NAME",
        description="MongoDB database name",
    )
    active_placement_year: str = Field(
        default="202526",
        validation_alias="ACTIVE_PLACEMENT_YEAR",
        description="Active placement year in compact format, e.g. 202526",
    )
    default_placement_year: str = Field(
        default="202526",
        validation_alias="DEFAULT_PLACEMENT_YEAR",
        description="Default placement year for users without a preference",
    )
    global_database_name: str = Field(
        default="PlacementBotGlobal",
        validation_alias="GLOBAL_DATABASE_NAME",
        description="MongoDB database name for global users and preferences",
    )
    placement_years: str = Field(
        default='["202526", "202627"]',
        validation_alias="PLACEMENT_YEARS",
        description="JSON list of configured placement years",
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
    superset_credentials_by_year: str = Field(
        default="",
        validation_alias="SUPERSET_CREDENTIALS_BY_YEAR",
        description="JSON map of placement year to SuperSet credentials",
    )

    # Google AI (Gemini)
    google_api_key: str = Field(
        default="",
        validation_alias="GOOGLE_API_KEY",
        description="Google API key for Gemini LLM",
    )
    llm_model: str = Field(
        default="gemini-3.8-flash",
        validation_alias="LLM_MODEL",
        description="Gemini model id used by every LangGraph pipeline",
    )
    llm_thinking_level: str = Field(
        default="low",
        validation_alias="LLM_THINKING_LEVEL",
        description="Gemini 3 thinking level: low, medium, or high",
    )
    llm_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="LLM_TIMEOUT_SECONDS",
        gt=0,
        description="Maximum seconds to wait for one LLM request",
    )
    llm_max_retries: int = Field(
        default=2,
        validation_alias="LLM_MAX_RETRIES",
        ge=0,
        description="Maximum automatic retries for one LLM request",
    )
    likely_on_campus_min_confidence: float = Field(
        default=0.7,
        validation_alias="LIKELY_ON_CAMPUS_MIN_CONFIDENCE",
        ge=0,
        le=1,
        description="Minimum model confidence required for the likely-on-campus tag",
    )

    # Placement Email (for reading offer letters)
    placement_email: str = Field(
        default="",
        validation_alias=AliasChoices("PLACEMENT_EMAIL", "PLCAMENT_EMAIL"),
        description="Email address for placement offers",
    )
    placement_app_password: str = Field(
        default="",
        validation_alias=AliasChoices("PLACEMENT_APP_PASSWORD", "PLCAMENT_APP_PASSWORD"),
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
        default="127.0.0.1",
        validation_alias="WEBHOOK_HOST",
        description="Host for webhook server",
    )
    webhook_api_key: str = Field(
        default="",
        validation_alias="WEBHOOK_API_KEY",
        description="API key required by protected webhook endpoints",
    )
    cors_origins: str = Field(
        default="[]",
        validation_alias="CORS_ORIGINS",
        description="JSON list of origins allowed to access the webhook API",
    )
    admin_telegram_user_ids: str = Field(
        default="[]",
        validation_alias="ADMIN_TELEGRAM_USER_IDS",
        description="JSON list of Telegram user IDs allowed to use admin features",
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
        description="Log file path (Bot)",
    )
    scheduler_log_file: str = Field(
        default="logs/scheduler.log",
        validation_alias="SCHEDULER_LOG_FILE",
        description="Log file path (Scheduler)",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


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
    from pathlib import Path

    from dotenv import load_dotenv

    # Determine paths relative to this file
    # file at: app/core/config.py
    # app dir: app/
    # root dir: project root (where .env usually is)

    # Try multiple locations for .env
    base_dir = Path(__file__).resolve().parent.parent.parent
    env_path = base_dir / ".env"

    if not env_path.exists():
        # Fallback to app directory
        env_path = base_dir / "app" / ".env"

    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path))
    else:
        # Fallback to default behavior (search in CWD)
        load_dotenv()

    return Settings()


def setup_logging(settings: Settings | None = None) -> logging.Logger:
    """
    Setup logging configuration.

    Args:
        settings: Optional settings object. If None, uses get_settings().

    Returns:
        Root logger instance
    """
    settings = settings or get_settings()

    # Configure handlers - use global daemon mode flag (set via CLI -d/--daemon)
    daemon = is_daemon_mode()

    # Ensure log file path is absolute using the same logic as get_settings
    log_path = Path(settings.log_file)
    if not log_path.is_absolute():
        base_dir = Path(__file__).resolve().parent.parent.parent
        log_path = base_dir / settings.log_file

    # Create logs directory if needed (using absolute path)
    log_dir = log_path.parent
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

    handlers: list[logging.Handler] = [
        logging.FileHandler(
            str(log_path),
            mode="a",
            encoding="utf-8",
        )
    ]

    if not daemon:
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
        f"Logging initialized. Level: {settings.log_level}, " f"Daemon: {daemon}"
    )

    return logger
