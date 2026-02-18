# b1e55ed Dashboard — Design Specification v1.0

> Single document of truth for the dashboard UI/UX.
> Consolidates: BUILD_PLAN Phase 3, SDD CRT Aesthetic, BRAIN_DASHBOARD_DESIGN_PROMPT, DASHBOARD_OVERHAUL_PRD.
> Author: b1e55ed | Date: 2026-02-18

---

## 0. Design Principles

1. **Data density over decoration.** Every pixel shows information or provides affordance. No hero sections, no marketing copy, no empty space that "breathes."
2. **Glanceable hierarchy.** The operator should extract system state in <2 seconds from any page. Color, position, and size encode meaning before text does.
3. **Terminal aesthetic, not terminal usability.** CRT glow and scanlines set the mood. But the information architecture follows Bloomberg, not bash.
4. **Mobile is real.** zoz checks this on a phone. Every layout must degrade gracefully to a single column without losing critical information.
5. **No loading spinners.** HTMX partial swaps keep the shell visible. Stale data with age indicators beats blank panels.
6. **Actions are deliberate.** Anything that changes state (brain cycle, kill switch, trade action) requires a confirmation pattern. No accidental clicks.
7. **The brand filter applies.** Precise. Convicted. Structural. Dry. No exclamation marks. No crypto-twitter vernacular.

---

## 1. Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Server | FastAPI + Uvicorn | Async, SSE native, Python ecosystem |
| Templates | Jinja2 | Server-rendered, partial-friendly |
| Interactivity | HTMX 2.x | SPA-like UX, no JS framework |
| Real-time | SSE via `sse-starlette` | Unidirectional, HTMX-native |
| Styling | Tailwind CSS (CDN) + custom CSS | Utility-first + CRT overrides |
| Font | IBM Plex Mono (data), Inter (labels) | Monospace for numbers, clean sans for navigation |
| Icons | Lucide (CDN) | Lightweight, consistent |
| Charts | Sparkline via inline SVG | No charting library. Keep it light. |

**No build step.** CDN for Tailwind, HTMX, fonts, icons. Zero npm.

---

## 2. Design Tokens

```css
:root {
  /* Surface */
  --bg-primary:    #050505;        /* Near-black, not pure black */
  --bg-panel:      #0a0f0a;        /* Panel background — barely visible green tint */
  --bg-elevated:   #0f1a0f;        /* Hover states, active panels */
  --border-dim:    #1a2e1a;        /* Panel borders — dark green */
  --border-active: #2a4a2a;        /* Active/focused panel borders */

  /* Text */
  --text-primary:  #c8e6c8;        /* Main text — soft green, NOT full #00ff41 */
  --text-bright:   #00ff41;        /* Emphasis, numbers that matter */
  --text-dim:      #4a6a4a;        /* Secondary, labels, timestamps */
  --text-muted:    #2a3a2a;        /* Disabled, placeholder */

  /* Semantic */
  --color-bull:    #00ff41;        /* Green — profit, bullish, ok */
  --color-bear:    #ff3333;        /* Red — loss, bearish, danger */
  --color-warn:    #ffaa00;        /* Amber — caution, transition */
  --color-info:    #00ccff;        /* Cyan — informational, links */
  --color-neutral: #888888;        /* Gray — inactive, no signal */

  /* Regime-specific */
  --regime-risk-on:       #00ff41;
  --regime-euphoria:      #ffaa00;
  --regime-correction:    #ff6633;
  --regime-crisis:        #ff3333;
  --regime-choppy:        #888888;
  --regime-transition:    #00ccff;

  /* Effects */
  --glow-green:    0 0 8px rgba(0, 255, 65, 0.2);
  --glow-red:      0 0 8px rgba(255, 51, 51, 0.2);
  --glow-amber:    0 0 8px rgba(255, 170, 0, 0.2);

  /* Typography */
  --font-data:     'IBM Plex Mono', 'Courier New', monospace;
  --font-ui:       'Inter', -apple-system, sans-serif;
  --text-xs:       0.75rem;   /* 12px — timestamps, metadata */
  --text-sm:       0.8125rem; /* 13px — secondary data */
  --text-base:     0.875rem;  /* 14px — primary data */
  --text-lg:       1.125rem;  /* 18px — section headers */
  --text-xl:       1.5rem;    /* 24px — page-level numbers */
  --text-2xl:      2rem;      /* 32px — hero metrics */

  /* Spacing (4px base) */
  --sp-1: 0.25rem;
  --sp-2: 0.5rem;
  --sp-3: 0.75rem;
  --sp-4: 1rem;
  --sp-6: 1.5rem;
  --sp-8: 2rem;

  /* Border radius */
  --radius-sm: 2px;   /* Panels — barely rounded, not sharp */
  --radius-md: 4px;   /* Buttons, inputs */
}
```

### Scanline Overlay

Subtle. 3% opacity max. Must not interfere with readability on any device.

```css
body::after {
  content: '';
  position: fixed;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0, 0, 0, 0.03) 2px,
    rgba(0, 0, 0, 0.03) 4px
  );
  pointer-events: none;
  z-index: 9999;
}
```

