"""
SuperSet Telegram Notification Bot

This bot scrapes job postings from the SuperSet portal, saves them to database,
enhances their formatting, and sends them to a Telegram channel.

Key Features:
- Incremental scraping: Stops when encountering EXACT duplicate posts
- Exact matching: Only posts with 100% identical content are rejected
- Database-only storage: No file-based saving
- Precise duplicate detection: Even small content changes are treated as new posts
- Comprehensive logging for daemon mode support

Modules:
- webscraping: Handles web scraping with exact duplicate detection using MongoDB
- formatting: Enhances formatting of posts already saved in database
- telegram: Sends formatted messages from database to Telegram
"""

import logging
from modules.webscraping import WebScraper
from modules.formatting import TextFormatter
from modules.telegram import TelegramBot
import sys


def main():
    """Main function to orchestrate the complete workflow"""
    logger = logging.getLogger(__name__)
    logger.info("Starting SuperSet Telegram Notification Bot")

    print("Starting SuperSet Telegram Notification Bot...")
    print("=" * 50)

    scraper = WebScraper()
    formatter = TextFormatter()
    telegram_bot = TelegramBot()

    success_count = 0
    total_steps = 3

    # Step 1: Web Scraping
    print("\nStep 1/3: Starting incremental web scraping...")
    print("-" * 30)
    logger.info("Step 1/3: Starting incremental web scraping")

    try:
        if scraper.scrape():
            success_msg = "Web scraping completed successfully!"
            print(success_msg)
            logger.info(success_msg)
            success_count += 1
        else:
            error_msg = "Web scraping failed!"
            print(error_msg)
            logger.error(error_msg)

    except Exception as e:
        error_msg = f"Web scraping error: {e}"
        print(error_msg)
        logger.error(error_msg, exc_info=True)

    # Step 2: Formatting
    print("\nStep 2/3: Enhancing post formatting...")
    print("-" * 30)
    logger.info("Step 2/3: Enhancing post formatting")

    try:
        format_result = formatter.format_content()
        if isinstance(format_result, dict) and format_result.get("success"):
            enhanced_posts = format_result.get("new_posts", 0)
            total_processed = format_result.get("total_processed", 0)
            success_msg = f"Content formatting enhancement completed! Posts enhanced: {enhanced_posts}, Total processed: {total_processed}"
            print(f"Content formatting enhancement completed!")
            print(
                f"   Posts enhanced: {enhanced_posts}, Total processed: {total_processed}"
            )
            logger.info(success_msg)
            success_count += 1
        else:
            error_msg = "Content formatting failed!"
            if isinstance(format_result, dict):
                error_detail = format_result.get("error", "Unknown error")
                error_msg += f" - Error: {error_detail}"
                print("Content formatting failed!")
                print(f"   Error: {error_detail}")
            else:
                print(error_msg)
            logger.error(error_msg)

    except Exception as e:
        error_msg = f"Formatting error: {e}"
        print(error_msg)
        logger.error(error_msg, exc_info=True)

    # Step 3: Telegram Sending
    print("\nStep 3/3: Sending formatted content to Telegram...")
    print("-" * 30)
    logger.info("Step 3/3: Sending formatted content to Telegram")

    try:
        if telegram_bot.run():
            success_msg = "Telegram sending completed successfully!"
            print(success_msg)
            logger.info(success_msg)
            success_count += 1
        else:
            error_msg = "Telegram sending failed!"
            print(error_msg)
            logger.error(error_msg)

    except Exception as e:
        error_msg = f"Telegram error: {e}"
        print(error_msg)
        logger.error(error_msg, exc_info=True)

    # Final Summary
    print("\n" + "=" * 50)
    print("PROCESS SUMMARY")
    print("=" * 50)
    print(f"Completed steps: {success_count}/{total_steps}")

    logger.info(f"Process completed: {success_count}/{total_steps} steps successful")

    if success_count == total_steps:
        final_msg = "All steps completed successfully!"
        print(final_msg)
        logger.info(final_msg)
        return 0
    elif success_count > 0:
        final_msg = "Process completed with some issues."
        print(final_msg)
        logger.warning(final_msg)
        return 1
    else:
        final_msg = "Process failed completely."
        print(final_msg)
        logger.error(final_msg)
        return 2


def run_scraping_only():
    """Run only the web scraping module"""
    logger = logging.getLogger(__name__)
    logger.info("Running web scraping only")
    print("Running web scraping only...")
    scraper = WebScraper()
    result = scraper.scrape()
    logger.info(f"Web scraping only completed with result: {result}")
    return result


def run_formatting_only():
    """Run only the formatting module"""
    logger = logging.getLogger(__name__)
    logger.info("Running formatting only")
    print("Running formatting only...")
    formatter = TextFormatter()
    result = formatter.format_content()
    logger.info(f"Formatting only completed with result: {result}")
    return result


def run_telegram_only():
    """Run only the Telegram module"""
    logger = logging.getLogger(__name__)
    logger.info("Running Telegram sending only")
    print("Running Telegram sending only...")
    telegram_bot = TelegramBot()
    result = telegram_bot.run()
    logger.info(f"Telegram sending only completed with result: {result}")
    return result


if __name__ == "__main__":
    main()
