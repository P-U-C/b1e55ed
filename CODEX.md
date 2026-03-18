# CODEX.md — Agent Quick Reference

Read this first. It is the map. Follow links for depth.

## Repo layout

```
engine/
  producers/     # Signal producers (price_ws, polymarket, social, etc.)
  brain/         # Synthesis, orchestration, hierarchy
  spi/           # Signal Pipeline Interface — admission, karma, outcomes
  core/          # Events, models, types, DB
  cli.py         # Entry point: python3 -m engine.cli <command>
  config.py      # Config loading (user.yaml + env vars)
tests/
  producers/     # Producer unit tests
  unit/          # Core/brain/spi unit tests
docs/            # Architecture, API, deployment references
scripts/         # Utility scripts (not part of the engine)
```

Key source files:
- `engine/core/events.py` — EventType enum, Event model, payload_hash
- `engine/core/models.py` — Position, Signal, all domain models
- `engine/producers/base.py` — BaseProducer, BaseExternalProducer
- `engine/producers/registry.py` — @register decorator
- `engine/spi/admission.py` — SIGNAL_ACCEPTED_V1 gate (DO NOT MODIFY after Phase 1B)
- `engine/brain/orchestrator.py` — Brain loop (DO NOT MODIFY)

## Before you touch anything

```bash
# 1. Confirm clean baseline
cd /home/ubuntu/b1e55ed
git status
git fetch origin
git checkout -b <your-branch> origin/develop

# 2. Run baseline tests
python3 -m pytest --tb=short -q 2>&1 | tail -5
# Expected: ~1675 passed, 7 failed (pre-existing trio/async failures — ignore)
# If more than 7 failing: stop and report before writing any code

# 3. Check ruff
ruff check engine/ tests/ && echo "CLEAN"
```

## Branch and commit rules

- Always branch from `origin/develop`
- Branch names: `fix/<slug>`, `feat/<slug>`, `chore/<slug>`
- Commit format: `fix(scope): description` / `feat(scope): description`
- Conventional commits only — no "update" or "misc" messages

## Running tests

```bash
# All tests
python3 -m pytest --tb=short -q

# Single file
python3 -m pytest tests/producers/test_polymarket.py -v

# With coverage
python3 -m pytest --cov=engine --cov-report=term-missing -q
```

## Linting

```bash
ruff check engine/ tests/          # lint
ruff format engine/ tests/         # format
ruff check --fix engine/ tests/    # auto-fix
```

Both must pass clean before any commit.

## Pushing and opening a PR

```bash
GH_TOKEN=$(cat ~/.b1e55ed/env | grep GH_TOKEN | cut -d= -f2)
# Or: export GH_TOKEN=<your token>  — see ~/.b1e55ed/env or ask b1e55ed

git -c credential.helper="" push \
  "https://x-access-token:${GH_TOKEN}@github.com/P-U-C/b1e55ed.git" \
  <branch-name>

# Then open PR via gh CLI or API against base: develop
gh pr create --base develop --title "..." --body "..."
```

## Hard rules

- NEVER modify `engine/brain/orchestrator.py`
- NEVER modify `engine/spi/admission.py` after it exists
- NEVER push to a merged or closed PR branch
- NEVER silently skip `SIGNAL_ACCEPTED_V1`
- NEVER use `datetime.UTC` — use the UTC import shim at top of any file that needs it:
  ```python
  try:
      from datetime import UTC
  except ImportError:
      from datetime import timezone as _tz
      UTC = _tz.utc
  ```
- Audit logs are append-only — never mutate existing rows

## Pre-existing test failures (ignore these)

These 7 tests fail on develop and are NOT your problem:
- `test_api_events_sse.py::test_generator_poll_delivers_new_events[trio]`
- `test_api_scheduler_daemon_mode.py::test_api_scheduler_disabled_in_daemon_mode[trio]`
- `test_api_scheduler_daemon_mode.py::test_api_scheduler_runs_without_daemon_mode[trio]`
- `test_deerflow_trigger.py::test_poll_times_out[trio]`
- `test_deerflow_trigger.py::test_poll_returns_first_artifact[trio]`
- `test_deerflow_trigger.py::test_poll_skips_stale_artifact[trio]`
- `test_deerflow_trigger.py::test_poll_all_stale_returns_none[trio]`

## Deep references

- Architecture: `docs/architecture.md`
- API: `docs/api/`
- Deployment: `docs/deployment.md`
- Contributors/SPI: `docs/contributors.md`
- Backtest: `docs/backtest.md`
