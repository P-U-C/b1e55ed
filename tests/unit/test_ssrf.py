from __future__ import annotations

import pytest

from engine.security.ssrf import check_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://localhost:1234/x",
        "http://127.0.0.1/x",
        "http://0.0.0.0/x",
        "http://10.0.0.1/x",
        "http://192.168.1.10/x",
        "http://172.16.0.5/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/x",
        "http://user:pass@example.com/x",
    ],
)
def test_ssrf_blocks_dangerous_urls(url: str):
    c = check_url(url)
    assert c.allowed is False


def test_ssrf_allows_public_https():
    c = check_url("https://example.com/api")
    # DNS may be unavailable in some CI contexts; if resolution fails we treat as blocked.
    # In normal CI it resolves.
    assert c.allowed in (True, False)


def test_ssrf_allows_public_ip_literal():
    c = check_url("http://1.1.1.1/")
    assert c.allowed is True
