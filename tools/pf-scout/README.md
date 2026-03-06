# pf-scout 🔍

**Post Fiat network intelligence — discover contributors, build contacts, find mentors, recruit producers.**

A CLI tool for Post Fiat participants who want to find the right people in the network. Whether you're recruiting producers for your node, looking for mentors, or just want to see who's active and aligned — `pf-scout` gives you a scored, filterable view of the contributor pool.

---

## Install

```bash
cd pf-scout
pip install -e .
```

## Quick Start

```bash
# 1. Configure your JWT token
pf-scout setup

# 2. See who's in the network
pf-scout network summary

# 3. Discover top prospects
pf-scout network discover

# 4. See your contacts enriched with leaderboard data
pf-scout network contacts
```

---

## Getting Your JWT Token

You need a JWT token from **tasknode.postfiat.org** to use the network commands.

1. Go to [tasknode.postfiat.org](https://tasknode.postfiat.org) and log in (GitHub OAuth)
2. Open browser DevTools (`F12` or `Cmd+Opt+I`)
3. Go to the **Network** tab
4. Click any page or action that triggers an API call
5. Find a request to `/api/...` and click it
6. In the **Headers** section, find `Authorization: Bearer <your-token>`
7. Copy everything after `Bearer `

You can either:
- Run `pf-scout setup` and paste the token (saved to `~/.pf-scout/config.json`)
- Set `PF_JWT_TOKEN` environment variable

---

## Commands

### `pf-scout setup`

Interactive wizard. Prompts for your JWT token, validates it against the API, saves to `~/.pf-scout/config.json`.

### `pf-scout network summary`

Network overview: active contributors, total PFT output, top by volume, top by alignment.

### `pf-scout network top`

Quick top-10 leaderboard view.

```bash
pf-scout network top                    # Top 10 by monthly score
pf-scout network top --by alignment     # Top 10 by alignment
pf-scout network top --by volume        # Top 10 by PFT volume
pf-scout network top --count 20         # Top 20
```

### `pf-scout network discover`

Full prospect discovery with rubric scoring.

```bash
pf-scout network discover                          # Default: min alignment 60
pf-scout network discover --min-alignment 70        # Higher alignment filter
pf-scout network discover --domain "blockchain"     # Filter by capability keyword
pf-scout network discover --rubric my-rubric.yaml   # Custom rubric
pf-scout network discover --output prospects.md     # Save to file
```

### `pf-scout network contacts`

Your contact list enriched with leaderboard data (alignment, sybil, PFT output).

### `pf-scout score`

Score prospects from a manual CSV file against a rubric.

```bash
pf-scout score --input prospects.csv --rubric rubrics/b1e55ed.yaml --output report.md
```

### `pf-scout report`

Generate the full b1e55ed prospect report from CSV input.

```bash
pf-scout report --input examples/b1e55ed-prospects-input.csv
```

---

## Use Cases

| Goal | Command |
|------|---------|
| Find high-alignment contributors to network with | `pf-scout network discover --min-alignment 80` |
| See who's producing the most output | `pf-scout network top --by volume` |
| Find mentors with specific expertise | `pf-scout network discover --domain "quantitative"` |
| Review your existing contacts with fresh data | `pf-scout network contacts` |
| Recruit producers for your node | `pf-scout network discover --rubric my-node-rubric.yaml` |
| Quick network health check | `pf-scout network summary` |

---

## Rubric Customization

Rubrics are YAML files with weighted scoring dimensions. See `rubrics/b1e55ed.yaml` for the default.

```yaml
name: My Node Rubric
dimensions:
  - id: skill_x
    name: Skill X
    weight: 1.5
    description: What you're looking for
    score_guide:
      5: Expert level
      1: No background
```

---

## Auth

Two ways to authenticate:

1. **`pf-scout setup`** — saves token to `~/.pf-scout/config.json`
2. **Environment variable** — `export PF_JWT_TOKEN="your-token"`

Environment variable takes priority over saved config.
