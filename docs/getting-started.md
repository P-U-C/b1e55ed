# Getting Started

b1e55ed is a CLI-first trading intelligence engine built around append-only events.

This guide covers a local first run.

## Quickstart (recommended)

### Install

```bash
curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/install.sh | bash
```

### Setup wizard

```bash
b1e55ed wizard
```

> **Running from source?** Use `./b1e55ed wizard` or `uv run b1e55ed wizard` instead.

---

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- SQLite (bundled on most systems)

Recommended:
- A dedicated `B1E55ED_MASTER_PASSWORD` for encrypted-at-rest identity and keystore material.

## Install

### Option A: Installer script (recommended)

```bash
curl -sSf https://raw.githubusercontent.com/P-U-C/b1e55ed/main/install.sh | bash
```

After install, `b1e55ed` is available globally in your PATH.

### Option B: From source

```bash
git clone https://github.com/P-U-C/b1e55ed.git
cd b1e55ed
uv sync
```

From-source users can use `./b1e55ed` (repo wrapper) or `uv run b1e55ed` for all commands.[^1]

[^1]: From-source: use `./b1e55ed command` or `uv run b1e55ed command`. Installed users: just `b1e55ed command`.

## Quick start (local)

Sequence: install → forge identity → setup → register contributor → run brain.

### 1) Forge an identity (The Forge)

The Forge derives an Ethereum identity with a `0xb1e55ed` prefix. Required if you plan to use EAS attestations.

```bash
b1e55ed identity forge
b1e55ed identity show
```

Outputs:
- `.b1e55ed/identity.json` (public identity)
- `.b1e55ed/forge_key.enc` (private key material; protect it)

If you are not using EAS attestations, forging is optional.

### 2) Run setup

Setup writes `config/user.yaml`, initializes `data/brain.db`, and stores secrets in the keystore when available.

```bash
export B1E55ED_MASTER_PASSWORD="your-secure-password"
b1e55ed setup
```

### 3) (Optional) Configure EAS

EAS is used to create and verify off-chain attestations for contributors.

Edit `config/user.yaml`:

```yaml
eas:
  enabled: false
  mode: offchain
  rpc_url: "https://eth.llamarpc.com"
  eas_contract: "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587"
  schema_registry: "0xA7b39296258348C78294F95B872b282326A97BDF"
  schema_uid: ""               # set after schema registration
  attester_private_key: ""     # required for creating attestations
```

See: [eas-integration.md](eas-integration.md).

### 4) Register a contributor

Contributors are the attribution unit for signals.

Register via CLI:

```bash
b1e55ed contributors register --name "local-operator" --role operator
```

If EAS is enabled and `eas.attester_private_key` is configured:

```bash
b1e55ed contributors register --name "local-operator" --role operator --attest
```

See: [contributors.md](contributors.md).

### 5) Run the brain

```bash
b1e55ed brain
```

Ingest your first signal:

```bash
b1e55ed signal "BTC breakout — confirmed on-chain" \
  --symbols BTC \
  --direction bullish \
  --conviction 7
```

See: [curator.md](curator.md) for the full curator pipeline.

### 6) Start API + dashboard

API requires `api.auth_token` unless `B1E55ED_INSECURE_OK=1` is set.

```bash
# Terminal 1
export B1E55ED_API__AUTH_TOKEN="your-secret-token"
b1e55ed api

# Terminal 2
b1e55ed dashboard

# Dashboard: http://localhost:5051
# API:       http://localhost:5050/api/v1/health
```

Check agent interfaces:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5050/api/v1/capabilities
```

## Next steps

- [Configuration](configuration.md)
- [CLI reference](cli-reference.md)
- [API reference](api-reference.md)
- [Architecture](architecture.md)
- [Agent interfaces](agent-interfaces.md)
- [Oracle](oracle.md)
- [Curator pipeline](curator.md)
