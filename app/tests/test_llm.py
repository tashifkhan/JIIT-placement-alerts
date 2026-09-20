"""Tests for the shared Gemini factory and message flattening."""

from types import SimpleNamespace

from core.llm import DEFAULT_GEMINI_MODEL, message_text


def test_default_model_is_gemini_3_8_flash() -> None:
    assert DEFAULT_GEMINI_MODEL == "gemini-3.8-flash"


def test_message_text_flattens_gemini_content_blocks() -> None:
    message = SimpleNamespace(
        text="",
        content=[
            {"type": "thinking", "text": "internal scratchpad"},
            {"type": "text", "text": '{"ok": true}'},
        ],
    )

    assert message_text(message) == '{"ok": true}'


def test_message_text_prefers_message_text_property() -> None:
    message = SimpleNamespace(text="plain answer", content=[{"type": "text", "text": "ignored"}])

    assert message_text(message) == "plain answer"
