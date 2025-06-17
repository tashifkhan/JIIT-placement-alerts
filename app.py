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
"""

import asyncio
import schedule
import time
import threading
from datetime import datetime
import pytz
from modules.telegram import TelegramBot
from main import main as run_main_process


class BotScheduler:
    def __init__(self):
        self.telegram_bot = TelegramBot()
        self.ist = pytz.timezone("Asia/Kolkata")
        self.running = True

    def scheduled_job(self):
        """Run the main scraping and notification process"""
        try:
            current_time = datetime.now(self.ist).strftime("%Y-%m-%d %H:%M:%S IST")
            print(f"\n{'='*60}")
            print(f"SCHEDULED JOB STARTED AT {current_time}")
            print(f"{'='*60}")

            # Run the main process (scraping + formatting + sending)
            result = run_main_process()

            if result == 0:
                print(f"✅ Scheduled job completed successfully at {current_time}")
            else:
                print(f"❌ Scheduled job completed with issues at {current_time}")

        except Exception as e:
            print(f"❌ Error in scheduled job: {e}")

    def setup_schedule(self):
        """Setup the scheduled jobs for 3 times a day"""

        schedule.every().day.at("12:00").do(self.scheduled_job)

        schedule.every().day.at("00:00").do(self.scheduled_job)

        schedule.every().day.at("18:00").do(self.scheduled_job)

        print("📅 Scheduled jobs setup:")
        print("   - 12:00 PM IST (Noon)")
        print("   - 12:00 AM IST (Midnight)")
        print("   - 6:00 PM IST (Evening)")

    def run_scheduler(self):
        """Run the scheduler in a separate thread"""
        print("🕐 Starting job scheduler...")
        while self.running:
            schedule.run_pending()
            time.sleep(60)  #

    def start_bot_and_scheduler(self):
        """Start both the Telegram bot and the scheduler"""
        try:
            print("Starting SuperSet Telegram Bot Server...")

            # Setup scheduled jobs
            self.setup_schedule()

            # Start scheduler in a separate thread
            scheduler_thread = threading.Thread(target=self.run_scheduler, daemon=True)
            scheduler_thread.start()

            # Get current time in IST
            current_time = datetime.now(self.ist)
            print(
                f"🕐 Current time (IST): {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # Show user statistics
            self.telegram_bot.get_user_stats()

            print("\nStarting Telegram bot server...")
            print("Send /start to the bot to register for notifications!")

            # Start the bot server (this will block)
            self.telegram_bot.start_bot_server()

        except KeyboardInterrupt:
            print("\nShutting down bot server...")
            self.running = False
        except Exception as e:
            print(f"Error starting bot server: {e}")

    def run_once_now(self):
        """Run the job once immediately (for testing)"""
        print("Running job immediately for testing...")
        self.scheduled_job()


def main():
    """Main function"""
    import sys

    bot_scheduler = BotScheduler()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--run-once":
            bot_scheduler.run_once_now()
            return

        elif sys.argv[1] == "--help":
            print("SuperSet Telegram Bot Server")
            print("\nUsage:")
            print("  python app.py              - Start bot server with scheduler")
            print("  python app.py --run-once   - Run scraping job once immediately")
            print("  python app.py --help       - Show this help message")
            return

    bot_scheduler.start_bot_and_scheduler()


if __name__ == "__main__":
    main()
