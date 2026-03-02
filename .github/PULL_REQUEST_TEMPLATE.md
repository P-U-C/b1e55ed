## Summary

<!-- One sentence: what does this PR do and why? -->

Closes #<!-- issue number -->

---

## Type of change

<!-- Check all that apply -->

- [ ] `feat` — new feature
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `refactor` — no behaviour change
- [ ] `test` — tests only
- [ ] `chore` — tooling, deps, config

---

## Labels

> **Required before requesting review.** Apply via the Labels panel on the right.

| Label | When to apply |
|-------|---------------|
| `feat` | New capability |
| `fix` | Bug fix |
| `docs` | Docs-only change |
| `producer` | Touches `engine/producers/` |
| `brain` | Touches `engine/brain/` |
| `flywheel` | Touches attribution, stratification, or paper trading |
| `mcp` | Touches MCP layer |
| `events` | Events domain producer |
| `backlog` | Not yet scheduled for a sprint |
| `roadmap` | Part of phased producer roadmap |

- [ ] Labels applied ✅

---

## Changes

<!-- Bullet list of what changed. Be specific about files. -->

-

---

## Tests

- [ ] New tests added (or explain why not needed)
- [ ] All existing tests pass: `.venv/bin/python -m pytest --tb=short -q`
- [ ] Test count: `___` passing

---

## Checklist

- [ ] Branch targets the correct base (`develop` for features; `feat/mcp` for MCP-dependent work)
- [ ] `docs/dependencies-docs.md` updated if new file dependencies introduced
- [ ] No secrets or credentials in committed code
- [ ] `engine/brain/orchestrator.py` **not modified** (parallel emission only)
