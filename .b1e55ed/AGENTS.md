# .b1e55ed/AGENTS.md — Operator & Agent Playbook

This repository is a system. Treat it like one.

## First principles

- **Event contract is the primitive.** If it doesn't read/write events, it doesn't belong.
- **Three config surfaces max.** `config/default.yaml`, `config/presets/*.yaml`, env vars (secrets only).
- **Two execution modes.** `paper` and `live`. Nothing in between.
- **Hash chain scope: all events.** Auditability is not optional.

## Session / Agent hygiene

When working inside an agent runtime (OpenClaw or similar):

1. Read `.b1e55ed/SOUL.md` (system ethos)
2. Read `user/CRITICAL.md` (if present) — **source of truth** for trading state
3. Prefer state files over chat memory. Compaction happens. Files persist.

### CRITICAL.md

**Why it exists**: you will forget an open position exactly once.

CRITICAL.md MUST contain:
- Open positions (asset, entry, size, stop, target)
- Pending transactions
- Wallet balances
- Active alerts
- Recent critical decisions

Rules:
- Read on every session start
- Update immediately after any position change
- If chat memory conflicts with CRITICAL.md → **CRITICAL.md wins**

## Repo workflow

- Work on `develop`. PR to `main`.
- Atomic commits. Prefer:
  - `chore:` scaffolding/tooling
  - `feat(core):` foundational modules
  - `test(core):` unit tests

## Safety

- Never commit secrets. Use env vars.
- `user/` and `data/` are gitignored for a reason.
- The exchange will not save you.

## Easter egg policy

Two modes. Nothing in between.

- Eggs live in **docstrings, comments, constants, test names**.
- Eggs never obscure business logic.
- No hype language. Precision carries the energy.

The hex is blessed: `0xb1e55ed`.
