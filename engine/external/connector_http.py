"""HTTP connector for external producer endpoints.

Uses stdlib only — no third-party HTTP libraries.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime
from urllib.parse import urlencode

try:
    from datetime import UTC  # py311+
except ImportError:  # pragma: no cover
    from datetime import timezone as _tz  # noqa: PLC0415

    UTC = _tz.utc  # noqa: N806, UP017

from engine.external.models import RawExternalRecord

_ADAPTER_VERSION = "1.0.0"
_USER_AGENT = "b1e55ed-adapter/1.0"


class HttpConnector:
    """Polling HTTP connector for external producer endpoints."""

    def __init__(self, base_url: str, timeout_sec: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def fetch(
        self,
        path: str,
        method: str = "GET",
        params: dict | None = None,
        headers: dict | None = None,
        source_system: str = "",
    ) -> RawExternalRecord:
        """Fetch from the external endpoint and return a RawExternalRecord.

        Args:
            path: URL path to append to base_url.
            method: HTTP method ("GET" or "POST").
            params: Query string parameters.
            headers: Additional request headers.
            source_system: Logical source name to embed in the record.

        Returns:
            RawExternalRecord with hashed payload and ISO fetch timestamp.

        Raises:
            urllib.error.URLError: On network/HTTP errors.
        """
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        req_headers = {"User-Agent": _USER_AGENT}
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, headers=req_headers, method=method.upper())

        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:  # noqa: S310
            raw = json.loads(resp.read())

        payload_hash = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()

        fetched_at = datetime.now(tz=UTC).isoformat()

        return RawExternalRecord(
            source_system=source_system,
            source_endpoint=path,
            source_payload_hash=payload_hash,
            adapter_version=_ADAPTER_VERSION,
            raw_payload=raw,
            fetched_at=fetched_at,
        )

    def health_check(self, path: str, timeout_sec: int | None = None) -> bool:
        """Perform a health-check GET and return True if the response is 2xx.

        Never raises — returns False on any error.
        """
        try:
            url = f"{self.base_url}{path}"
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            timeout = timeout_sec if timeout_sec is not None else self.timeout_sec
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return 200 <= resp.status < 300
        except Exception:  # noqa: BLE001
            return False
