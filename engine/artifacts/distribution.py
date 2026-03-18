"""engine.artifacts.distribution

Delivery channels for generated artifacts.

Reads config from b1e55ed's user config file.
All channels are optional — gracefully skip if not configured.
"""

from __future__ import annotations

import email.mime.multipart
import email.mime.text
import json
import logging
import smtplib
from typing import Any

from engine.artifacts.store import ArtifactRecord

logger = logging.getLogger(__name__)


# Brand's Whole Earth Catalog (1968): "Access to tools."
# The artifact is the tool. Distribution is the access.
# The pipeline exists so knowledge doesn't die in the directory that made it.
# McLuhan (1964): the medium is the message.
# An artifact distributed by email carries institutional weight.
# The same artifact in Slack carries immediacy. Via webhook, automation.
# The content is identical. The meaning shifts with the channel.
class ArtifactDistributor:
    """Best-effort delivery of artifacts to configured channels."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = (config or {}).get("artifacts", {})

    def distribute(self, record: ArtifactRecord, permalink: str) -> list[str]:
        """Distribute artifact to all configured channels.

        Returns list of channels successfully delivered to.
        Logs failures but does not raise — distribution is best-effort.
        """
        delivered: list[str] = []

        for name, handler in [
            ("email", self._send_email),
            ("slack", self._send_slack),
            ("webhook", self._send_webhook),
        ]:
            channel_cfg = self._config.get(name)
            if not channel_cfg:
                continue
            try:
                handler(record, permalink, channel_cfg)
                delivered.append(name)
            except Exception:
                logger.exception("Artifact distribution failed for channel=%s artifact=%s", name, record.id)

        return delivered

    # ------------------------------------------------------------------
    # Channel implementations
    # ------------------------------------------------------------------

    def _send_email(
        self,
        record: ArtifactRecord,
        permalink: str,
        cfg: dict[str, Any],
    ) -> None:
        """Send artifact via SMTP (stdlib smtplib, no external SDK)."""
        smtp_host = cfg.get("smtp_host")
        smtp_port = int(cfg.get("smtp_port", 587))
        smtp_user = cfg.get("smtp_user", "")
        smtp_password = cfg.get("smtp_password", "")
        from_addr = cfg.get("from_addr", smtp_user)
        to_addrs: list[str] = cfg.get("to_addrs", [])

        if not smtp_host or not to_addrs:
            return

        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["Subject"] = f"[b1e55ed] Research artifact: {record.filename}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)

        body_text = f"New research artifact: {record.filename}\nSource: {record.source}\nPermalink: {permalink}\n"
        body_html = (
            f"<h3>New research artifact</h3>"
            f"<p><strong>{record.filename}</strong></p>"
            f"<p>Source: {record.source}</p>"
            f'<p><a href="{permalink}">View artifact</a></p>'
        )

        msg.attach(email.mime.text.MIMEText(body_text, "plain"))
        msg.attach(email.mime.text.MIMEText(body_html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_port == 587:
                server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, to_addrs, msg.as_string())

        logger.info("Artifact %s emailed to %s", record.id[:12], to_addrs)

    def _send_slack(
        self,
        record: ArtifactRecord,
        permalink: str,
        cfg: dict[str, Any],
    ) -> None:
        """Post artifact notification to Slack via incoming webhook."""
        import urllib.request

        webhook_url = cfg.get("webhook_url")
        if not webhook_url:
            return

        payload = json.dumps(
            {
                "text": f"New research artifact: {record.filename}",
                "attachments": [{"text": permalink}],
            }
        ).encode()

        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)

        logger.info("Artifact %s posted to Slack", record.id[:12])

    def _send_webhook(
        self,
        record: ArtifactRecord,
        permalink: str,
        cfg: dict[str, Any],
    ) -> None:
        """POST artifact metadata to a generic webhook URL."""
        import urllib.request

        url = cfg.get("url")
        if not url:
            return

        payload = json.dumps(
            {
                "artifact_id": record.id,
                "filename": record.filename,
                "permalink": permalink,
                "source": record.source,
                "event_id": record.event_id,
            }
        ).encode()

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)

        logger.info("Artifact %s sent to webhook %s", record.id[:12], url)