### Text Glow

Applied sparingly. Only to `--text-bright` elements. Never to body text.

```css
.glow { text-shadow: var(--glow-green); }
```

---

## 3. Layout System

### Shell (all pages)

```
┌──────────────────────────────────────────────────┐
│  NAV BAR (fixed top, 48px)                       │
│  [logo] [brain] [positions] [signals] [config]   │
│                              [kill] [regime pill] │
├──────────────────────────────────────────────────┤
│                                                    │
│  PAGE CONTENT (scrollable)                         │
│  max-width: 1440px, centered                       │
│  padding: var(--sp-4)                              │
│                                                    │
│                                                    │
└──────────────────────────────────────────────────┘
```

**Nav bar details:**
- Left: `b1e55ed` wordmark (IBM Plex Mono, `--text-dim`, no logo image)
- Center: Page links (Brain, Positions, Signals, Social, Performance, System, Config)
- Right: Kill switch indicator (colored dot + level), regime pill (color-coded badge)
- Mobile: Hamburger menu, kill switch + regime always visible

### Panel Component

The fundamental building block. Every data group lives in a panel.

```
┌─ PANEL TITLE ──────────────── [refresh icon] ─┐
│                                                 │
│  Panel content                                  │
│                                                 │
│                                    updated 3m ─ │
└─────────────────────────────────────────────────┘
```

- Border: `1px solid var(--border-dim)`
- Background: `var(--bg-panel)`
- Title: `var(--font-ui)`, `var(--text-sm)`, `var(--text-dim)`, uppercase, letter-spacing 0.05em
- Content: `var(--font-data)`, `var(--text-base)`
- Staleness indicator: bottom-right, `var(--text-xs)`, `var(--text-dim)`
- When stale (>5min): staleness turns `var(--color-warn)`
- When very stale (>30min): border turns `var(--color-warn)`
- Refresh icon: top-right, triggers HTMX partial reload

### Grid

- Desktop (>1024px): CSS Grid, `repeat(auto-fit, minmax(380px, 1fr))`
- Tablet (768-1024): 2 columns
- Mobile (<768px): single column, panels stack vertically
- Gap: `var(--sp-4)`

---

## 4. Pages

### 4.1 Brain Overview (landing page: `/`)

The cockpit. Everything at a glance. No scrolling required on desktop.

```
┌──────────────────────────────────────────────────────────┐
│  REGIME BANNER (full width, 64px)                         │
│  ● RISK_ON_TREND — "Trending bullish" — Confidence: 72%  │
├────────────────────────┬─────────────────────────────────┤
│  POSITIONS (panel)     │  CONVICTION (panel)              │
│                        │                                  │
│  HL-001 HYPE LONG      │  BTC  ████████░░ 7.2  LONG     │
│  $30.63 (-1.6%)        │  HYPE ██████░░░░ 5.8  LONG     │
│  Entry $31.14          │  ETH  ███░░░░░░░ 2.9  NEUTRAL  │
│  Stop  $28.00 ⚠        │  SOL  █████░░░░░ 4.5  LONG     │
│  Target $36.00         │                                  │
│  P&L: -$51 (-1.6%)    │  Domain weights:                 │
│                        │  On-chain  ███████ 30%           │
│  [1 open / 0 pending]  │  TradFi    █████  23%           │
│                        │  Sentiment ████   19%            │
│                        │  Technical ██     10%            │
│                        │  Events    ██     10%            │
│                        │  Social    █       8%            │
├────────────────────────┴─────────────────────────────────┤
│  SIGNAL FEED (panel, live via SSE)                        │
│                                                           │
│  15:01  TA       BTC   RSI 24 oversold            ▼ 8.2  │
│  15:01  TradFi   BTC   Basis 2.4% unwound         → 3.1  │
│  15:01  Nansen   SOL   Smart money +$54K           ▲ 5.0  │
│  14:13  ACI      HYPE  Consensus +3.33 (high disp) → 4.0  │
│  09:01  Events   BTC   BlackRock ETH staking ETF   ▲ 6.0  │
│                                                           │
│  [showing 5 of 142 signals today]                         │
├───────────────────────────┬───────────────────────────────┤
│  QUICK ACTIONS (panel)    │  SYSTEM STATUS (panel)        │
│                           │                               │
│  [▶ Run Brain Cycle]      │  Last cycle: 3m ago ●         │
│  [⚠ Kill Switch: OFF]     │  Producers: 11/13 healthy     │
│  [↻ Force Price Check]    │  Events today: 142            │
│                           │  DB size: 24 MB               │
│                           │  Uptime: 4d 12h               │
│                           │  Karma pending: $2.40          │
└───────────────────────────┴───────────────────────────────┘
```

**Regime banner:**
- Full-width bar at top of page content (below nav)
- Background: regime color at 10% opacity
- Left border: 4px solid regime color
- Text: regime name + human-readable description + confidence %
- Pulses subtly on regime change (CSS animation, 2 cycles then stops)

