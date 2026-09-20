"""Email fetching helpers for placement offer extraction."""

from typing import Dict, List

from clients.google_groups_client import GoogleGroupsClient


class PlacementEmailFetcherMixin:
    """Email fetching behavior for PlacementService."""

    def fetch_unread_emails(self) -> List[Dict[str, str]]:
        """
        Fetch unread emails from IMAP.

        Uses GoogleGroupsClient if available, otherwise falls back to the legacy
        Gmail IMAP implementation.
        """
        client = self.email_client or GoogleGroupsClient(
            email_address=self.email_address,
            app_password=self.app_password,
        )
        emails = client.fetch_unread_emails(mark_as_read=True)
        return [
            {
                "subject": item.get("subject", ""),
                "sender": item.get("sender", ""),
                "body": item.get("body", ""),
                "time_sent": item.get("time_sent", ""),
                "message_id": item.get("message_id", ""),
                "email_id": item.get("email_id", ""),
            }
            for item in emails
        ]
