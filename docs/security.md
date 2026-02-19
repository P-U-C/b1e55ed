# Security Architecture

b1e55ed security model: minimize trust, maximize auditability.

---

## Core Principles

1. **Event-sourced integrity** - Hash chain commits to full event record
2. **Secure by default** - Refuse to start in insecure configuration
3. **Encrypted at rest** - Identity keys encrypted with master password
4. **Consistent identity** - Single signing key across all operations
5. **Audit trail** - Every event signed and traceable

---

## Event Hash Chain

### What It Does

Every event appended to `brain.db` includes a cryptographic hash that commits to:
- Previous event hash (chain linkage)
- Timestamp (prevents backdating)
- Event ID (prevents duplication)
- Event type (prevents type confusion)
- Schema version (prevents downgrade attacks)
- Source, trace ID, dedupe key (metadata integrity)
- Payload (content integrity)

This creates a tamper-evident append-only log. Modifying any field breaks the chain.

### Implementation

**Hash computation** (`engine/core/models.py`):
```python
def compute_event_hash(
    *,
    prev_hash: str | None,
    event_type: EventType,
    payload: dict[str, Any],
    ts: datetime,
    source: str | None,
    trace_id: str | None,
    schema_version: str,
    dedupe_key: str | None,
    event_id: str,
) -> str:
    """Commits to full event header + payload."""
    header_parts = [
        prev_hash or "",
        ts.isoformat(),
        event_id,
        str(event_type),
        schema_version,
        source or "",
        trace_id or "",
        dedupe_key or "",
    ]
    data = "|".join(header_parts) + "|" + canonical_json(payload)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
```

**Verification** (`engine/core/database.py`):
```python
def verify_hash_chain(self, fast: bool = True, last_n: int = 100) -> bool:
    """Verify event hash chain integrity."""
    # Recompute hash for each event and compare to stored hash
    # If any mismatch, chain is broken
```

### Security Guarantees

✅ **Tamper-evident:** Can't modify any field without breaking chain  
✅ **Append-only:** Can't reorder or delete events without detection  
✅ **Timestamped:** Can't backdate events  
✅ **Traceable:** Every event links to previous  

❌ **Not encrypted:** Events are plaintext (encrypted at rest via filesystem/disk encryption)  
❌ **Not distributed:** Single SQLite file (backup/replication is operator responsibility)  

---

## API Security

### Secure by Default

**API refuses to start** if `auth_token` is empty (unless `B1E55ED_INSECURE_OK=1` override).

**Why:** Prevents accidental deployment without authentication.

**Error message:**
```
❌ SECURITY ERROR: API auth_token is empty

Set B1E55ED_API__AUTH_TOKEN environment variable or add to config:
  api:
    auth_token: your-secret-token

To run without auth (dev/test only), set B1E55ED_INSECURE_OK=1
```

### CORS Configuration

**Before (insecure):**
```python
allow_origins=["*"]  # Wide open
allow_credentials=True  # With credentials = footgun
```

**After (secure):**
```yaml
api:
  cors_origins: []  # Empty = CORS disabled
  # Or explicit allow list:
  # cors_origins: ["https://dashboard.example.com"]
```

**Why:** `allow_origins=["*"]` + `allow_credentials=True` allows any site to make authenticated requests to your API.

### Authentication

**Bearer token required** for protected endpoints:
```bash
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://localhost:5050/brain/run
```

**Protected endpoints:**
- `POST /brain/run` - Trigger manual cycle
- `GET /positions` - View open positions
- All karma endpoints

**Public endpoints:**
- `GET /health` - System status
- `GET /signals` - Recent signals (read-only)

### Rate Limiting

**Default:** 100 requests/minute per IP (not yet implemented, placeholder for v1.0.0)

---

## Identity & Signing

### Node Identity

Every b1e55ed instance has a persistent Ed25519 identity:
- **Node ID:** `b1e55ed-<hex>`
- **Public key:** Ed25519 public key (hex)
- **Private key:** Ed25519 private key (encrypted at rest)

**Location:** `~/.b1e55ed/identity.key`

### Encryption at Rest

**With master password** (production):
```json
{
  "node_id": "b1e55ed-abc123...",
  "public_key": "deadbeef...",
  "private_key_enc": "encrypted-blob",
  "kdf": {
    "name": "pbkdf2_hmac_sha256",
    "iterations": 480000,
    "salt_b64": "random-salt"
  }
}
```

**Without master password** (dev mode only):
```json
{
  "node_id": "b1e55ed-abc123...",
  "public_key": "deadbeef...",
  "private_key": "plaintext-hex",
  "warning": "DEVELOPMENT MODE: identity private key stored unencrypted"
}
```

