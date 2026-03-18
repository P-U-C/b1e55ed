# Dashboard UX Sprint 3 — Operator Control Surface

**Theme**: Transform the dashboard from a read-only monitoring view into an interactive control surface.

**PR**: feat/dashboard-sprint-3  
**Spec**: All interactions are HTMX — no page reloads, no modals, no external JS libraries.

---

## Features Delivered

### 1. Settings Page (`/settings`)

**Before**: No settings UI. Operators needed SSH + YAML editing to change trading mode or risk limits.

**After**: Dedicated settings page with:
- Trading mode toggle — Paper / Live with red warning banner in live mode
- Inline-editable risk limits (max daily loss, max position size, max leverage) — per-field HTMX save
- API key status table — shows configured/not set for all keys, never exposes values
- Danger zone — reset defaults and clear signal history with confirmation

### 2. Artifact Preview Pane (`/artifacts`)

**Before**: Table with a dead "Link" column pointing to raw API URLs.

**After**: 
- Each artifact row is clickable (`hx-get="/partials/artifact-preview/{id}"`)
- Inline preview expands below the table — text/markdown in `<pre>`, JSON formatted
- Close button collapses the pane without page reload

### 3. Position Management UI (`/positions`)

**Before**: "Adjust Stop" and "Adjust Target" buttons triggered `window.confirm()` dialogs — unusable on mobile, no precision input.

**After**:
- Inline edit forms appear on button click — number input with current value pre-filled
- Set / Cancel buttons, HTMX POST to `adjust-stop` / `adjust-target`
- Inline confirmation response replaces the form on success

### 4. Producer Restart / Retry (`/producers`)

**Before**: Producer cards showed failure state with no recovery path from the UI.

**After**:
- Every card has a **Restart** button — `POST /api/producers/{name}/restart`
- Failing cards additionally show **Clear Failures** — `POST /api/producers/{name}/reset-failures`
- Buttons swap to inline status text (green/red) on response

### 5. Forecasts Page (`/forecasts`)

**Before**: `/forecasts` was a 404.

**After**: Full calibration view:
- Summary stats bar: Total / Pending / Resolved / Mean Brier score
- Filter controls: asset (BTC/ETH/SOL/All), horizon (24h/7d/All), status (pending/resolved/all)
- Forecast log table: color-coded direction (bull/bear/neutral), Brier score heat (green <0.25, amber <0.5, red ≥0.5), status badges
- Per-producer breakdown cards: forecast count, accuracy rate, mean Brier
- HTMX poll: `hx-trigger="every 60s"` on the table partial
- Nav link added

---

## Test Coverage

12 unit tests passing (4 new for sprint-3 features):
- `test_settings_page`
- `test_artifact_preview_partial`
- `test_forecasts_page`
- `test_forecasts_partial`

## Files Changed

| File | Change |
|------|--------|
| `dashboard/app.py` | `/settings`, `/forecasts`, `/partials/artifact-preview/{id}`, `/partials/forecasts-table`, restart/reset-failures API endpoints |
| `dashboard/templates/settings.html` | New — settings page |
| `dashboard/templates/forecasts.html` | New — forecasts page |
| `dashboard/templates/partials/artifact_preview.html` | New — preview partial |
| `dashboard/templates/partials/forecasts_table_inner.html` | New — HTMX table partial |
| `dashboard/templates/artifacts.html` | Clickable rows, preview pane div |
| `dashboard/templates/positions.html` | Inline edit forms replacing confirm dialogs |
| `dashboard/templates/producers.html` | Restart / Clear Failures buttons per card |
| `dashboard/templates/base.html` | Forecasts + Settings nav links |

