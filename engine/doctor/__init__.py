"""engine.doctor

Diagnostic tiers for b1e55ed health verification.

Tier 0 — Preflight: Python version, deps, config, DB path, identity, kill switch.
Tier 1 — Components: producer instantiation, orchestrator load, OMS, dashboard.
Tier 2 — Pipeline smoke: synthetic signal ingestion, brain cycle, outcome resolution.
"""
