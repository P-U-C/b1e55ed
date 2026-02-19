"""engine.security

Security + identity primitives.

Tier model (v1.0):
- Tier 0: environment variables
- Tier 1: encrypted vault file (Fernet)
- Tier 2: OS keyring (optional)

The chain remembers.
"""

from engine.security.audit import AuditLogger
from engine.security.identity import NodeIdentity, ensure_identity, generate_node_identity
from engine.security.keystore import Keystore, KeystoreTier
from engine.security.redaction import redact_secrets, sanitize_for_log

__all__ = [
    "AuditLogger",
    "NodeIdentity",
    "ensure_identity",
    "generate_node_identity",
    "Keystore",
    "KeystoreTier",
    "redact_secrets",
    "sanitize_for_log",
]
