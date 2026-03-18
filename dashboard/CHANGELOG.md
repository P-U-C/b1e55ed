# Dashboard Changelog

## v1.0.0-beta.1 — 2026-03-08

Initial dashboard release. Engineering-first monitoring interface.

### What's in v1
- Brain overview (home): system status, signal feed, kill switch
- Cockpit: "The Call" synthesis view, producer breakdown, benchmarks
- Signals: full signal history with type/domain filtering
- Producers: health table, registration form, failure tracking
- Social: pipeline diagnostics, watchlist, curator feed, sentiment panels
- Artifacts: research artifact listing with permalink access
- Positions: portfolio positions view (empty state)
- Performance: P&L, Sharpe, win rate, weight history
- Identity: node identity, forge details, network discovery (coming soon)
- Contributors: contributor registry

### Known Issues (addressed in v2)
- 404 pages in nav (forecasts, karma, curator, settings)
- Raw Unix timestamps exposed throughout UI
- Corrupted timestamps in social curator feed
- Localhost URL artifact in producer registration form
- Social page exposes raw API endpoint as user instruction
- No live market price context anywhere
- No data visualizations — all tables and text
- 13-item nav (overcrowded)
- Monospace font used for all text (readability issue)
- No urgency hierarchy for producer failures

---

## v1.0.0-beta.2 — TBD

UX overhaul. Sprint 1+2 changes. See `docs/ux/` for full specs.
