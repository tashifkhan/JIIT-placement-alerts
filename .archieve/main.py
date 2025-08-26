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
from modules.config import set_daemon_mode, safe_print
import sys


def main(daemon_mode=False):
    """Main function to orchestrate the complete workflow"""
    logger = logging.getLogger(__name__)
    logger.info("Starting SuperSet Telegram Notification Bot")

    # Set global daemon mode
    set_daemon_mode(daemon_mode)

    safe_print("Starting SuperSet Telegram Notification Bot...")
    safe_print("=" * 50)

    scraper = WebScraper()
    formatter = TextFormatter()
    telegram_bot = TelegramBot()

    success_count = 0
    total_steps = 3

    # Step 1: Web Scraping
    safe_print("\nStep 1/3: Starting incremental web scraping...")
    safe_print("-" * 30)
    logger.info("Step 1/3: Starting incremental web scraping")

    try:
        if scraper.scrape():
            success_msg = "Web scraping completed successfully!"
            safe_print(success_msg)
            logger.info(success_msg)
            success_count += 1
        else:
            error_msg = "Web scraping failed!"
            safe_print(error_msg)
            logger.error(error_msg)

    except Exception as e:
        error_msg = f"Web scraping error: {e}"
        safe_print(error_msg)
        logger.error(error_msg, exc_info=True)

    # Step 2: Formatting
    safe_print("\nStep 2/3: Enhancing post formatting...")
    safe_print("-" * 30)
    logger.info("Step 2/3: Enhancing post formatting")

    try:
        format_result = formatter.format_content()
        if isinstance(format_result, dict) and format_result.get("success"):
            enhanced_posts = format_result.get("new_posts", 0)
            total_processed = format_result.get("total_processed", 0)
            success_msg = f"Content formatting enhancement completed! Posts enhanced: {enhanced_posts}, Total processed: {total_processed}"
            safe_print(f"Content formatting enhancement completed!")
            safe_print(
                f"   Posts enhanced: {enhanced_posts}, Total processed: {total_processed}"
            )
            logger.info(success_msg)
            success_count += 1
        else:
            error_msg = "Content formatting failed!"
            if isinstance(format_result, dict):
                error_detail = format_result.get("error", "Unknown error")
                error_msg += f" - Error: {error_detail}"
                safe_print("Content formatting failed!")
                safe_print(f"   Error: {error_detail}")
            else:
                safe_print(error_msg)
            logger.error(error_msg)

    except Exception as e:
        error_msg = f"Formatting error: {e}"
        safe_print(error_msg)
        logger.error(error_msg, exc_info=True)

    # Step 3: Telegram Sending
    safe_print("\nStep 3/3: Sending formatted content to Telegram...")
    safe_print("-" * 30)
    logger.info("Step 3/3: Sending formatted content to Telegram")

    try:
        if telegram_bot.run():
            success_msg = "Telegram sending completed successfully!"
            safe_print(success_msg)
            logger.info(success_msg)
            success_count += 1
        else:
            error_msg = "Telegram sending failed!"
            safe_print(error_msg)
            logger.error(error_msg)

    except Exception as e:
        error_msg = f"Telegram error: {e}"
        safe_print(error_msg)
        logger.error(error_msg, exc_info=True)

    # Final Summary
    safe_print("\n" + "=" * 50)
    safe_print("PROCESS SUMMARY")
    safe_print("=" * 50)
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


def run_scraping_only(daemon_mode=False):
    """Run only the web scraping module"""
    logger = logging.getLogger(__name__)
    logger.info("Running web scraping only")
    if not daemon_mode:
        print("Running web scraping only...")
    scraper = WebScraper()
    result = scraper.scrape()
    logger.info(f"Web scraping only completed with result: {result}")
    return result


def run_formatting_only(daemon_mode=False):
    """Run only the formatting module"""
    logger = logging.getLogger(__name__)
    logger.info("Running formatting only")
    if not daemon_mode:
        print("Running formatting only...")
    formatter = TextFormatter()
    result = formatter.format_content()
    logger.info(f"Formatting only completed with result: {result}")
    return result


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


