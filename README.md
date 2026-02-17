# b1e55ed

`0xb1e55ed` = **"blessed"** — a hex number that spells a word. The name is the first easter egg.

b1e55ed is a sovereign trading intelligence system built around one primitive: **events**.
Producers emit events. The brain reads events and emits events. Execution reads events and emits events.
An append-only hash chain makes the system auditable by construction.

## Status

- Phase 0 (Foundation): in progress
- Execution modes: **paper** and **live** (no dry run)

## Quickstart

```bash
# Python 3.11+
pip install uv
uv sync --dev

uv run pytest tests/ -v
uv run ruff check .
```

## Design principles (non-negotiable)

- Event contract is the primitive
- Three config surfaces max: `config/default.yaml`, `config/presets/*.yaml`, env vars (secrets only)
- One kill switch, five levels
- Tests live in `tests/` (never alongside source)

## Repo layout

- `engine/` — core system (event store, config, producers, brain)
- `api/` — FastAPI boundary
- `dashboard/` — HTMX operator UI
- `config/` — defaults + presets
- `corpus/` — templates for patterns/theses/mistakes
- `.b1e55ed/` — agent/runtime guidance for operators

## Karma

> "We make a living by what we get. We make a life by what we give." — attributed to Winston Churchill

Karma is default-on (configurable) and only applies to **realized profits**.

## License

MIT.