**Positions panel:**
- Each position: symbol, direction, current price, entry, stop, target, P&L
- Price color: green if profitable, red if losing
- Stop proximity warning: if price within 5% of stop, amber background
- Clicking a position navigates to `/positions/{id}`

**Conviction panel:**
- Horizontal bar per asset, 0-10 scale
- Bar color: green (long), red (short), gray (neutral)
- Number at end of bar with direction label
- Domain weights below as smaller stacked bars

**Signal feed:**
- Live via SSE — new signals prepend with subtle slide-in animation
- Each row: timestamp, domain badge (colored pill), asset, description, direction arrow, strength score
- Strength score: number 0-10, color-coded (>7 green, 4-7 amber, <4 dim)
- Click any signal to expand and see full payload (HTMX swap)

**Quick actions:**
- Buttons use `--bg-elevated` background, `--border-active` border
- Kill switch button: red when active, shows current level
- Confirmation modal for kill switch toggle and brain cycle
- Brain cycle button shows spinner during execution (HTMX indicator)

**System status:**
- Key metrics as label: value pairs
- Green dot next to "Last cycle" if <10min, amber if 10-30min, red if >30min
- Producer count: "11/13 healthy" — clicking goes to `/system`

### 4.2 Positions (`/positions`)

Deep view of all positions — open, pending, and recently closed.

```
┌──────────────────────────────────────────────────────────┐
│  POSITIONS                            [open] [closed]     │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  ┌─ HL-001 · HYPE · LONG ────────────────────────────┐  │
│  │                                                     │  │
│  │  CURRENT    ENTRY     STOP      TARGET    P&L      │  │
│  │  $30.63     $31.14    $28.00    $36.00    -$51     │  │
│  │  (-1.6%)              (-10.1%)  (+15.6%)  (-1.6%)  │  │
│  │                                                     │  │
│  │  ──────────────────────────────────────────────     │  │
│  │  $28 ▎stop     $30.63 ▎now      $36 ▎target        │  │
│  │  ══════════════●═══════════════════════════         │  │
│  │                                                     │  │
│  │  Leverage: 10x ⚠ (max: 3x)                        │  │
│  │  Opened: 2026-02-14 · Held: 4d 6h                  │  │
│  │  Conviction at entry: 6.8 · Current: 5.2           │  │
│  │  Regime at entry: TRANSITION · Current: RISK_ON    │  │
│  │                                                     │  │
│  │  [Adjust Stop] [Adjust Target] [Close Position]    │  │
│  │  [Request Re-evaluation]                            │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  RECENTLY CLOSED                                          │
│  (none yet)                                               │
└──────────────────────────────────────────────────────────┘
```

**Price ladder:** Visual horizontal bar showing stop → current → target positioning. Current price is a marker on the bar. Green region (profit zone) to the right, red region (loss zone) to the left.

**Compliance warnings:** If leverage exceeds policy max, show amber warning inline.

**Actions:** Each button opens a confirmation panel (HTMX swap, not modal). "Close Position" requires typing the position ID to confirm.

### 4.3 Signals (`/signals`)

All signals grouped by domain with history.

