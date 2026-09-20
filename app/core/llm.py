"""Shared Gemini chat-model factory for notice and offer extraction."""

from typing import Any, List, Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from core.config import get_settings

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_THINKING_LEVEL = "low"


def build_chat_model(
    *,
    model: Optional[str] = None,
    temperature: float = 0,
    api_key: Optional[str] = None,
    thinking_level: Optional[str] = None,
) -> ChatGoogleGenerativeAI:
    """Build the Gemini chat model used by every LangGraph pipeline."""
    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=model or settings.llm_model,
        temperature=temperature,
        api_key=api_key or settings.google_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        thinking_level=thinking_level or settings.llm_thinking_level,
    )


def message_text(message_or_content: Any) -> str:
    """Flatten a LangChain message or Gemini content payload to text."""
    if message_or_content is None:
        return ""

    text = getattr(message_or_content, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    content = getattr(message_or_content, "content", message_or_content)
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").lower()
            if part_type in {"thinking", "reasoning"}:
                continue
            value = part.get("text")
            if value:
                parts.append(str(value))
        return "\n".join(parts)

    return str(content)
