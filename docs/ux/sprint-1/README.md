# UX Sprint 1 — Stop The Bleeding

**Date:** 2026-07-20
**Branch:** `ux/sprint-1`
**Status:** Complete

---

## Fixes

### Fix 1: Remove 404 pages from nav

**Problem:** The task spec identified forecasts, karma, curator, and settings as 404 pages. On inspection, these links were already removed from `base.html` in prior work — all current nav items have valid routes.

**Solution:** Verified all 14 nav items (`/`, `/cockpit`, `/positions`, `/signals`, `/social`, `/artifacts`, `/contributors`, `/producers`, `/webhooks`, `/performance`, `/system`, `/identity`, `/config`, `/treasury`) resolve to real pages. No changes needed.

**Rationale:** Don't fix what isn't broken. The nav is clean.

---

### Fix 2: Relative timestamps everywhere

**Problem:** Raw ISO timestamps like `2026-03-07T14:38:22Z` and Unix epochs like `1740110218` displayed verbatim — meaningless to human eyes at a glance.

**Solution:** Added `timeago` and `fmt_iso` Jinja2 custom filters registered on the template environment in `dashboard/app.py`. `timeago` converts any ISO-8601 string, Unix timestamp, or Python datetime to relative strings ("35m ago", "2d ago"). `fmt_iso` returns the full UTC string for tooltip `title` attributes. Applied across: curator feed, social status, artifacts, identity, source health.

**Rationale:** Relative time is how humans think. Full ISO on hover for when you need precision.

---

### Fix 3: Fix corrupted timestamps in social curator feed

**Problem:** Curator feed was rendering raw `c.ts` values from the API — ISO strings that could appear corrupted like "2024-03..03-07DATE:21:18" depending on data quality.

**Solution:** The `timeago` filter now handles all curator feed timestamps, parsing ISO and Unix formats gracefully. Malformed strings fall through as-is rather than producing garbled output. The filter is applied in both `partials/curator_feed.html` and the inline curator section in `social.html`.

**Rationale:** A robust filter that handles edge cases beats template-level string slicing.

---

### Fix 4: Remove localhost URL from producer registration form

**Problem:** The endpoint input field in the producer registration form had `http://127.0.0.1:8000/signals` as placeholder — a dev artifact that looks unprofessional and confuses users.

**Solution:** Replaced with `/api/v1/producers/your-producer/signals` — a hint that shows the expected URL pattern without leaking internal dev details.

**Rationale:** Placeholders should guide, not confuse.

---

### Fix 5: Surface Seed Watchlist properly on Social page

**Problem:** When the watchlist is unseeded, a yellow alert banner told users to "POST to `/api/v1/social/seed`" — a developer instruction, not a user action. The Seed Watchlist button existed but wasn't prominent enough.

**Solution:** Replaced the dev-instruction alert with a clean empty-state CTA: centered layout with a plain-English explanation of what seeding does ("adds the default set of tokens so the pipeline knows what to track"), followed by a prominent green "🌱 Seed Watchlist" button.

**Rationale:** Users shouldn't need to know about API endpoints. One clear action, one clear explanation.

---

### Fix 6: Live market ticker in nav/header

**Problem:** No ambient market context. Users had to leave the dashboard to check prices.

**Solution:** Added `GET /api/market-ticker` route that fetches BTC/ETH/SOL prices from CoinGecko's free API, cached for 60 seconds. A small HTMX-powered ticker in the nav header shows `BTC $84,200 +2.1%` with green/red coloring for direction. Polls every 60s. Hidden on mobile to keep nav clean. JavaScript parses the JSON response client-side for proper formatting.

**Rationale:** Market context should be ambient, not a separate action. One line, monospace, unobtrusive.

---

### Fix 7: Fix Unix timestamp display on Identity page

**Problem:** "Forged at: 1740110218" — a raw Unix epoch that's meaningless to humans.

**Solution:** Applied `timeago` filter with `fmt_iso` tooltip. Now shows "5mo ago" with full date on hover.

**Rationale:** Same principle as Fix 2. Consistency across the dashboard.

---

### Fix 8: Urgency on Producer failures

**Problem:** When producers are failing, there's no visual urgency. Users might not notice degraded system state.

**Solution:** Added a red urgency banner that appears when ≥50% of producers are non-healthy: "⚠ X of Y producers failing — system degraded". Computed entirely in the Jinja2 template from existing `producers` data — no backend changes. Styled with `.producer-urgency-banner` class (red background, white text, centered).

**Rationale:** System degradation should scream, not whisper.

---

## Before Screenshots

See `docs/ux/sprint-1/before/` for pre-sprint screenshots:

| Page | File |
|------|------|
| Home/Brain | `home.jpg` |
| Cockpit | `cockpit.jpg` |
| Signals | `signals.jpg` |
| Producers | `producers.jpg` |
| Social | `social.jpg` |
| Artifacts | `artifacts.jpg` |
| Positions | `positions.jpg` |
| Performance | `performance.jpg` |
| Forecasts | `forecasts.jpg` |
| Karma | `karma.jpg` |
| Curator | `curator.jpg` |
| Identity | `identity.jpg` |
| Settings | `settings.jpg` |

## After Screenshots

After screenshots added post-merge.

---

## Design Principles

**Humans first.** Every change in this sprint translates machine data (Unix epochs, ISO strings, dev API paths) into human-readable information. The dashboard exists for operators, not for the machine.

**Ambient awareness.** The market ticker and producer urgency banner provide passive information without requiring active investigation. Good dashboards surface what matters without being asked.

**Consistency over novelty.** The `timeago` filter applies the same pattern everywhere — relative time with full precision on hover. One pattern, applied uniformly, beats six different timestamp formats.

**No new dependencies.** Everything was achieved with stdlib Python, existing Jinja2 templating, and vanilla JavaScript. The CoinGecko API is free and keyless. Complexity is the enemy of reliability.