```
┌──────────────────────────────────────────────────────────┐
│  SIGNALS                    [all] [ta] [tradfi] [onchain] │
│                             [social] [sentiment] [events] │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  LATEST BY DOMAIN                                         │
│                                                           │
│  ┌─ TECHNICAL ─────────────────────── 3m ago ──────────┐ │
│  │  BTC   RSI 24.1   EMA↓   BB lower   Vol 0.8x   ▼8  │ │
│  │  HYPE  RSI 52.6   EMA→   BB mid     Vol 1.2x   →4  │ │
│  │  ETH   RSI 31.2   EMA↓   BB lower   Vol 0.7x   ▼7  │ │
│  │  SOL   RSI 38.4   EMA↓   BB lower   Vol 0.9x   ▼6  │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─ TRADFI ────────────────────────── 3m ago ──────────┐ │
│  │  Basis: 2.4%/3.3% ann. (low)                        │ │
│  │  Funding: +1.9% ann. (bullish flip)                  │ │
│  │  Melt-up: 3/4 ███░                                   │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─ ON-CHAIN (NANSEN) ────────────── 6h ago ───────────┐ │
│  │  Smart money: USDC +$132K, SOL +$54K, KIMCHI +$21K  │ │
│  │  Net flow: accumulating                               │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  SIGNAL HISTORY (scrollable, filtered by domain tabs)     │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  15:01  BTC  RSI 24.1 oversold                 ▼ 8  │ │
│  │  14:01  BTC  RSI 26.3 oversold                 ▼ 7  │ │
│  │  13:01  BTC  RSI 28.8 approaching oversold     ▼ 6  │ │
│  │  ...                                                 │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

**Domain tabs:** Filter signal history by domain. "All" shows interleaved.

**Latest by domain:** One panel per active domain showing the most recent reading. Clicking expands to full event payload.

**Signal history:** Infinite scroll via HTMX (`hx-get` on scroll, append). Each row is clickable for detail.

### 4.4 Performance (`/performance`)

Track system accuracy and trading performance.

```
┌──────────────────────────────────────────────────────────┐
│  PERFORMANCE                                              │
├────────────────────────┬─────────────────────────────────┤
│  SUMMARY (panel)       │  BRAIN ACCURACY (panel)          │
│                        │                                  │
│  Total trades: 0       │  Predictions: 0                  │
│  Win rate: —           │  Correct: —                      │
│  Avg P&L: —            │  Accuracy: —                     │
│  Total P&L: $0         │                                  │
│  Sharpe: —             │  By domain:                      │
│  Max drawdown: —       │  (no data yet)                   │
│                        │                                  │
├────────────────────────┴─────────────────────────────────┤
│  TRADE LOG (panel)                                        │
│                                                           │
│  ID     Asset  Dir   Entry    Exit    P&L     Held       │
│  (no closed trades yet)                                   │
│                                                           │
├──────────────────────────────────────────────────────────┤
│  WEIGHT HISTORY (panel)                                   │
│                                                           │
│  Date        On-chain  TradFi  Sent.  Tech  Events Social│
│  2026-02-18  30%       23%     19%    10%   10%    8%    │
│  (initial weights — no adjustments yet)                   │
│                                                           │
├──────────────────────────────────────────────────────────┤
│  EXIT DISCIPLINE (panel)                                  │
│                                                           │
│  "Didn't sell" tax: tracks missed exits vs actual.        │
│  (no data yet — populates after first closed trade)       │
└──────────────────────────────────────────────────────────┘
```

**Empty states matter.** When there's no data, show clean empty states with one-line explanations. Never show broken layouts or "undefined."

### 4.5 System (`/system`)

Operational health. Replaces the old "commander" view.

```
┌──────────────────────────────────────────────────────────┐
│  SYSTEM                                                   │
├────────────────────────┬─────────────────────────────────┤
│  PRODUCERS (panel)     │  KILL SWITCH (panel)             │
│                        │                                  │
│  ta-indicators    ● OK │  Level: 0 (NORMAL)               │
│  orderbook-depth  ● OK │  ● ● ● ● ●                      │
│  price-alerts     ● OK │  0   1   2   3   4               │
│  tradfi-basis     ● OK │                                  │
│  etf-flows        ● OK │  Auto-escalate: ON               │
│  onchain-flows   ○ ERR │  Auto-de-escalate: OFF           │
│  stablecoin      ○ ERR │  Last change: never              │
│  whale-tracking  ○ ERR │                                  │
│  market-events    ● OK │  [Set Level ▼]                   │
│  market-sentiment ● OK │                                  │
│  social-buzz      ● OK │                                  │
│  curator-ingest   ● OK │                                  │
│  aci              ● OK │                                  │
│                        │                                  │
│  11/13 healthy         │                                  │
├────────────────────────┴─────────────────────────────────┤
│  EVENT STORE (panel)                                      │
│                                                           │
│  Total events: 1,247                                      │
│  Today: 142                                               │
│  By type: signal (128), brain (8), execution (4), sys (2) │
│  DB size: 24 MB                                           │
│  Hash chain: ✓ intact                                     │
│                                                           │
│  [Verify Hash Chain] [Export Events]                      │
├──────────────────────────────────────────────────────────┤
│  RESOURCES (panel)                                        │
│                                                           │
│  Disk: 31% ██████████████████████░░░░░░░░░░░░░░          │
│  API credits: Nansen 1,080/1,100 remaining                │
│  Allium: ⚠ 401 (subscription expired)                    │
│  Brave: ~1,800/2,000 remaining                            │
│  Uptime: 4d 12h 33m                                       │
└──────────────────────────────────────────────────────────┘
```

**Producer health:** Colored dot per producer. Green = OK, amber = degraded/stale, red = error. Click producer name to see last run details, error messages, staleness.

**Kill switch:** Visual 5-step indicator. Current level highlighted. Only allows setting level via dropdown + confirm. Shows escalation history.

### 4.6 Config (`/config`)

Read + write system configuration. This is a v1 requirement.

```
┌──────────────────────────────────────────────────────────┐
│  CONFIGURATION                       [preset ▼] [save]   │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  PRESET: balanced                     [load preset]       │
│  Available: conservative, balanced, degen                 │
│                                                           │
├──────────────────────────────────────────────────────────┤
│  RISK                                                     │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Max daily loss (USD)     [________1000]             │ │
│  │  Max position size (%)    [__________15]             │ │
│  │  Max leverage (default)   [___________5]             │ │
│  │  Max leverage (crisis)    [___________1]             │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  BRAIN                                                    │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Cycle interval (seconds) [________300]              │ │
│  │  Min conviction to trade  [_________65]  (0-100)     │ │
│  │  CTS auto-trigger (PCS)   [_________75]  (0-100)     │ │
│  │  Synthesis version         v2 (locked)               │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  EXECUTION                                                │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Mode                     [paper ▼]                  │ │
│  │  Confirmation threshold   [________500] USD          │ │
│  │  Circuit breaker (max/min)[____10] / [_____60]s      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  KARMA                                                    │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Enabled                  [✓]                        │ │
│  │  Percentage               [_______0.5] %             │ │
│  │  Settlement mode          [manual ▼]                 │ │
│  │  Treasury address         [0xPUC_TREASURY...]        │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  UNIVERSE                                                 │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Symbols: BTC, ETH, SOL, SUI, HYPE                  │ │
│  │  [+ Add symbol]                                      │ │
│  │  Max universe size        [________100]              │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  DASHBOARD                                                │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Host                     127.0.0.1 (locked)         │ │
│  │  Port                     [_______5051]              │ │
│  │  Auth token               [••••••••] [regenerate]    │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
│  ⚠ Unsaved changes                          [Save] [Reset]│
└──────────────────────────────────────────────────────────┘
```

**Behavior:**
- On load: reads `config/default.yaml` (or active config)
- Preset selector: loads preset values into form without saving
- Edit any field → "Unsaved changes" banner appears
- Save: validates via Pydantic model → writes to YAML → restarts affected components
- Locked fields (synthesis version, host) are visible but not editable
- Reset: reverts to last saved state
- Sensitive fields (auth token, treasury address) partially masked

**Validation:**
- Client-side: HTMX validates on blur (`hx-post="/config/validate"` returning error or ok)
- Server-side: full Pydantic validation before write
- Invalid values: red border + inline error message below field

### 4.7 Social (`/social`)

The social intelligence command center. Dedicated page because this is the fastest-evolving signal domain and the primary source of narrative-level alpha.

```
┌──────────────────────────────────────────────────────────┐
│  SOCIAL INTELLIGENCE                                      │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  PIPELINE STATUS (panel)                                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Pipeline: ● ACTIVE    Last run: 12m ago             │ │
│  │  LLM cost (MTD): $14.20 / $100 budget                │ │
│  │  Sources: Reddit ● | Farcaster ● | TikTok ○ |       │ │
│  │           Telegram ● | Polymarket ● | Trends ●       │ │
│  │  Kill switch: OFF    Error rate: 0.2%                 │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
├────────────────────────┬─────────────────────────────────┤
│  SENTIMENT MAP (panel) │  ALERTS (panel)                  │
│                        │                                  │
│  BTC   ████░░  +0.6    │  ⚠ ECHO CHAMBER                 │
│        bullish lean    │  $KIMCHI — 4 sources, same       │
│  HYPE  █████░  +0.8    │  narrative within 2h. Likely     │
│        bullish         │  coordinated. Fade signal.       │
│  ETH   ███░░░  -0.2    │                                  │
│        neutral/bear    │  ● VELOCITY SPIKE                │
│  SOL   ████░░  +0.5    │  $BUTTCOIN mentions 3x in 1h.   │
│        bullish lean    │  Early buzz, no on-chain         │
│  SUI   ███░░░  -0.1    │  confirmation yet.               │
│        neutral         │                                  │
│                        │  ● DIVERGENCE (bearish)          │
│  Method: LLM scored    │  $VIRTUAL — social buzz up 40%   │
│  Sources: 6 active     │  but on-chain flow flat.         │
│  Updated: 12m ago      │  Pump fake probability: high.    │
│                        │                                  │
├────────────────────────┴─────────────────────────────────┤
│  NARRATIVE TRACKER (panel)                                │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Rank  Narrative           Velocity  Stage    Age    │ │
│  │  1     AI agents           ████████  mature   47d    │ │
│  │  2     RWA / tokenization  ██████    growing  23d    │ │
│  │  3     BTC ETF staking     █████     early    3d     │ │
│  │  4     Solana memecoins    ████      fading   62d    │ │
│  │  5     L2 fee wars         ███       early    8d     │ │
│  │                                                      │ │
│  │  [Click narrative for deep view]                     │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                           │
├──────────────────────────────────────────────────────────┤
│  CURATOR FEED (panel, live via SSE)                       │
│                                                           │
│  Operator-submitted intel + auto-ingested signals.        │
│                                                           │
│  15:12  zoz    HYPE  "Hyperliquid team hinting at   ▲ 7  │
│                       new perp listings"                  │
│  14:30  auto   BTC   Reddit r/bitcoin sentiment     → 4  │
│                       neutral, volume declining           │
│  13:45  auto   SOL   Farcaster dev mentions up 22%  ▲ 5  │
│  12:00  zoz    ETH   "BlackRock staking ETF is      ▲ 8  │
│                       structural, not speculative"        │
│                                                           │
│  [Submit signal]  [View all]                              │
│                                                           │
├──────────────────────────────────────────────────────────┤
│  SOURCE HEALTH (panel)                                    │
│                                                           │
│  Source       Status  Last Hit  Signals/24h  Quality      │
│  Reddit      ● OK    12m       34           ████░ 0.72   │
│  Farcaster   ● OK    12m       18           ███░░ 0.65   │
│  TikTok      ○ DOWN  3d        0            —            │
│  Telegram    ● OK    45m       8            ████░ 0.70   │
│  Polymarket  ● OK    12m       12           █████ 0.81   │
│  Trends      ● OK    6h        4            ███░░ 0.58   │
│  Nitter/X    ○ DOWN  —         0            —            │
│                                                           │
│  Apify: ⚠ Monthly limit exceeded (resets in 12d)         │
└──────────────────────────────────────────────────────────┘
```

**Pipeline status:** Top-level health at a glance. Cost tracking matters — LLM-scored sentiment costs money per call. Show budget burn rate and kill switch state.

**Sentiment map:** Per-asset aggregated sentiment with direction and strength. Color-coded bars: green (bullish), red (bearish), gray (neutral). Score is -1 to +1. Updated on each pipeline run.

**Alerts panel:** The high-value output. Three alert types from the social intel pipeline:
- **Echo chamber:** Coordinated shilling detected (same narrative, multiple "independent" sources within short window). Action: fade.
- **Velocity spike:** Rapid mention acceleration on a token. Early signal, needs on-chain confirmation.
- **Divergence:** Social buzz diverging from on-chain reality. Bullish divergence (buzz + flow) = signal. Bearish divergence (buzz, no flow) = pump fake.

Alerts are color-coded by type and show actionable context, not just raw data.

**Narrative tracker:** Ranked list of active market narratives with velocity (rate of mention growth), lifecycle stage (early/growing/mature/fading), and age. Click to expand: key tokens in the narrative, related signals, first-seen date, peak date. This is where narrative rotation gets tracked.

**Curator feed:** Mixed feed of operator-submitted intel (`/signal` command) and auto-ingested signals. Operator signals get the `zoz` tag, auto signals get `auto`. Each has a conviction score. Live via SSE. "Submit signal" opens an inline form (HTMX swap) for quick intel submission without leaving the page.

**Source health:** Per-source operational status. Quality score (0-1) based on historical signal accuracy when available. Shows API limits and degradation notices (Apify, Nitter).

**SSE events for social page:**

| Event | Payload | UI Target |
|-------|---------|-----------|
| `social.alert` | Echo chamber/velocity/divergence | Alerts panel (prepend) |
| `social.sentiment` | Updated sentiment map | Sentiment map (replace) |
| `social.curator` | New curator signal | Curator feed (prepend) |
| `social.narrative` | Narrative rank change | Narrative tracker (replace) |

**Mobile:** On mobile, stack in this order: Pipeline status (compressed), Alerts (always visible — this is the action), Sentiment map, Curator feed (collapsed), Narrative tracker (collapsed), Source health (collapsed).

---

### 4.8 Treasury (`/treasury`)

Karma tracking and settlement.

```
┌──────────────────────────────────────────────────────────┐
│  KARMA TREASURY                                           │
├────────────────────────┬─────────────────────────────────┤
│  TOTALS (panel)        │  SETTINGS (panel)                │
│                        │                                  │
│  Lifetime earned: $0   │  Rate: 0.5% of profit            │
│  Pending: $0           │  Mode: manual                    │
│  Settled: $0           │  Threshold: $50                  │
│  Receipts: 0           │  Treasury: 0xPUC...              │
│                        │                                  │
├────────────────────────┴─────────────────────────────────┤
│  PENDING INTENTS (panel)                                  │
│                                                           │
│  (no pending karma intents)                               │
│                                                           │
│  [Settle All]  (disabled when nothing pending)            │
├──────────────────────────────────────────────────────────┤
│  RECEIPT HISTORY (panel)                                  │
│                                                           │
│  Date    Trades  Amount   Status     Tx                   │
│  (no settlements yet)                                     │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

