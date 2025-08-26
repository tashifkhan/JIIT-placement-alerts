import logging
import inspect
from datetime import datetime

"""
Global configuration for SuperSet Telegram Bot

This module provides global configuration variables that can be accessed
across all modules, particularly for daemon mode support.
"""

# Global daemon mode flag
DAEMON_MODE = False


def set_daemon_mode(enabled=True):
    """Set the global daemon mode flag"""
    global DAEMON_MODE
    DAEMON_MODE = enabled


def is_daemon_mode():
    """Check if running in daemon mode"""
    return DAEMON_MODE


def safe_print(*args, **kwargs):
    """Print only if not in daemon mode"""
    if not DAEMON_MODE:
        print(*args, **kwargs)
    else:
        logger = logging.getLogger("SuperSetTelegramBot")
        if not logger.hasHandlers():
            handler = logging.FileHandler("superset_telegram_bot.log")
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

        frame = inspect.currentframe().f_back
        func_name = frame.f_code.co_name
        line_no = frame.f_lineno
        msg = " ".join(str(arg) for arg in args)
        if msg:
            logger.info(f"{func_name}:{line_no} - {msg}")
