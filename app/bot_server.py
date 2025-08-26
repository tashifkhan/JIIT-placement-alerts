"""
SuperSet Telegram Bot Server

This file runs the Telegram bot server to handle user interactions and
schedules the main scraping/notification process to run 3 times a day.

Schedule:
- 12:00 PM IST (Indian Standard Time)
- 12:00 AM IST (Midnight)
- 6:00 PM IST

Features:
- User registration via /start command
- User management (start/stop subscriptions)
- Scheduled job posting notifications to all registered users
- Database-driven user management
- Daemon mode support with comprehensive logging
"""

import os
import sys
import logging
import argparse
from datetime import datetime
import pytz
from telegram_handeller import TelegramBot
import schedule
import time
import threading
from main import main as run_main_process
import subprocess


def setup_logging(daemon_mode=False):
    """Setup logging configuration for daemon and normal modes"""
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_file = os.path.join(logs_dir, "superset_bot.log")

    # Configure logging format
    log_format = (
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.FileHandler(log_file, mode="a", encoding="utf-8"),
            logging.StreamHandler() if not daemon_mode else logging.NullHandler(),
        ],
    )

    # Set specific loggers to appropriate levels
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Mode: {'Daemon' if daemon_mode else 'Normal'}")
    logger.info(f"Log file: {log_file}")

    return logger