---

## 5. Interaction Patterns

### 5.1 HTMX Partial Updates

Every panel refreshes independently. No full page reloads after initial load.

```html
<!-- Auto-refresh panel every 30s -->
<div id="positions-panel"
     hx-get="/partials/positions"
     hx-trigger="every 30s"
     hx-swap="innerHTML">
  {% include 'partials/positions.html' %}
</div>

<!-- SSE-driven signal feed -->
<div id="signal-feed"
     hx-ext="sse"
     sse-connect="/stream"
     sse-swap="signal"
     hx-swap="afterbegin">
</div>

<!-- Action with confirmation -->
<button hx-post="/api/brain/run"
        hx-confirm="Run brain cycle now?"
        hx-target="#cycle-result"
        hx-indicator="#cycle-spinner">
  ▶ Run Brain Cycle
</button>
```

### 5.2 Refresh Intervals

| Panel | Interval | Method |
|-------|----------|--------|
| Regime banner | 30s | HTMX poll |
| Positions | 30s | HTMX poll |
| Conviction | 60s | HTMX poll |
| Signal feed | Real-time | SSE |
| System status | 60s | HTMX poll |
| Producer health | 60s | HTMX poll |
| Config | Manual | On load only |

### 5.3 Confirmation Patterns

**Dangerous actions** (kill switch, close position, settlement):
- Inline confirmation panel replaces the button
- Shows action summary + consequences
- Requires explicit click on "Confirm" or "Cancel"
- Position close requires typing position ID