**Environment variables:**
- `B1E55ED_MASTER_PASSWORD` - Encrypt identity (required for production)
- `B1E55ED_DEV_MODE=1` - Allow plaintext (dev/test only)

**Security policy:**
```python
if not master_password and not dev_mode:
    raise ValueError(
        "SECURITY ERROR: Cannot save plaintext identity without B1E55ED_DEV_MODE=1. "
        "Set B1E55ED_MASTER_PASSWORD to encrypt identity at rest."
    )
```

### Identity Consistency

**Before (broken audit trail):**
- CLI: Persisted identity (`~/.b1e55ed/identity.key`)
- API: Ephemeral identity (new key per request)
- Result: Events signed by different keys, no accountability

**After (consistent):**
- Both CLI and API: Same persisted identity via `ensure_identity()`
- All events signed by same key
- Audit trail traceable to single node_id

### Signing Flow

```python
# 1. Load or generate identity
identity = ensure_identity()

# 2. Sign event payload
data = canonical_json(payload).encode("utf-8")
signature = identity.sign(data)

# 3. Store in event
event = {
    "payload": payload,
    "signature": signature.hex(),
    "signer": identity.node_id,
}
```

**Verification:**
```python
identity.verify(signature, data)  # Returns True/False
```

---

## Secret Management

### Storage Tiers

**Tier 0: Environment Variables**
- Read from `os.environ`
- No persistence
- Secure: Yes (process-isolated)

**Tier 1: Encrypted Vault** (Fernet)
- File: `~/.b1e55ed/keystore.vault`
- Encryption: Fernet (AES-128-CBC + HMAC-SHA256)
- Password: `B1E55ED_MASTER_PASSWORD`

**Tier 2: OS Keyring** (optional, future)
- Platform-specific (Keychain on macOS, Secret Service on Linux, etc.)
- Not yet implemented

### Keystore Usage

**Save secret:**
```python
from engine.security import Keystore

ks = Keystore.ensure_default()
ks.set("api_key", "secret-value", tier=KeystoreTier.VAULT)
```

**Retrieve secret:**
```python
api_key = ks.get("api_key")
```

**Precedence:**
1. Environment variable (if set)
2. Vault (if exists)
3. OS keyring (future)
4. Raise error if not found

### Best Practices

✅ **Do:**
- Store API keys in vault or environment
- Use `B1E55ED_MASTER_PASSWORD` in production
- Rotate secrets regularly
- Use `.env` files locally (gitignored)

❌ **Don't:**
- Hardcode secrets in code
- Commit secrets to git
- Store plaintext secrets in config files
- Share master password in chat/email

---

## Redaction & Logging

### Automatic Redaction

**Before logging:**
```python
from engine.security import sanitize_for_log

safe_data = sanitize_for_log(raw_data)
logger.info("event", extra={"data": safe_data})
```

**What gets redacted:**
- API keys (pattern: `sk-`, `xai-`, etc.)
- Bearer tokens
- Private keys
- Passwords
- Auth headers

**Replacement:** `***REDACTED***`

### Audit Logging

**Audit events** (`engine.security.audit.AuditLogger`):
```python
audit = AuditLogger(db=db, identity=identity)

audit.log_access(resource="/positions", action="read", outcome="allowed")
audit.log_access(resource="/brain/run", action="write", outcome="denied", reason="kill_switch_active")
```

**Stored in:** `brain.db` events table with type `system.audit.v1`

**Use cases:**
- Track who accessed what
- Detect anomalous access patterns
- Compliance/forensics

---

## Kill Switch

### Purpose

**Emergency shutdown** when system detects:
- Unusual trading activity
- Large unexpected losses
- Policy violations
- External threats

### Levels

| Level | State | Action |
|-------|-------|--------|
| 0 | Normal | No restrictions |
| 1 | Caution | Log warnings, continue |
| 2 | Crisis | **Block new trades**, allow exits |
| 3 | Lockdown | **Block all trades**, manual intervention required |

### Monotonic Escalation

**Rule:** Kill switch can only escalate, never auto-de-escalate.

**Why:** Prevents "recovered for 30 seconds" from re-arming risk before operator reviews.

**Manual reset:**
```bash
b1e55ed kill-switch reset --level 0 --reason "Issue resolved, reviewed by operator"
```

### Events

**Escalation:**
```json
{
  "type": "system.kill_switch.v1",
  "payload": {
    "level": 2,
    "prev_level": 1,
    "reason": "Large unrealized loss detected: -15%",
    "triggered_by": "risk_monitor"
  }
}
```

**Reset:**
```json
{
  "type": "system.kill_switch.v1",
  "payload": {
    "level": 0,
    "prev_level": 2,
    "reason": "Issue resolved, reviewed by operator",
    "reset_by": "b1e55ed-abc123..."
  }
}
```

