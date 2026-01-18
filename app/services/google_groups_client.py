"""
Google Groups Client

Reusable IMAP client for fetching emails from Google Groups.
Decoupled from placement-specific logic for use by multiple services.
"""

import os
import re
import imaplib
import email
import logging
from email.header import decode_header
from typing import List, Dict, Optional
from datetime import timezone, timedelta
from core import get_settings


class GoogleGroupsClient:
    """
    IMAP client for fetching emails from Google Groups.

    Handles:
    - IMAP connection management
    - Fetching unread emails
    - Marking emails as read
    - Extracting forwarded message metadata
    """

    def __init__(
        self,
        email_address: Optional[str] = None,
        app_password: Optional[str] = None,
        imap_server: str = "imap.gmail.com",
    ):
        """
        Initialize Google Groups client.

        Args:
            email_address: Email address to fetch from (defaults to env PLACEMENT_EMAIL)
            app_password: App password for email (defaults to env PLACEMENT_APP_PASSWORD)
            imap_server: IMAP server address
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.email_address = email_address or get_settings().placement_email
        self.app_password = app_password or get_settings().placement_app_password
        self.imap_server = imap_server
        self._connection: Optional[imaplib.IMAP4_SSL] = None

        self.logger.info("GoogleGroupsClient initialized")

    def connect(self) -> imaplib.IMAP4_SSL:
        """
        Establish IMAP connection.

        Returns:
            IMAP connection object

        Raises:
            ValueError: If credentials are not configured
            ConnectionError: If connection fails
        """
        if not self.email_address or not self.app_password:
            raise ValueError(
                "Email credentials not properly configured. "
                "Please check PLCAMENT_EMAIL and PLCAMENT_APP_PASSWORD environment variables."
            )

        try:
            self._connection = imaplib.IMAP4_SSL(self.imap_server)
            self._connection.login(self.email_address, self.app_password)
            self.logger.info(f"Connected to {self.imap_server}")
            return self._connection
        except imaplib.IMAP4.error as e:
            raise ConnectionError(f"IMAP connection failed: {e}")

    def disconnect(self) -> None:
        """Close IMAP connection."""
        if self._connection:
            try:
                self._connection.logout()
                self.logger.info("Disconnected from IMAP server")
            except Exception as e:
                self.logger.warning(f"Error during disconnect: {e}")
            finally:
                self._connection = None

    def get_unread_message_ids(self, folder: str = "inbox") -> List[str]:
        """
        Get list of unread email IDs.

        Args:
            folder: IMAP folder to check

        Returns:
            List of email IDs as strings
        """
        connection = self.connect()
        try:
            connection.select(folder)
            status, messages = connection.search(None, "UNSEEN")
            email_ids = messages[0].split()
            return [
                e_id.decode() if isinstance(e_id, bytes) else str(e_id)
                for e_id in email_ids
            ]
        finally:
            self.disconnect()

    def fetch_email(
        self, email_id: str, folder: str = "inbox", mark_as_read: bool = False
    ) -> Optional[Dict[str, str]]:
        """
        Fetch a specific email by ID.

        Args:
            email_id: ID of email to fetch
            folder: IMAP folder
            mark_as_read: Whether to mark as read

        Returns:
            Dict with email data (subject, sender, body, time_sent) or None
        """
        connection = self.connect()
        try:
            connection.select(folder)

            # Fetch content
            email_data = self._parse_email(connection, email_id.encode())

            if email_data and mark_as_read:
                connection.store(email_id.encode(), "+FLAGS", "\\Seen")

            return email_data
        except Exception as e:
            self.logger.error(f"Error fetching email {email_id}: {e}")
            return None
        finally:
            self.disconnect()

    def fetch_unread_emails(
        self,
        folder: str = "inbox",
        mark_as_read: bool = True,
    ) -> List[Dict[str, str]]:
        """
        Fetch unread emails from specified folder.

        Note: This method fetches all unread emails at once.
        For safer processing, use get_unread_message_ids() and fetch_email() iteratively.

        Args:
            folder: IMAP folder to fetch from
            mark_as_read: Whether to mark fetched emails as read

        Returns:
            List of email dicts with keys: subject, sender, body, email_id
        """
        email_ids = self.get_unread_message_ids(folder)

        emails = []
        for e_id in email_ids:
            email_data = self.fetch_email(e_id, folder, mark_as_read)
            if email_data:
                emails.append(email_data)

        self.logger.info(f"Fetched {len(emails)} unread emails from {folder}")
        return emails

    def _parse_email(
        self,
        connection: imaplib.IMAP4_SSL,
        email_id: bytes,
    ) -> Optional[Dict[str, str]]:
        """
        Parse a single email message.

        Args:
            connection: IMAP connection
            email_id: Email ID to fetch

        Returns:
            Dict with email data or None if parsing fails
        """
        try:
            res, msg_data = connection.fetch(email_id, "(RFC822)")

            if not msg_data or not msg_data[0] or len(msg_data[0]) <= 1:
                return None

            raw_msg = msg_data[0][1]
            if not isinstance(raw_msg, bytes):
                return None

            msg = email.message_from_bytes(raw_msg)

            # Decode subject
            subject, encoding = decode_header(msg["Subject"])[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8", errors="ignore")

            sender = msg.get("From", "")

            # Extract body
            body = self._extract_body(msg)

            # Extract time: first try forwarded date from body, then fall back to email Date header
            time_sent = self.extract_forwarded_date(body)
            if not time_sent:
                # Not a forwarded email, get actual email Date header
                email_date = msg.get("Date", "")
                if email_date:
                    time_sent = self._format_email_date(email_date)

            return {
                "subject": subject or "",
                "sender": sender,
                "body": body,
                "email_id": (
                    email_id.decode() if isinstance(email_id, bytes) else str(email_id)
                ),
                "time_sent": time_sent,
            }

        except Exception as e:
            self.logger.error(f"Error parsing email {email_id}: {e}")
            return None

    def _extract_body(self, msg: email.message.Message) -> str:
        """Extract body content from email message."""
        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type in ["text/plain", "text/html"]:
                    try:
                        payload = part.get_payload(decode=True)
                        if isinstance(payload, bytes):
                            body = payload.decode("utf-8", errors="ignore")
                            # Prefer text/plain if available
                            if content_type == "text/plain":
                                break
                    except Exception:
                        continue
        else:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                body = payload.decode("utf-8", errors="ignore")

        return body

    @staticmethod
    def extract_forwarded_date(text: str) -> Optional[str]:
        """
        Extract the date from forwarded message headers and convert to ISO format.

        Looks for patterns like:
        - "Date: Thu, 21 Aug, 2025, 4:51 pm"
        - "Date: Wed, 20 Aug 2025 at 13:20"

        Returns:
            ISO datetime string (e.g., "2025-08-21T16:51:00+05:30") or None if not found
        """
        if not text:
            print("[DEBUG extract_forwarded_date] Empty text")
            return None

        # Try multiple patterns for date extraction
        # Pattern 1: Date: followed by content until Subject:, newline, or end
        date_patterns = [
            r"Date:\s*([^\n\r]+?)(?:\s*\n|\s*\r|\s*Subject:|$)",  # Standard newline
            r"Date:\s*(.+?)(?:<br>|Subject:|To:|$)",  # HTML br or Subject/To
            r"Date:\s*([A-Za-z]{3},?\s+\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}(?:,?\s+(?:at\s+)?\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?)",  # Explicit date format
        ]

        date_str = None
        for i, pattern in enumerate(date_patterns):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip().rstrip(",")
                print(
                    f"[DEBUG extract_forwarded_date] Pattern {i+1} matched: {repr(date_str)}"
                )
                break

        if not date_str:
            # Show a snippet of the text to debug
            snippet = text[:500].replace("\n", "\\n").replace("\r", "\\r")
            print(
                f"[DEBUG extract_forwarded_date] No pattern matched. Text snippet: {snippet}"
            )
            return None

        # Clean up the date string
        date_str = re.sub(r",\s*,", ",", date_str)
        # Remove any HTML tags
        date_str = re.sub(r"<[^>]+>", "", date_str).strip()
        # Remove trailing Subject: or To: that might have been captured
        date_str = re.sub(
            r"\s*(Subject|To)\s*:.*$", "", date_str, flags=re.IGNORECASE
        ).strip()

        if not date_str:
            return None

        try:
            from dateutil import parser as date_parser
            import unicodedata

            # Normalize Unicode whitespace (including \u202f narrow no-break space)
            # Replace all Unicode whitespace with regular space
            date_str = "".join(
                " " if unicodedata.category(c) in ("Zs", "Cc") else c for c in date_str
            )
            date_str = " ".join(date_str.split())  # Collapse multiple spaces
            print(
                f"[DEBUG extract_forwarded_date] Normalized date_str: {repr(date_str)}"
            )

            # Parse the date string
            parsed_date = date_parser.parse(date_str, fuzzy=True)

            # Define IST timezone (UTC+5:30)
            ist = timezone(timedelta(hours=5, minutes=30))

            # If no timezone, assume IST; otherwise convert
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=ist)
            else:
                parsed_date = parsed_date.astimezone(ist)

            # Return ISO format datetime string
            return parsed_date.isoformat()

        except Exception as e:
            print(f"[DEBUG extract_forwarded_date] Exception: {e}")
            return None

        return None

    @staticmethod
    def _format_email_date(date_str: str) -> Optional[str]:
        """
        Format the email Date header to ISO format.

        Args:
            date_str: The Date header value from the email

        Returns:
            ISO datetime string or None if parsing fails
        """
        if not date_str:
            return None

        try:
            from dateutil import parser as date_parser

            # Parse the email date
            parsed_date = date_parser.parse(date_str, fuzzy=True)

            # Define IST timezone (UTC+5:30)
            ist = timezone(timedelta(hours=5, minutes=30))

            # Convert to IST
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=ist)
            else:
                parsed_date = parsed_date.astimezone(ist)

            # Return ISO format datetime string
            return parsed_date.isoformat()

        except Exception:
            return None

    @staticmethod
    def extract_forwarded_sender(text: str) -> Optional[str]:
        """
        Extract the original sender from forwarded message headers.

        Looks for patterns like:
        - "From: Vinod Kumar <vinod.jptnp@gmail.com>"
        - "From: vinod.jptnp@gmail.com"

        This is used to get the actual sender when an email is forwarded.

        Returns:
            The original sender email/name or None if not a forwarded message
        """
        if not text:
            return None

        # Check if this is a forwarded message
        forwarded_patterns = [
            r"-+\s*Forwarded message\s*-+",
            r"Begin forwarded message",
            r"Fwd:",
            r"FW:",
        ]

        is_forwarded = any(
            re.search(pat, text, re.IGNORECASE) for pat in forwarded_patterns
        )

        if not is_forwarded:
            return None

        # Pattern to match "From: Name <email>" or "From: email" in forwarded headers
        from_pattern = r"From:\s*(.+?)(?:\n|$)"
        match = re.search(from_pattern, text, re.IGNORECASE)

        if match:
            sender_str = match.group(1).strip()
            sender_str = sender_str.rstrip(",")
            return sender_str

        return None

    def mark_as_read(self, email_id: str) -> bool:
        """
        Mark a specific email as read.

        Args:
            email_id: Email ID to mark as read

        Returns:
            True if successful
        """
        connection = self.connect()
        try:
            connection.select("inbox")
            connection.store(email_id.encode(), "+FLAGS", "\\Seen")
            return True

        except Exception as e:
            self.logger.error(f"Error marking email as read: {e}")
            return False

        finally:
            self.disconnect()

    def mark_as_unread(self, email_id: str) -> bool:
        """
        Mark a specific email as unread.

        Args:
            email_id: Email ID to mark as unread

        Returns:
            True if successful
        """
        connection = self.connect()
        try:
            connection.select("inbox")
            connection.store(email_id.encode(), "-FLAGS", "\\Seen")
            return True

        except Exception as e:
            self.logger.error(f"Error marking email as unread: {e}")
            return False

        finally:
            self.disconnect()