**Normal actions** (brain cycle, force price check):
- `hx-confirm` browser dialog is sufficient

### 5.4 Empty States

Every panel has a designed empty state:

| Panel | Empty State Text |
|-------|-----------------|
| Positions | "No open positions. Brain decisions will appear here." |
| Signals | "No signals yet. Waiting for first producer cycle." |
| Trade log | "No closed trades. Performance data populates after first exit." |
| Karma | "No karma intents. Profitable trade closes generate intents." |
| Weight history | "Initial weights active. Adjustments begin after 30 days (cold start)." |

### 5.5 Error States

- API errors: panel shows amber border + "Failed to load. Retrying..." + auto-retry in 10s
- SSE disconnect: signal feed shows "⚠ Connection lost. Reconnecting..." banner
- Validation errors: red border + message below field, clear on fix

---

## 6. Mobile Layout

### Breakpoints

| Name | Width | Columns |
|------|-------|---------|
| Mobile | <768px | 1 |
| Tablet | 768-1024px | 2 |
| Desktop | >1024px | 2-3 (page-dependent) |

### Mobile Priorities

On mobile, the Brain Overview page reorders panels by priority:

1. **Regime banner** (always visible, compressed to single line)
2. **Positions** (full width, scrollable if multiple)
3. **Quick actions** (sticky bottom bar with 3 key buttons)
4. **Conviction** (collapsed by default, tap to expand)
5. **Signal feed** (collapsed by default, tap to expand)
6. **System status** (collapsed by default)