def run_once_and_notify_if_new_posts(daemon_mode=False):
    """
    Run the complete workflow once and send notifications to all users only if new posts are found.
    This function provides explicit feedback about whether new posts were discovered and sent.
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting run-once workflow with conditional user notifications")

    if not daemon_mode:
        print("SuperSet Bot - Run Once with Smart Notifications")
        print("=" * 55)
        print("Will only send notifications if NEW posts are discovered!")
        print()

    scraper = WebScraper()
    formatter = TextFormatter()
    telegram_bot = TelegramBot()

    # Step 1: Check current unsent posts count (before scraping)
    if not daemon_mode:
        print("📊 Checking current status...")
    try:
        initial_unsent_count = len(telegram_bot.db_manager.get_unsent_posts())
        if not daemon_mode:
            print(f"   Unsent posts before scraping: {initial_unsent_count}")
    except Exception as e:
        logger.error(f"Error checking initial unsent posts: {e}")
        initial_unsent_count = 0

    success_count = 0
    total_steps = 3

    # Step 2: Web Scraping
    if not daemon_mode:
        print("\nStep 1/3: Scraping for new job posts...")
        print("-" * 40)
    logger.info("Step 1/3: Starting web scraping")

    scraping_success = False
    try:
        if scraper.scrape():
            success_msg = "✅ Web scraping completed successfully!"
            if not daemon_mode:
                print(success_msg)
            logger.info(success_msg)
            success_count += 1
            scraping_success = True
        else:
            error_msg = "❌ Web scraping failed!"
            if not daemon_mode:
                print(error_msg)
            logger.error(error_msg)

    except Exception as e:
        error_msg = f"❌ Web scraping error: {e}"
        if not daemon_mode:
            print(error_msg)
        logger.error(error_msg, exc_info=True)

    # Step 3: Check if new posts were found
    new_posts_found = False
    if scraping_success:
        try:
            current_unsent_count = len(telegram_bot.db_manager.get_unsent_posts())
            new_posts_count = current_unsent_count - initial_unsent_count
            if not daemon_mode:
                print(f"\n📈 Scraping Results:")
                print(f"   Unsent posts after scraping: {current_unsent_count}")
                print(f"   New posts discovered: {new_posts_count}")

            if new_posts_count > 0:
                new_posts_found = True
                if not daemon_mode:
                    print(
                        f"🎉 Found {new_posts_count} new posts! Will proceed with formatting and notifications."
                    )
                logger.info(f"Found {new_posts_count} new posts during scraping")
            else:
                if not daemon_mode:
                    print(
                        "ℹ️  No new posts found. Skipping formatting and notifications."
                    )
                logger.info("No new posts found during scraping")

        except Exception as e:
            logger.error(f"Error checking post counts: {e}")
            # If we can't determine, proceed with the rest of the workflow
            new_posts_found = True

    # Step 4: Formatting (only if new posts found)
    if new_posts_found:
        if not daemon_mode:
            print("\nStep 2/3: Enhancing post formatting...")
            print("-" * 40)
        logger.info("Step 2/3: Starting post formatting")

        try:
            format_result = formatter.format_content()
            if isinstance(format_result, dict) and format_result.get("success"):
                enhanced_posts = format_result.get("new_posts", 0)
                total_processed = format_result.get("total_processed", 0)
                success_msg = f"✅ Content formatting completed! Posts enhanced: {enhanced_posts}, Total processed: {total_processed}"
                if not daemon_mode:
                    print(f"✅ Content formatting enhancement completed!")
                    print(
                        f"   Posts enhanced: {enhanced_posts}, Total processed: {total_processed}"
                    )
                logger.info(success_msg)
                success_count += 1
            else:
                error_msg = "❌ Content formatting failed!"
                if isinstance(format_result, dict):
                    error_detail = format_result.get("error", "Unknown error")
                    error_msg += f" - Error: {error_detail}"
                    if not daemon_mode:
                        print("❌ Content formatting failed!")
                        print(f"   Error: {error_detail}")
                else:
                    if not daemon_mode:
                        print(error_msg)
                logger.error(error_msg)

        except Exception as e:
            error_msg = f"❌ Formatting error: {e}"
            if not daemon_mode:
                print(error_msg)
            logger.error(error_msg, exc_info=True)

        # Step 5: Send to all registered users (only if new posts found)
        if not daemon_mode:
            print("\nStep 3/3: Sending notifications to all registered users...")
            print("-" * 55)
        logger.info("Step 3/3: Sending notifications to registered users")

        try:
            # Get user count first
            users = telegram_bot.db_manager.get_all_users()
            user_count = len(users) if users else 0

            if user_count == 0:
                if not daemon_mode:
                    print("⚠️  No users registered for notifications!")
                logger.warning("No registered users found")
            else:
                if not daemon_mode:
                    print(
                        f"📢 Sending notifications to {user_count} registered users..."
                    )

                if telegram_bot.run():
                    success_msg = (
                        f"✅ Notifications sent successfully to all {user_count} users!"
                    )
                    if not daemon_mode:
                        print(success_msg)
                    logger.info(success_msg)
                    success_count += 1
                else:
                    error_msg = "❌ Failed to send notifications!"
                    if not daemon_mode:
                        print(error_msg)
                    logger.error(error_msg)

        except Exception as e:
            error_msg = f"❌ Notification error: {e}"
            if not daemon_mode:
                print(error_msg)
            logger.error(error_msg, exc_info=True)
    else:
        if not daemon_mode:
            print("\n⏭️  Skipping formatting and notifications (no new posts found)")
        logger.info("Skipped formatting and notifications - no new posts")
        success_count += 1  # Consider this a success since no action was needed

    # Final Summary
    if not daemon_mode:
        print("\n" + "=" * 55)
        print("RUN-ONCE SUMMARY")
        print("=" * 55)

    if new_posts_found:
        if not daemon_mode:
            print(f"📊 Completed steps: {success_count}/{total_steps}")
        logger.info(
            f"Run-once process completed: {success_count}/{total_steps} steps successful"
        )

        if success_count == total_steps:
            final_msg = (
                "🎉 All steps completed successfully! New posts sent to all users."
            )
            if not daemon_mode:
                print(final_msg)
            logger.info(final_msg)
            return 0
        elif success_count > 0:
            final_msg = "⚠️  Process completed with some issues."
            if not daemon_mode:
                print(final_msg)
            logger.warning(final_msg)
            return 1
        else:
            final_msg = "❌ Process failed completely."
            if not daemon_mode:
                print(final_msg)
            logger.error(final_msg)
            return 2
    else:
        final_msg = "✅ Run completed successfully - No new posts to send."
        if not daemon_mode:
            print(final_msg)
        logger.info(final_msg)
        return 0


if __name__ == "__main__":
    main()
