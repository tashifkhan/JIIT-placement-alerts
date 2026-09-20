"""Email parsing and privacy helpers for placement offer extraction."""

import re


def strip_headers_and_forwarded_markers(text: str) -> str:
    """Remove email headers and forwarding markers from user-facing text."""
    if not text:
        return text

    header_patterns = [
        r"^\s*(From|Sender|Sent|To|Cc|Subject)\s*:.*$",
        r"^\s*(Fwd|FW)\s*:.*$",
        r"^\s*(Begin forwarded message|Forwarded message).*$",
        r"^\s*On .+ wrote:\s*$",
    ]

    lines = text.splitlines()
    cleaned_lines: list[str] = []
    for line in lines:
        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in header_patterns):
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\bvia\s+[^\s\n]+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bforward(ed)?(\s+message)?\b", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def extract_forwarded_date(text: str) -> str | None:
    """Extract forwarded email date and convert it to an ISO timestamp."""
    if not text:
        return None

    date_patterns = [
        r"Date:\s*([^\n\r]+?)(?:\s*\n|\s*\r|\s*Subject:|$)",
        r"Date:\s*(.+?)(?:<br>|Subject:|To:|$)",
        r"Date:\s*([A-Za-z]{3},?\s+\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}(?:,?\s+(?:at\s+)?\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)?)",
    ]

    date_str = None
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1).strip().rstrip(",")
            break

    if not date_str:
        return None

    date_str = re.sub(r",\s*,", ",", date_str)
    date_str = re.sub(r"<[^>]+>", "", date_str).strip()
    date_str = re.sub(
        r"\s*(Subject|To)\s*:.*$", "", date_str, flags=re.IGNORECASE
    ).strip()

    if not date_str:
        return None

    try:
        import unicodedata
        from datetime import timedelta, timezone

        from dateutil import parser as date_parser

        date_str = "".join(
            " " if unicodedata.category(char) in ("Zs", "Cc") else char
            for char in date_str
        )
        date_str = " ".join(date_str.split())
        parsed_date = date_parser.parse(date_str, fuzzy=True)
        ist = timezone(timedelta(hours=5, minutes=30))

        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=ist)
        else:
            parsed_date = parsed_date.astimezone(ist)

        return parsed_date.isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def extract_forwarded_sender(text: str) -> str | None:
    """Extract original sender from forwarded email headers."""
    if not text:
        return None

    forwarded_patterns = [
        r"-+\s*Forwarded message\s*-+",
        r"Begin forwarded message",
        r"Fwd:",
        r"FW:",
    ]
    is_forwarded = any(re.search(pattern, text, re.IGNORECASE) for pattern in forwarded_patterns)
    if not is_forwarded:
        return None

    from_pattern = r"From:\s*(.+?)(?:\n|$)"
    match = re.search(from_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(",")
    return None


def extract_json_from_response(response_content: str) -> str:
    """Extract JSON from LLM response, handling markdown code blocks."""
    json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(json_pattern, response_content)
    return match.group(1).strip() if match else response_content.strip()
