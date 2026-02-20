"""engine.security.ssrf

SSRF protection utilities.

Producers can be configured with arbitrary HTTP endpoints. That is a security
boundary: without guardrails, a producer can be used to exfiltrate metadata
or pivot into internal networks (e.g. 169.254.169.254, 127.0.0.1, RFC1918).

Policy (v1):
- Only allow http/https
- Deny userinfo in URL
- Deny localhost
- Deny private / link-local / loopback / multicast / unspecified IP ranges
- Resolve DNS and require all A/AAAA records to be public

This is intentionally conservative.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class UrlCheck:
    allowed: bool
    reason: str | None = None
    host: str | None = None


_DENY_HOSTS = {
    "localhost",
    "localhost.localdomain",
}


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if addr.is_private:
        return False
    if addr.is_loopback:
        return False
    if addr.is_link_local:
        return False
    if addr.is_multicast:
        return False
    if addr.is_unspecified:
        return False
    return not addr.is_reserved


def check_url(url: str) -> UrlCheck:
    """Validate URL for SSRF safety."""

    try:
        u = urlparse(str(url))
    except Exception:
        return UrlCheck(False, reason="invalid_url")

    scheme = (u.scheme or "").lower()
    if scheme not in ("http", "https"):
        return UrlCheck(False, reason="scheme_not_allowed")

    if u.username or u.password:
        return UrlCheck(False, reason="userinfo_not_allowed")

    host = (u.hostname or "").lower().strip()
    if not host:
        return UrlCheck(False, reason="missing_host")

    if host in _DENY_HOSTS:
        return UrlCheck(False, reason="host_denied", host=host)

    # Fast path: literal IP
    try:
        ipaddress.ip_address(host)
        if not _is_public_ip(host):
            return UrlCheck(False, reason="ip_not_public", host=host)
        return UrlCheck(True, host=host)
    except Exception:
        pass

    # Resolve DNS; require all results to be public
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return UrlCheck(False, reason="dns_resolution_failed", host=host)

    ips: set[str] = set()
    for family, _socktype, _proto, _canon, sockaddr in infos:
        if family == socket.AF_INET or family == socket.AF_INET6:
            ips.add(str(sockaddr[0]))

    if not ips:
        return UrlCheck(False, reason="dns_no_records", host=host)

    for ip in ips:
        if not _is_public_ip(ip):
            return UrlCheck(False, reason=f"dns_ip_not_public:{ip}", host=host)

    return UrlCheck(True, host=host)
