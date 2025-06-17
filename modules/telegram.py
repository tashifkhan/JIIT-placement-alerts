import dotenv
import os
import re
import time
import requests
from .database import MongoDBManager

dotenv.load_dotenv()


class TelegramBot:
    def __init__(self):
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
        self.db_manager = MongoDBManager()

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(project_root, "output")

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        self.markdown_file = os.path.join(output_dir, "formatted_job_posts.md")

    def test_connection(self):
        """Test if Telegram bot is configured correctly"""
        try:
            if not self.TELEGRAM_BOT_TOKEN:
                print("TELEGRAM_BOT_TOKEN not set in .env file")
                return False

            if not self.TELEGRAM_CHAT_ID:
                print("TELEGRAM_CHAT_ID not set in .env file")
                return False

            return True

        except Exception as e:
            print(f"Error testing Telegram connection: {e}")
            return False

    def send_message(self, message, parse_mode="MarkdownV2"):
        """Send a single message to Telegram"""
        try:
            if not self.TELEGRAM_BOT_TOKEN or not self.TELEGRAM_CHAT_ID:
                print("Error: Telegram bot token or chat ID not configured")
                return False

            url = f"https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendMessage"

            # Convert and escape the message for Telegram
            if parse_mode == "MarkdownV2":
                formatted_message = self.convert_markdown_to_telegram(message)
            else:
                formatted_message = message

            payload = {
                "chat_id": self.TELEGRAM_CHAT_ID,
                "text": formatted_message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }

            response = requests.post(url, json=payload)

            if response.status_code == 200:
                print(
                    f"Message sent successfully (length: {len(formatted_message)} chars)"
                )
                return True
            else:
                print(f"Failed to send message. Status code: {response.status_code}")
                print(f"Response: {response.text}")
                # Try fallback with plain text if MarkdownV2 fails
                if parse_mode == "MarkdownV2":
                    print("Retrying with plain text...")
                    return self.send_message(message, parse_mode=None)
                return False

        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            # Try fallback with plain text
            if parse_mode == "MarkdownV2":
                print("Retrying with plain text...")
                return self.send_message(message, parse_mode=None)
            return False

    def send_message_html(self, message):
        """Send message using HTML formatting (more reliable than Markdown)"""
        try:
            if not self.TELEGRAM_BOT_TOKEN or not self.TELEGRAM_CHAT_ID:
                print("Error: Telegram bot token or chat ID not configured")
                return False

            url = f"https://api.telegram.org/bot{self.TELEGRAM_BOT_TOKEN}/sendMessage"

            html_message = self.convert_markdown_to_html(message)

            payload = {
                "chat_id": self.TELEGRAM_CHAT_ID,
                "text": html_message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }

            response = requests.post(url, json=payload)

            if response.status_code == 200:
                print(
                    f"HTML message sent successfully (length: {len(html_message)} chars)"
                )
                return True
            else:
                print(
                    f"Failed to send HTML message. Status code: {response.status_code}"
                )
                print(f"Response: {response.text}")

                payload["parse_mode"] = None
                payload["text"] = message
                response = requests.post(url, json=payload)
                return response.status_code == 200

        except Exception as e:
            print(f"Error sending HTML Telegram message: {e}")
            return False

    def send_new_posts_from_db(self):
        """Send only new posts from MongoDB that haven't been sent to Telegram yet"""
        try:
            # Get unsent posts from database
            unsent_posts = self.db_manager.get_unsent_posts()

            if not unsent_posts:
                print("No new posts to send to Telegram")
                return True

            print(f"Found {len(unsent_posts)} new posts to send to Telegram")

            successful_sends = 0
            failed_sends = 0

            for i, post in enumerate(unsent_posts, 1):
                post_content = post.get("content", "")
                post_title = post.get("title", "No Title")

                if not post_content.strip():
                    continue

                print(f"Sending post {i}/{len(unsent_posts)}: {post_title[:50]}...")

                # Send the post
                success = False
                if len(post_content) > 4000:
                    chunks = self.split_long_message(post_content)
                    chunk_success = True
                    for j, chunk in enumerate(chunks, 1):
                        print(f"  Sending chunk {j}/{len(chunks)}...")
                        if not self.send_message_html(chunk):
                            chunk_success = False
                            failed_sends += 1
                        time.sleep(1)
                    success = chunk_success
                else:
                    success = self.send_message_html(post_content)

                if success:
                    successful_sends += 1
                    # Mark as sent in database
                    if self.db_manager.mark_as_sent(post["_id"]):
                        print(f"✅ Post marked as sent in database")
                    else:
                        print(f"⚠️  Failed to mark post as sent in database")
                else:
                    failed_sends += 1
                    print(f"❌ Failed to send post: {post_title[:50]}...")

                time.sleep(2)  # Rate limiting

            print(
                f"Telegram sending completed: {successful_sends} successful, {failed_sends} failed"
            )
            return successful_sends > 0

        except Exception as e:
            print(f"Error sending posts from database: {e}")
            return False

    def send_markdown_file(self):
        """Legacy method - now redirects to database-based sending"""
        print("Using database-based post sending instead of markdown file...")
        return self.send_new_posts_from_db()

    def split_long_message(self, message, max_length=4000):
        """Split a long message into smaller chunks while preserving markdown formatting"""
        if len(message) <= max_length:
            return [message]

        chunks = []
        lines = message.split("\n")
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) + 1 > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = line + "\n"
                else:
                    words = line.split(" ")
                    current_line = ""
                    for word in words:
                        if len(current_line) + len(word) + 1 > max_length:
                            if current_line:
                                chunks.append(current_line.strip())
                                current_line = word + " "
                            else:
                                chunks.append(word[:max_length])
                                current_line = ""
                        else:
                            current_line += word + " "
                    if current_line:
                        current_chunk = current_line + "\n"
            else:
                current_chunk += line + "\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

    def escape_markdown_v2(self, text):
        """Escape special characters for Telegram MarkdownV2"""
        # Characters that need to be escaped in MarkdownV2
        escape_chars = [
            "_",
            "*",
            "[",
            "]",
            "(",
            ")",
            "~",
            "`",
            ">",
            "#",
            "+",
            "-",
            "=",
            "|",
            "{",
            "}",
            ".",
            "!",
        ]

        for char in escape_chars:
            text = text.replace(char, f"\\{char}")

        return text

    def convert_markdown_to_telegram(self, text):
        """Convert standard markdown to Telegram-compatible MarkdownV2"""
        # First, handle bold text
        text = text.replace("**", "*")

        # Convert ## headers to bold
        text = re.sub(r"^##\s+(.*?)$", r"*\1*", text, flags=re.MULTILINE)
        # Convert ### headers to bold
        text = re.sub(r"^###\s+(.*?)$", r"*\1*", text, flags=re.MULTILINE)

        # Handle blockquotes (> text) - convert to italic
        text = re.sub(r"^>\s+(.*?)$", r"_\1_", text, flags=re.MULTILINE)

        # Split text into parts to avoid escaping content inside markdown
        lines = text.split("\n")
        processed_lines = []

        for line in lines:
            if line.strip():
                if "*" in line or "_" in line or "`" in line:
                    processed_lines.append(line)
                else:
                    processed_lines.append(self.escape_markdown_v2(line))
            else:
                processed_lines.append(line)

        return "\n".join(processed_lines)

    def convert_markdown_to_html(self, text):
        """Convert markdown to HTML for Telegram"""
        # Convert headers to bold
        text = re.sub(r"^##\s+(.*?)$", r"<b>\1</b>", text, flags=re.MULTILINE)
        text = re.sub(r"^###\s+(.*?)$", r"<b>\1</b>", text, flags=re.MULTILINE)

        # Convert bold text
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)

        # Convert italic text
        text = re.sub(r"_(.*?)_", r"<i>\1</i>", text)

        # Convert blockquotes
        text = re.sub(r"^>\s+(.*?)$", r"<i>\1</i>", text, flags=re.MULTILINE)

        # Convert code blocks (though Telegram has limited support)
        text = re.sub(r"`(.*?)`", r"<code>\1</code>", text)

        return text

    def get_database_stats(self):
        """Get and display database statistics"""
        try:
            stats = self.db_manager.get_posts_stats()
            print("\n📊 Database Statistics:")
            print(f"   Total posts: {stats.get('total_posts', 0)}")
            print(f"   Sent to Telegram: {stats.get('sent_to_telegram', 0)}")
            print(f"   Pending to send: {stats.get('pending_to_send', 0)}")

            post_types = stats.get("post_types", [])
            if post_types:
                print("\n   Post types distribution:")
                for pt in post_types:
                    print(f"     - {pt['_id']}: {pt['count']}")

            return stats
        except Exception as e:
            print(f"Error getting database stats: {e}")
            return {}

    def run(self):
        """Main method to run Telegram functionality"""
        print("SuperSet Telegram Bot - Send Mode")
        print("1. Testing Telegram connection...")

        if not self.test_connection():
            print(
                "Please configure your Telegram bot token and chat ID in the .env file"
            )
            print("To get a bot token: Message @BotFather on Telegram")
            print("To get your chat ID: Message @userinfobot on Telegram")
            return False

        # Show database stats
        self.get_database_stats()

        print("2. Sending new job posts to Telegram...")
        result = self.send_new_posts_from_db()

        if result:
            print("Telegram sending completed successfully!")
        else:
            print("Telegram sending failed!")

        return result