---

## DCG (Don't Cross the Guys)

### Purpose

**Blacklist** for symbols that should never be traded (regulatory, reputational, or strategic reasons).

### Configuration

```yaml
execution:
  dcg_symbols: ["USDT", "LUNA", "FTT"]
```

**Enforcement:** OMS rejects any trade in DCG symbols before execution.

### Events

```json
{
  "type": "system.dcg_violation.v1",
  "payload": {
    "symbol": "USDT",
    "action": "buy",
    "reason": "Symbol in DCG blacklist",
    "blocked_at": "2026-02-19T03:00:00Z"
  }
}
```

---

## Threat Model

### What We Protect Against

✅ **Insider threat:** Audit trail tracks all actions  
✅ **Configuration errors:** Secure-by-default prevents accidental exposure  
✅ **Tampering:** Hash chain detects modified events  
✅ **Unauthorized API access:** Bearer token required  
✅ **Secret leakage:** Encrypted storage + redaction  

### What We Don't Protect Against

❌ **Physical access:** If attacker has filesystem access, they can read `brain.db`  
❌ **Memory dumping:** Private keys exist in memory during operation  
❌ **Side-channel attacks:** No constant-time crypto (relies on cryptography library)  
❌ **DoS:** No rate limiting yet (v1.0.0 roadmap item)  
❌ **MITM:** API is HTTP by default (use nginx with TLS in production)  

### Deployment Recommendations

**For production:**
1. Set `B1E55ED_MASTER_PASSWORD` (encrypt identity + vault)
2. Set `B1E55ED_API__AUTH_TOKEN` (strong random token, 32+ chars)
3. Configure `api.cors_origins` (explicit allow list)
4. Run API behind nginx with TLS
5. Use filesystem encryption (LUKS, FileVault, etc.)
6. Backup `brain.db` regularly (encrypted backups)
7. Rotate secrets every 90 days
8. Monitor audit logs for anomalies

**For dev/test:**
1. Set `B1E55ED_DEV_MODE=1` (allow plaintext identity)
2. Set `B1E55ED_INSECURE_OK=1` (allow API without auth)
3. Never use dev mode in production

---

## Security Checklist

**Before deploying:**
- [ ] `B1E55ED_MASTER_PASSWORD` set (not empty)
- [ ] `B1E55ED_API__AUTH_TOKEN` set (32+ chars, random)
- [ ] `api.cors_origins` configured (not empty, explicit)
- [ ] `B1E55ED_DEV_MODE` not set (or set to 0)
- [ ] TLS enabled (nginx or similar)
- [ ] Filesystem encryption enabled
- [ ] Backup strategy defined
- [ ] Secret rotation policy defined
- [ ] Audit log monitoring enabled

**Regular maintenance:**
- [ ] Review audit logs weekly
- [ ] Rotate secrets every 90 days
- [ ] Backup `brain.db` daily
- [ ] Test backup restore monthly
- [ ] Update dependencies monthly
- [ ] Review kill switch events

**Incident response:**
1. Activate kill switch (level 2 or 3)
2. Review audit logs for unauthorized access
3. Verify hash chain integrity (`db.verify_hash_chain()`)
4. Rotate compromised secrets
5. Review and patch vulnerability
6. Document incident in audit log
7. Reset kill switch after resolution

---

## Compliance

**GDPR considerations:**
- Events may contain user data (if trading on behalf of users)
- Implement right-to-erasure (delete user events, but preserve hash chain)
- Log data retention policy (default: indefinite, configure per jurisdiction)

**SOC 2 Type II considerations:**
- Audit trail (events table)
- Access control (API auth)
- Encryption at rest (master password + filesystem)
- Change management (git commits + event log)

**PCI DSS considerations:**
- Not applicable (no credit card processing)
- If added: never store CC numbers in events

---

## Vulnerability Disclosure

**Found a security issue?**

1. **Don't** open a public GitHub issue
2. **Do** email security contact (define in SECURITY.md)
3. Include:
   - Description of vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (optional)

**Response timeline:**
- Acknowledgment: 48 hours
- Initial assessment: 7 days
- Fix deployed: 30 days (critical), 90 days (non-critical)
- Public disclosure: After fix deployed + 14 days

---

## References

- [Event Sourcing](https://martinfowler.com/eaaDev/EventSourcing.html)
- [Ed25519 Signatures](https://ed25519.cr.yp.to/)
- [Cryptography Library](https://cryptography.io/)
- [OWASP API Security](https://owasp.org/www-project-api-security/)

---

*Last updated: 2026-02-19 (after security hardening commit da9f429)*
