"""
SuperSet Telegram Notification Bot

This bot scrapes job postings from the SuperSet portal, saves them to database,
enhances their formatting, and sends them to a Telegram channel.

Modules:
- webscraping: Handles web scraping with exact duplicate detection using MongoDB
- formatting: Enhances formatting of posts already saved in database
- telegram: Sends formatted messages from database to Telegram
"""

import logging
from update import run_update
from telegram_handeller import TelegramBot
from config import set_daemon_mode, safe_print
import sys


def main(daemon_mode=False):
    """Main function to orchestrate the complete workflow"""
    logger = logging.getLogger(__name__)
    logger.info("Starting SuperSet Telegram Notification Bot")

    # Set global daemon mode
    set_daemon_mode(daemon_mode)

    safe_print("Starting SuperSet Telegram Notification Bot...")
    safe_print("=" * 50)

    # Web Scraping (this now returns per-step status)
    update_result = run_update()

    # Telegram Sending
    safe_print("Sending formatted content to Telegram...")
    safe_print("-" * 30)
    logger.info("Sending formatted content to Telegram")
    telegram_bot = TelegramBot()

    try:
        telegram_result = telegram_bot.run()
        if telegram_result:
            success_msg = "Telegram sending completed successfully!"
            safe_print(success_msg)
            logger.info(success_msg)
            telegram_success = True
        else:
            error_msg = "Telegram sending failed!"
            safe_print(error_msg)
            logger.error(error_msg)
            telegram_success = False

    except Exception as e:
        error_msg = f"Telegram error: {e}"
        safe_print(error_msg)
        logger.error(error_msg, exc_info=True)
    telegram_success = False

    # Final Summary
    safe_print("\n" + "=" * 50)
    safe_print("PROCESS SUMMARY")
    safe_print("=" * 50)
    # We consider three high-level steps: notices, jobs, placements (from run_update)
    total_steps = 3

    # Compute completed sub-steps from update_result
    notices_done = (
        bool(update_result.get("notices")) if isinstance(update_result, dict) else False
    )
    jobs_done = (
        bool(update_result.get("jobs")) if isinstance(update_result, dict) else False
    )
    placements_done = (
        bool(update_result.get("placements"))
        if isinstance(update_result, dict)
        else False
    )

    success_count = sum(
        [1 if notices_done else 0, 1 if jobs_done else 0, 1 if placements_done else 0]
    )
    # Add telegram step as a separate final step
    total_steps += 1
    success_count += 1 if telegram_success else 0

    safe_print(f"Completed steps: {success_count}/{total_steps}")
    logger.info(f"Process completed: {success_count}/{total_steps} steps successful")

    if success_count == total_steps:
        final_msg = "All steps completed successfully!"
        safe_print(final_msg)
        logger.info(final_msg)
        return 0

    elif success_count > 0:
        final_msg = "Process completed with some issues."
        safe_print(final_msg)
        logger.warning(final_msg)
        return 1

    else:
        final_msg = "Process failed completely."
        safe_print(final_msg)
        logger.error(final_msg)
        return 2


def run_telegram_only(daemon_mode=False):
    """Run only the Telegram module"""
    logger = logging.getLogger(__name__)
    logger.info("Running Telegram sending only")

    if not daemon_mode:
        print("Running Telegram sending only...")

    telegram_bot = TelegramBot()
    result = telegram_bot.run()

    logger.info(f"Telegram sending only completed with result: {result}")
    return result


if __name__ == "__main__":
    main()
