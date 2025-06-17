"""
SuperSet Telegram Notification Bot

This bot scrapes job postings from the SuperSet portal, formats them,
and sends them to a Telegram channel.

Modules:
- webscraping: Handles web scraping using Selenium
- formatting: Formats the scraped content into readable markdown
- telegram: Sends formatted messages to Telegram
"""

from modules.webscraping import WebScraper
from modules.formatting import TextFormatter
from modules.telegram import TelegramBot
import sys


def main():
    """Main function to orchestrate the complete workflow"""
    print("Starting SuperSet Telegram Notification Bot...")
    print("=" * 50)

    scraper = WebScraper()
    formatter = TextFormatter()
    telegram_bot = TelegramBot()

    success_count = 0
    total_steps = 3

    print("\nStep 1/3: Starting web scraping...")
    print("-" * 30)

    try:
        if scraper.scrape():
            print("Web scraping completed successfully!")
            success_count += 1
        else:
            print("Web scraping failed!")

    except Exception as e:
        print(f"Web scraping error: {e}")

    print("\nStep 2/3: Formatting extracted content...")
    print("-" * 30)

    try:
        if formatter.format_content():
            print("Content formatting completed successfully!")
            success_count += 1
        else:
            print("Content formatting failed!")

    except Exception as e:
        print(f"Formatting error: {e}")

    print("\nStep 3/3: Sending formatted content to Telegram...")
    print("-" * 30)

    try:
        if telegram_bot.run():
            print("Telegram sending completed successfully!")
            success_count += 1
        else:
            print("Telegram sending failed!")

    except Exception as e:
        print(f"Telegram error: {e}")

    # Final Summary
    print("\n" + "=" * 50)
    print("PROCESS SUMMARY")
    print("=" * 50)
    print(f"Completed steps: {success_count}/{total_steps}")

    if success_count == total_steps:
        print("All steps completed successfully!")
        return 0

    elif success_count > 0:
        print("Process completed with some issues.")
        return 1

    else:
        print("Process failed completely.")
        return 2


def run_scraping_only():
    """Run only the web scraping module"""
    print("Running web scraping only...")
    scraper = WebScraper()
    return scraper.scrape()


def run_formatting_only():
    """Run only the formatting module"""
    print("Running formatting only...")
    formatter = TextFormatter()
    return formatter.format_content()


def run_telegram_only():
    """Run only the Telegram module"""
    print("Running Telegram sending only...")
    telegram_bot = TelegramBot()
    return telegram_bot.run()


if __name__ == "__main__":
    main()