### Mobile Nav

- Hamburger menu (top left)
- Kill switch dot + regime pill always visible in nav bar
- Active page highlighted

---

## 7. SSE Event Types

The `/stream` endpoint emits these SSE event types:

| Event | Payload | UI Target |
|-------|---------|-----------|
| `signal` | Signal event envelope | Signal feed (prepend) |
| `regime` | New regime state | Regime banner (replace) |
| `conviction` | Updated scores | Conviction panel (replace) |
| `position` | Position update | Positions panel (replace) |
| `kill_switch` | Level change | Kill switch indicator + nav dot |
| `cycle` | Brain cycle complete | System status "last cycle" |
| `karma` | New intent | Treasury pending count |

---

## 8. Authentication

- Bearer token stored as `HttpOnly` cookie
- Login page: single input field for token, no username
- Token generated during `b1e55ed setup`
- All routes except `/login` and `/health` require auth
- API routes accept `Authorization: Bearer <token>` header (for programmatic access)
- Dashboard routes check cookie

---

## 9. API Endpoints (Dashboard Backend)

These serve both the dashboard (HTML partials) and external consumers (JSON).

| Method | Path | Response | Auth |
|--------|------|----------|------|
| GET | `/health` | JSON: version, uptime, db_size | No |
| GET | `/` | HTML: Brain Overview | Yes |
| GET | `/positions` | HTML: Positions page | Yes |
| GET | `/positions/{id}` | HTML: Position detail | Yes |
| GET | `/signals` | HTML: Signals page | Yes |
| GET | `/performance` | HTML: Performance page | Yes |
| GET | `/system` | HTML: System page | Yes |
| GET | `/config` | HTML: Config page | Yes |
| GET | `/social` | HTML: Social Intelligence page | Yes |
| GET | `/treasury` | HTML: Treasury page | Yes |
| GET | `/login` | HTML: Login form | No |
| POST | `/login` | Set cookie, redirect | No |
| GET | `/stream` | SSE stream | Yes |
| GET | `/partials/{name}` | HTML fragment | Yes |
| POST | `/api/brain/run` | JSON: cycle result | Yes |
| POST | `/api/kill-switch` | JSON: new level | Yes |
| POST | `/api/positions/{id}/close` | JSON: close result | Yes |
| GET | `/api/config` | JSON: current config | Yes |
| POST | `/api/config` | JSON: validate + save | Yes |
| POST | `/api/config/validate` | JSON: validation result | Yes |
| GET | `/api/producers/status` | JSON: producer health | Yes |
| GET | `/api/signals` | JSON: signal list | Yes |
| GET | `/api/events` | JSON: event query | Yes |
| GET | `/api/karma/intents` | JSON: pending intents | Yes |
| POST | `/api/karma/settle` | JSON: settlement result | Yes |
| GET | `/api/karma/receipts` | JSON: receipt history | Yes |
| GET | `/api/social/sentiment` | JSON: per-asset sentiment | Yes |
| GET | `/api/social/alerts` | JSON: active social alerts | Yes |
| GET | `/api/social/narratives` | JSON: narrative rankings | Yes |
| GET | `/api/social/sources` | JSON: source health | Yes |
| POST | `/api/social/signal` | JSON: submit curator signal | Yes |

---

## 10. File Structure

