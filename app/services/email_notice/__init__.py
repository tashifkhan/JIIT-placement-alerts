"""Email notice extraction service package."""

from services.email_notice.models import (
    ExtractedNotice,
    NoticeDocument,
    NoticeGraphState,
)
from services.email_notice.prompts import (
    LIKELY_ON_CAMPUS_PROMPT,
    NOTICE_EXTRACTION_PROMPT,
)
from services.email_notice.service import EmailNoticeService

__all__ = [
    "NOTICE_EXTRACTION_PROMPT",
    "LIKELY_ON_CAMPUS_PROMPT",
    "EmailNoticeService",
    "ExtractedNotice",
    "NoticeDocument",
    "NoticeGraphState",
]