class BotServer:
    def __init__(self, daemon_mode=False):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.daemon_mode = daemon_mode
        self.telegram_bot = TelegramBot()
        self.ist = pytz.timezone("Asia/Kolkata")
        self.running = True

        self.logger.info(
            f"BotServer initialized in {'daemon' if daemon_mode else 'normal'} mode"
        )

    def scheduled_job(self):
        """Run the main scraping and notification process"""
        self.logger.info("Starting scheduled job execution")
        try:
            current_time = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S IST")

            if not self.daemon_mode:
                print(f"\n{'='*60}")
                print(f"SCHEDULED JOB STARTED AT {current_time}")
                print(f"{'='*60}")

            self.logger.info(f"SCHEDULED JOB STARTED AT {current_time}")

            # Run the main process (scraping + formatting + sending)
            result = run_main_process(daemon_mode=self.daemon_mode)

            if result == 0:
                success_msg = (
                    f"✅ Scheduled job completed successfully at {current_time}"
                )
                self.logger.info(success_msg)
                if not self.daemon_mode:
                    print(success_msg)
            else:
                error_msg = f"❌ Scheduled job completed with issues at {current_time} (exit code: {result})"
                self.logger.warning(error_msg)
                if not self.daemon_mode:
                    print(error_msg)

        except Exception as e:
            error_msg = f"❌ Error in scheduled job: {e}"
            self.logger.error(error_msg, exc_info=True)
            if not self.daemon_mode:
                print(error_msg)

    def setup_schedule(self):
        """Setup the scheduled jobs for 3 times a day"""
        self.logger.info("Setting up scheduled jobs")

        schedule.every().day.at("09:00").do(self.scheduled_job)
        schedule.every().day.at("12:00").do(self.scheduled_job)
        schedule.every().day.at("15:00").do(self.scheduled_job)
        schedule.every().day.at("18:00").do(self.scheduled_job)
        schedule.every().day.at("20:00").do(self.scheduled_job)
        schedule.every().day.at("00:00").do(self.scheduled_job)

        schedule_msg = "📅 Scheduled jobs setup: 9:00 AM, 12:00 PM, 3:00 PM, 6:00 PM, 8:00 PM, 12:00 AM IST"
        self.logger.info(schedule_msg)

        if not self.daemon_mode:
            print("📅 Scheduled jobs setup:")
            print("   - 9:00 AM IST (Morning)")
            print("   - 12:00 PM IST (Noon)")
            print("   - 3:00 PM IST (Afternoon)")
            print("   - 6:00 PM IST (Evening)")
            print("   - 8:00 PM IST (Night)")
            print("   - 12:00 AM IST (Midnight)")

    def run_scheduler(self):
        """Run the scheduler in a separate thread"""
        self.logger.info("Starting job scheduler thread")
        if not self.daemon_mode:
            print("🕐 Starting job scheduler...")

        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

        self.logger.info("Job scheduler thread stopped")

    def start_bot_and_scheduler(self):
        """Start both the Telegram bot and the scheduler"""
        self.logger.info("Starting SuperSet Telegram Bot Server")
        try:
            if not self.daemon_mode:
                print("Starting SuperSet Telegram Bot Server...")

            # Setup scheduled jobs
            self.setup_schedule()

            # Start scheduler in a separate thread
            scheduler_thread = threading.Thread(target=self.run_scheduler, daemon=True)
            scheduler_thread.start()
            self.logger.info("Scheduler thread started")

            # Get current time in IST
            current_time = datetime.now(self.ist)
            time_msg = (
                f"🕐 Current time (IST): {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.logger.info(time_msg)

            if not self.daemon_mode:
                print(time_msg)

            # Show user statistics
            self.telegram_bot.get_user_stats()

            start_msg = "Starting Telegram bot server..."
            self.logger.info(start_msg)
            if not self.daemon_mode:
                print(start_msg)
                print("Send /start to the bot to register for notifications!")
            # Start the bot server (this will block)
            self.telegram_bot.start_bot_server()

        except KeyboardInterrupt:
            shutdown_msg = "Shutting down bot server..."
            self.logger.info(shutdown_msg)
            if not self.daemon_mode:
                print(f"\n{shutdown_msg}")
            self.running = False
        except Exception as e:
            error_msg = f"Error starting bot server: {e}"
            self.logger.error(error_msg, exc_info=True)
            if not self.daemon_mode:
                print(error_msg)

    def start_bot(self):
        """Start the Telegram bot server"""
        self.logger.info("Starting SuperSet Telegram Bot Server")
        try:
            if not self.daemon_mode:
                print("Starting SuperSet Telegram Bot Server...")

            # Get current time in IST
            current_time = datetime.now(self.ist)
            time_msg = (
                f"🕐 Current time (IST): {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.logger.info(time_msg)

            if not self.daemon_mode:
                print(time_msg)

            # Show user statistics
            self.telegram_bot.get_user_stats()

            start_msg = "Starting Telegram bot server..."
            self.logger.info(start_msg)
            if not self.daemon_mode:
                print(start_msg)
                print("Send /start to the bot to register!")
            # Start the bot server (this will block)
            self.telegram_bot.start_bot_server()

        except KeyboardInterrupt:
            shutdown_msg = "Shutting down bot server..."
            self.logger.info(shutdown_msg)
            if not self.daemon_mode:
                print(f"\n{shutdown_msg}")

        except Exception as e:
            error_msg = f"Error starting bot server: {e}"
            self.logger.error(error_msg, exc_info=True)
            if not self.daemon_mode:
                print(error_msg)

    def run_once_now(self):
        """Run the job once immediately (for testing)"""
        self.logger.info("Running job immediately for testing")
        if not self.daemon_mode:
            print("Running job immediately for testing...")
        self.scheduled_job()


def _run_server_child(daemon_mode: bool):
    """Entry point for the spawned child process.

    This runs in a fresh process created with the 'spawn' start method which
    avoids fork-related deadlocks when the parent is multi-threaded.
    """
    # Configure logging for the child process (daemon mode controls handlers)
    setup_logging(daemon_mode=daemon_mode)

    bot_server = BotServer(daemon_mode=daemon_mode)
    bot_server.start_bot_and_scheduler()


def spawn_daemon_process():
    """Spawn a detached child process using subprocess.

    Uses start_new_session=True to detach from the controlling terminal and
    redirects std streams to /dev/null. Sets an environment marker so the
    child won't re-spawn itself.
    """
    python = sys.executable or "python3"
    script = os.path.abspath(__file__)

    # Build args: preserve -u for unbuffered output if present, pass --daemon flag
    args = [python, script, "--daemon"]

    # Prepare environment for child: mark it as the daemon child
    env = os.environ.copy()
    env["SUPERSET_DAEMON_CHILD"] = "1"

    # Redirect std streams to /dev/null so child detaches cleanly
    devnull = open(os.devnull, "r+")

    p = subprocess.Popen(
        args,
        env=env,
        stdin=devnull,
        stdout=devnull,
        stderr=devnull,
        start_new_session=True,
        close_fds=True,
    )

    print(f"Daemon process started with pid={p.pid}")
    sys.exit(0)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="SuperSet Telegram Bot Server")
    parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Run in daemon/detached mode with logging to file",
    )
    parser.add_argument(
        "--help-extended", action="store_true", help="Show extended help message"
    )

    args = parser.parse_args()

    if args.help_extended:
        print("SuperSet Telegram Bot Server")
        print("\nUsage:")
        print("  python app.py                - Start bot server with scheduler")
        print("  python app.py -d             - Start bot server in daemon mode")
        print("  python app.py --daemon       - Start bot server in daemon mode")
        print(
            "  python app.py --run-once     - Run scraping job once and send to all users if new posts found"
        )
        print("  python app.py --help-extended - Show this help message")
        print("\nDaemon Mode:")
        print("  In daemon mode, the process runs in the background and all output")
        print("  is logged to 'logs/superset_bot.log' file instead of console.")
        print("  Use this mode for production deployments.")
        print("\nRun-Once Mode:")
        print("  The --run-once command will:")
        print("  1. Scrape for new job posts")
        print(
            "  2. Only proceed with formatting and notifications if NEW posts are found"
        )
        print("  3. Send notifications to ALL registered users in the database")
        print("  4. Provide detailed feedback about the process")
        return

    # Setup daemon mode if requested
    if args.daemon:
        # If we're already the spawned daemon child, continue running normally.
        if os.environ.get("SUPERSET_DAEMON_CHILD") == "1":
            # Child: proceed to normal initialization below
            pass
        else:
            # Parent: spawn a detached daemon child and exit
            spawn_daemon_process()

    # Setup logging
    logger = setup_logging(daemon_mode=args.daemon)

    # bot_scheduler = BotScheduler(daemon_mode=args.daemon)

    # if args.run_once:
    #     logger.info("Running run-once command with smart notifications")
    #     # Use the new function that only sends to users if new posts are found
    #     return run_once_and_notify_if_new_posts(daemon_mode=args.daemon)

    # bot_scheduler.start_bot_and_scheduler()

    bot_server = BotServer(daemon_mode=args.daemon)
    bot_server.start_bot_and_scheduler()


if __name__ == "__main__":
    main()
