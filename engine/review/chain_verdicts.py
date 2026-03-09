"""engine.review.chain_verdicts

Posts Review Council verdicts to the on-chain ERC-8004 Validation Registry.

Fail-open design: when chain_client is None or a transaction fails, the
method returns None and logs a warning.  Review processing is never
blocked by chain-layer issues.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.oracle.chain import ChainClient

logger = logging.getLogger("b1e55ed.review.chain")


class CouncilChainPoster:
    """Posts Review Council verdicts to the on-chain ERC-8004 Validation Registry."""

    def __init__(
        self,
        chain_client: ChainClient | None,
        system_agent_id: int = 0,
    ) -> None:
        self._chain_client = chain_client
        self._system_agent_id = system_agent_id

    @property
    def chain_client(self) -> ChainClient | None:
        return self._chain_client

    @property
    def system_agent_id(self) -> int:
        return self._system_agent_id

    @staticmethod
    def compute_verdict_hash(verdict_json: dict) -> bytes:
        """Compute SHA3-256 hash of the verdict JSON (first 32 bytes).

        The hash is deterministic: keys are sorted and the JSON is encoded
        as UTF-8 before hashing.
        """
        raw = json.dumps(verdict_json, sort_keys=True).encode()
        return hashlib.sha3_256(raw).digest()[:32]

    def post_verdict(
        self,
        verdict: str,
        pr_number: int,
        pr_url: str,
        verdict_json: dict,
    ) -> str | None:
        """Post verdict to Validation Registry.

        Parameters
        ----------
        verdict:
            One of ``"pass"``, ``"concern"``, ``"block"``, ``"human-required"``.
        pr_number:
            GitHub pull request number.
        pr_url:
            Full URL to the pull request.
        verdict_json:
            Complete verdict payload (hashed for on-chain storage).

        Returns
        -------
        str | None
            Transaction hash hex string, or ``None`` if chain layer is
            unconfigured or the transaction failed.
        """
        if self._chain_client is None:
            logger.debug("post_verdict: chain_client is None — skipping on-chain write")
            return None

        try:
            result_uri = pr_url
            result_hash = self.compute_verdict_hash(verdict_json)

            tx_hash = self._chain_client.post_validation(
                agent_id=self._system_agent_id,
                verdict=verdict,
                result_uri=result_uri,
                result_hash=result_hash,
            )

            if tx_hash:
                logger.info(
                    "post_verdict: PR #%d verdict=%s tx=%s",
                    pr_number,
                    verdict,
                    tx_hash,
                )
            else:
                logger.debug(
                    "post_verdict: PR #%d verdict=%s — chain returned None (unconfigured or failed)",
                    pr_number,
                    verdict,
                )

            return tx_hash
        except Exception:
            logger.warning(
                "post_verdict: failed for PR #%d verdict=%s",
                pr_number,
                verdict,
                exc_info=True,
            )
            return None
