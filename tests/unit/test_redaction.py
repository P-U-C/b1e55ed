from __future__ import annotations

from engine.security.redaction import redact_secrets, sanitize_for_log


def test_redact_secrets_api_keys_and_wallets() -> None:
    text = "openai=sk-proj-abcdefghijklmnopqrstuv1234567890 and eth=0x" + "a" * 40
    out = redact_secrets(text)
    assert "sk-proj-" not in out
    assert "0x" + "a" * 40 not in out
    assert "[REDACTED]" in out


def test_sanitize_for_log_nested() -> None:
    payload = {
        "api_key": "secret123",
        "nested": {"token": "eyJabc.eyJdef.ghi", "notes": "ok"},
        "list": ["xai-abcdefghijklmnopqrstuv12345"],
    }

    clean = sanitize_for_log(payload)
    assert clean["api_key"] == "[REDACTED]"
    assert clean["nested"]["token"] == "[REDACTED]"
    assert clean["nested"]["notes"] == "ok"
    assert clean["list"][0] == "[REDACTED]"
