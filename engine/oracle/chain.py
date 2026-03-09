"""engine.oracle.chain

ERC-8004 on-chain client.  All methods fail-open: return None on error,
log a warning, never raise.  When ``identity_registry_address`` is None
the client silently no-ops — this lets the rest of the system run without
a deployed contract or configured RPC.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("b1e55ed.chain")

# Minimal ERC-8004 Identity Registry ABI (register + tokenURI)
_IDENTITY_REGISTRY_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"internalType": "string", "name": "agentURI", "type": "string"}],
        "name": "register",
        "outputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "tokenURI",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Minimal Reputation Registry ABI (postKarma)
_REPUTATION_REGISTRY_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "agentId", "type": "uint256"},
            {"internalType": "int256", "name": "karmaDelta", "type": "int256"},
            {"internalType": "string", "name": "tag", "type": "string"},
            {"internalType": "string", "name": "fileURI", "type": "string"},
            {"internalType": "bytes32", "name": "fileHash", "type": "bytes32"},
        ],
        "name": "postKarma",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# Minimal Validation Registry ABI (postValidation)
_VALIDATION_REGISTRY_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "agentId", "type": "uint256"},
            {"internalType": "string", "name": "verdict", "type": "string"},
            {"internalType": "string", "name": "resultURI", "type": "string"},
            {"internalType": "bytes32", "name": "resultHash", "type": "bytes32"},
        ],
        "name": "postValidation",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class ChainClient:
    """ERC-8004 on-chain identity & reputation client.

    Fail-open design: every public method returns ``None`` when the chain
    layer is unconfigured or when a transaction fails.  The caller never
    needs to handle exceptions from this class.
    """

    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        identity_registry_address: str | None = None,
        reputation_registry_address: str | None = None,
        validation_registry_address: str | None = None,
        public_base_url: str = "",
    ) -> None:
        self._rpc_url = rpc_url
        self._private_key = private_key
        self._public_base_url = public_base_url  # Fully-qualified base URL for on-chain agentURI minting
        self._identity_registry_address = identity_registry_address
        self._reputation_registry_address = reputation_registry_address
        self._validation_registry_address = validation_registry_address

        self._w3: Any = None
        self._account: Any = None
        self._identity_contract: Any = None
        self._reputation_contract: Any = None
        self._validation_contract: Any = None

        if not rpc_url or not private_key:
            logger.info("ChainClient: rpc_url or private_key not set — chain layer disabled")
            return

        try:
            from web3 import Web3

            self._w3 = Web3(Web3.HTTPProvider(rpc_url))
            self._account = self._w3.eth.account.from_key(private_key)

            if identity_registry_address:
                self._identity_contract = self._w3.eth.contract(
                    address=Web3.to_checksum_address(identity_registry_address),
                    abi=_IDENTITY_REGISTRY_ABI,
                )

            if reputation_registry_address:
                self._reputation_contract = self._w3.eth.contract(
                    address=Web3.to_checksum_address(reputation_registry_address),
                    abi=_REPUTATION_REGISTRY_ABI,
                )

            if validation_registry_address:
                self._validation_contract = self._w3.eth.contract(
                    address=Web3.to_checksum_address(validation_registry_address),
                    abi=_VALIDATION_REGISTRY_ABI,
                )

            logger.info(
                "ChainClient initialised (identity=%s, reputation=%s, validation=%s)",
                identity_registry_address or "disabled",
                reputation_registry_address or "disabled",
                validation_registry_address or "disabled",
            )
        except Exception:
            logger.warning("ChainClient: failed to initialise web3 — chain layer disabled", exc_info=True)
            self._w3 = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _send_tx(self, fn: Any) -> str | None:
        """Build, sign, and send a contract function call.  Returns tx hash hex or None."""
        if self._w3 is None or self._account is None:
            return None
        try:
            tx = fn.build_transaction(
                {
                    "from": self._account.address,
                    "nonce": self._w3.eth.get_transaction_count(self._account.address),
                    "gas": 300_000,
                    "gasPrice": self._w3.eth.gas_price,
                }
            )
            signed = self._account.sign_transaction(tx)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            return self._w3.to_hex(tx_hash)
        except Exception:
            logger.warning("ChainClient: tx send failed", exc_info=True)
            return None

    @property
    def enabled(self) -> bool:
        return self._w3 is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_producer(self, agent_uri: str) -> int | None:
        """Mint ERC-8004 NFT.  Returns agentId (tokenId) or None if not configured."""
        if self._identity_contract is None:
            logger.debug("register_producer: identity registry not configured — skipping")
            return None
        try:
            fn = self._identity_contract.functions.register(agent_uri)
            tx_hash = self._send_tx(fn)
            if tx_hash is None:
                return None

            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            # Extract tokenId from Transfer event log (topic 0 = Transfer, topic 3 = tokenId)
            for log_entry in receipt.get("logs", []):
                topics = log_entry.get("topics", [])
                if len(topics) >= 4:
                    token_id = int.from_bytes(topics[3], byteorder="big")
                    logger.info("register_producer: minted agentId=%d tx=%s", token_id, tx_hash)
                    return token_id

            # Fallback: parse returnValue if available
            logger.warning("register_producer: tx succeeded (%s) but could not extract tokenId from logs", tx_hash)
            return None
        except Exception:
            logger.warning("register_producer: failed", exc_info=True)
            return None

    def post_karma_feedback(
        self,
        agent_id: int,
        karma_delta: float,
        tag: str,
        file_uri: str = "",
        file_hash: bytes = b"",
    ) -> str | None:
        """Write karma to Reputation Registry.  Returns tx_hash or None."""
        if self._reputation_contract is None:
            logger.debug("post_karma_feedback: reputation registry not configured — skipping")
            return None
        try:
            # Convert float karma to int256 (scale by 1e6 for 6 decimal precision)
            karma_int = int(karma_delta * 1_000_000)
            padded_hash = file_hash.ljust(32, b"\x00")[:32]

            fn = self._reputation_contract.functions.postKarma(
                agent_id,
                karma_int,
                tag,
                file_uri,
                padded_hash,
            )
            tx_hash = self._send_tx(fn)
            if tx_hash:
                logger.info("post_karma_feedback: agentId=%d karma=%.6f tx=%s", agent_id, karma_delta, tx_hash)
            return tx_hash
        except Exception:
            logger.warning("post_karma_feedback: failed", exc_info=True)
            return None

    def post_validation(
        self,
        agent_id: int,
        verdict: str,
        result_uri: str = "",
        result_hash: bytes = b"",
    ) -> str | None:
        """Post council verdict to Validation Registry.  Returns tx_hash or None."""
        if self._validation_contract is None:
            logger.debug("post_validation: validation registry not configured — skipping")
            return None
        try:
            padded_hash = result_hash.ljust(32, b"\x00")[:32]

            fn = self._validation_contract.functions.postValidation(
                agent_id,
                verdict,
                result_uri,
                padded_hash,
            )
            tx_hash = self._send_tx(fn)
            if tx_hash:
                logger.info("post_validation: agentId=%d verdict=%s tx=%s", agent_id, verdict, tx_hash)
            return tx_hash
        except Exception:
            logger.warning("post_validation: failed", exc_info=True)
            return None
