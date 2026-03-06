#!/usr/bin/env python3
"""Generate the b1e55ed prospect list report from the input CSV."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from pf_scout.collectors.manual import load_csv
from pf_scout.output.markdown import generate_report
from pf_scout.scoring.scorer import load_rubric, score_all

# Recruitment angles for top-tier prospects (manually authored)
RECRUITMENT_ANGLES: dict[str, str] = {
    "allenday": (
        "Allen Day's Google Cloud career was spent building exactly what b1e55ed needs at the data layer: "
        "scalable on-chain ETL pipelines that turn raw blockchain state into queryable, analysis-ready datasets. "
        "His BigQuery public datasets for BTC/ETH/XRP/LTC represent the same class of work as a b1e55ed "
        "signal producer — turning chain data into systematic inputs for analysis. "
        "**Role fit**: on-chain data producer + infrastructure reviewer. "
        "**Value prop**: b1e55ed gives him a live forecast platform where his on-chain pipelines become "
        "attributable, scored signal rather than free public infrastructure."
    ),
    "Citrini7": (
        "Citrini is one of the most rigorous public macro analysts in crypto — cross-asset, rate-vol aware, "
        "and already plugged into the PF ecosystem as a named backer. "
        "His analytical framework (inflation → rates → risk assets → crypto flows) maps directly to the "
        "kind of structured confidence-stamped forecasts that b1e55ed's scoring engine rewards over narrative output. "
        "**Role fit**: macro market signal producer, top-tier reviewer. "
        "**Value prop**: b1e55ed converts his public alpha into an auditable track record with cryptographic provenance — "
        "the kind of proof that institutional allocators and PF's AGTI node need before weighting a signal."
    ),
    "goodalexander": (
        "Alex Good built the protocol and has the deepest understanding of what the network rewards. "
        "His trading and writing background (ibpandas, AGTI node, years of market commentary at postfiat.org) "
        "makes him a natural mechanism reviewer who can stress-test b1e55ed's rubric and scoring design. "
        "**Role fit**: mechanism reviewer, architect advisor, meta-producer gate validator. "
        "**Value prop**: b1e55ed is the attribution primitive he described theoretically in the AGTI node design — "
        "a chance to see proof-of-foresight demonstrated in production on his own network before the oracle launches."
    ),
    "asmodeoux": (
        "Yuri Goncharenko is already full-time Post Fiat (listed company: Post Fiat). "
        "Building the MCP chatbot integration means he understands the platform's API surface better than "
        "almost any other contributor. "
        "**Role fit**: infrastructure contributor, API integration specialist for b1e55ed's producer onboarding. "
        "**Value prop**: b1e55ed's producer API needs someone who can build the ingestion tooling that other "
        "contributors use to submit signals — this is the MCP-adjacent problem he's already solving."
    ),
    "DRavlic": (
        "Domagoj Ravlić has committed to more postfiatorg repositories than any other contributor — "
        "from the rippled fork to the validator history service to the explorer. "
        "He is the backbone of PF's infrastructure layer. "
        "**Role fit**: infrastructure contributor, validator operator liaison, node reliability specialist. "
        "**Value prop**: b1e55ed's producer nodes need operators who can run reliable production infrastructure "
        "— the same guarantee that validator-history-service and postfiatd require. This is his native domain."
    ),
    "Travis": (
        "Travis Good (goodalexander's brother) is building Ambient, a Bitcoin fork targeting the hardware macro "
        "thesis — a technically ambitious project in the same epistemic orbit as Post Fiat. "
        "His background bridges protocol-level consensus design with the same crypto/AI worldview that b1e55ed is built on. "
        "**Role fit**: mechanism reviewer, macro signal producer focused on BTC/monetary system forecasts. "
        "**Value prop**: b1e55ed gives him an independent attribution layer for his BTC theses — "
        "a way to build a verifiable track record separate from Ambient that compounds regardless of Ambient's outcomes."
    ),
    "based16z": (
        "based16z is an early PF backer with DeFi operational and VC-adjacent background, "
        "giving them exposure to both the capital allocation side (what signals matter) and the infrastructure side "
        "(what it takes to run production systems). "
        "**Role fit**: market signal producer, DeFi/on-chain data producer, network connector to technical contributors. "
        "**Value prop**: b1e55ed's karma system converts their existing DeFi alpha into a cryptographically attributed "
        "track record — the kind of proof that PF's AGTI node and institutional allocators actually need."
    ),
}


def main():
    prospects = load_csv("examples/b1e55ed-prospects-input.csv")
    rubric = load_rubric("rubrics/b1e55ed.yaml")
    scored = score_all(prospects, rubric)

    # Attach recruitment angles
    for p in scored:
        if p.handle in RECRUITMENT_ANGLES:
            p.recruitment_angle = RECRUITMENT_ANGLES[p.handle]

    # Print summary
    print("=== SCORED PROSPECTS ===")
    for p in scored:
        print(f"{p.tier:20s} {p.handle:30s} raw={p.total_score:2d} weighted={p.weighted_score:.1f}")

    # Generate markdown
    md = generate_report(scored, rubric, title="b1e55ed Producer Recruitment — Scored Prospect List")

    with open("b1e55ed-prospect-list.md", "w") as f:
        f.write(md)
    print(f"\nReport written to b1e55ed-prospect-list.md ({len(md)} chars)")

    return md


if __name__ == "__main__":
    main()
