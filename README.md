# b1e55ed

<p align="center">
  <img src="assets/b1e55ed-hero.jpg" alt="b1e55ed" width="900" />
</p>

`0xb1e55ed` = **"blessed"** — a hex number that spells a word. The name is the first easter egg.

b1e55ed is a sovereign trading intelligence system. Not a mechanism — an organism.
It learns from every trade, every signal, every mistake. Its conviction weights shift. Its producer scores evolve. Its corpus grows. The system you deploy today is not the system running six months from now.

Built around one primitive: **events**. Producers emit events. The brain reads events and emits events. Execution reads events and emits events. An append-only hash chain makes the whole thing auditable by construction.

## Status

- **Phase 3 (Interface): in progress**
- **API** (FastAPI): available
- **Dashboard** (FastAPI + Jinja2 + HTMX): available (wired to API)
- Execution modes: **paper** and **live** (no dry run)

## Quickstart

```bash
# Python 3.11+
pip install uv
uv sync --dev

uv run pytest -q
uv run ruff check .
```

## Run (local)

Two processes:

```bash
# API (port 5050)
uv run uvicorn api.main:app --host 0.0.0.0 --port 5050

# Dashboard (port 5051)
B1E55ED_API_BASE_URL=http://127.0.0.1:5050 \
  uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 5051
```

### Env vars

- `B1E55ED_API_BASE_URL` (default: `http://127.0.0.1:5050`)
- `B1E55ED_API_TOKEN` (optional; if API auth is enabled)


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