```
dashboard/
├── __init__.py
├── app.py                    # FastAPI app, middleware, CORS, lifespan
├── auth.py                   # Token auth, cookie management
├── deps.py                   # Dependency injection (config, db, brain)
├── routes/
│   ├── __init__.py
│   ├── pages.py              # All HTML page routes
│   ├── partials.py           # HTMX partial fragment routes
│   ├── api.py                # JSON API routes (brain, config, karma)
│   └── stream.py             # SSE endpoint
├── services/
│   ├── __init__.py
│   ├── brain_service.py      # Read brain state, trigger cycles
│   ├── position_service.py   # Position queries
│   ├── signal_service.py     # Signal aggregation
│   ├── config_service.py     # Config read/write/validate
│   ├── karma_service.py      # Karma queries, settlement
│   └── social_service.py     # Social pipeline state, sentiment, narratives
├── templates/
│   ├── base.html             # Shell: nav, head, scripts
│   ├── login.html            # Token entry
│   ├── brain.html            # Brain Overview
│   ├── positions.html        # Position Command Center
│   ├── position_detail.html  # Single position deep view
│   ├── signals.html          # Signal Dashboard
│   ├── performance.html      # Performance & Learning
│   ├── system.html           # System Health
│   ├── config.html           # Configuration editor
│   ├── social.html           # Social Intelligence
│   ├── treasury.html         # Karma Treasury
│   └── partials/
│       ├── regime_banner.html
│       ├── positions_panel.html
│       ├── conviction_panel.html
│       ├── signal_feed.html
│       ├── signal_row.html
│       ├── system_status.html
│       ├── producer_row.html
│       ├── position_card.html
│       ├── quick_actions.html
│       ├── config_section.html
│       ├── sentiment_map.html
│       ├── social_alert.html
│       ├── narrative_row.html
│       └── curator_signal.html
└── static/
    ├── style.css             # CRT aesthetic + custom overrides
    └── app.js                # SSE connection, minimal interactivity
```

---

## 11. What Ships in v1 vs Later

### v1 (Phase 3)

| Feature | Status |
|---------|--------|
| Brain Overview (all panels) | Ship |
| Positions page + detail | Ship |
| Signals page + filtering | Ship |
| System page (producers, kill switch, events, resources) | Ship |
| Social Intelligence page | Ship |
| Config page (read + write) | Ship |
| Treasury page | Ship |
| SSE real-time signal feed | Ship |
| HTMX partial refresh (all panels) | Ship |
| Auth (bearer token cookie) | Ship |
| Mobile responsive | Ship |
| CRT aesthetic | Ship |
| Empty states for all panels | Ship |

### v2 (Phase 4 / Post-Launch)

| Feature | Notes |
|---------|-------|
| Brain visualization (neural pathways) | The "Matrix brain" from the design prompt. Ambitious. Needs SVG + animation work. |
| Performance charts (sparklines, P&L curve) | Inline SVG sparklines. Requires trade history first. |
| Position price charts | Mini candlestick or line charts per position |
| Alpha stream (reasoning feed) | Terminal-style brain reasoning log |
| Notification preferences | Configure alert routing in dashboard |
| Dark/light theme toggle | Dark is default and primary. Light is an option. |
| Keyboard shortcuts | Power user feature |
| Export (CSV, JSON) | Event and trade data export |

### Explicitly NOT building

| Feature | Reason |
|---------|--------|
| Multi-user auth | Single operator system |
| Real-time charts (TradingView etc.) | Use external tools. Dashboard is for system state. |
| Mobile app | Web is sufficient |
| Public access mode | Tailscale/tunnel only |

---

## 12. Easter Eggs

Per EASTER_EGG_REFERENCE.md, the dashboard includes subtle references:

- **404 page:** "Block not found. Like MtGox withdrawals."
- **Login page footer:** "Hashcash predates Bitcoin (1997)."
- **Empty trade log:** "No trades yet. Patience is a position."
- **Hash chain verified:** "Genesis to tip. Immutable."
- **Kill switch level 4 banner:** "LOCKDOWN — The system has opinions about your risk tolerance."
- **First brain cycle ever:** "Running Bitcoin." (Hal Finney reference)

All pass the brand filter: timeless, conviction over consensus, builders over tourists. No crypto-twitter vernacular.

---

## 13. Implementation Order

Build in this sequence to get something visible fast, then layer quality:

1. **Shell** — `base.html` with nav, auth, design tokens, Tailwind/HTMX CDN imports
2. **Brain Overview** — Landing page with static mock data in all panels
3. **Services** — Wire services to real DB/config (panels go live)
4. **SSE** — Signal feed goes real-time
5. **Positions** — Full page with detail view
6. **Signals** — Full page with domain filtering
7. **System** — Producers, kill switch, events, resources
8. **Social** — Pipeline status, sentiment, alerts, narratives, curator feed, source health
9. **Config** — Read + write + validation + presets
10. **Treasury** — Karma view
11. **Performance** — Last (needs trade data to be meaningful)
12. **Mobile polish** — Responsive tweaks after all pages work
13. **Easter eggs** — Last touch

Each step is visually reviewable before moving to the next.

---

*"The dashboard is the Brain's face. Make it worthy."*
