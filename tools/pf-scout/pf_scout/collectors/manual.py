"""Manual CSV/JSON collector — load prospects from a file."""

import contextlib
import csv
import json

from .base import Prospect


def load_csv(path: str) -> list[Prospect]:
    """
    Load prospects from a CSV file.

    Required columns: handle
    Optional: display_name, source, notes, github_bio, github_company,
              postfiat_task_count, postfiat_pft_earned, twitter_followers,
              manual_quant_depth, manual_infra_capability, manual_market_analysis,
              manual_signal_generation, manual_engagement_consistency

    Columns prefixed with `manual_` are used as dimension score overrides.
    """
    prospects = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            manual_scores = {}
            for key, val in row.items():
                if key.startswith("manual_") and val.strip():
                    dim_id = key[len("manual_") :]
                    with contextlib.suppress(ValueError):
                        manual_scores[dim_id] = float(val)

            p = Prospect(
                handle=row.get("handle", "unknown"),
                display_name=row.get("display_name") or None,
                source=row.get("source", "manual"),
                github_bio=row.get("github_bio", ""),
                github_company=row.get("github_company", ""),
                github_location=row.get("github_location", ""),
                postfiat_task_count=int(row.get("postfiat_task_count", 0) or 0),
                postfiat_pft_earned=float(row.get("postfiat_pft_earned", 0) or 0),
                twitter_followers=int(row.get("twitter_followers", 0) or 0),
                notes=row.get("notes", ""),
                manual_scores=manual_scores,
            )
            if row.get("postfiat_capabilities"):
                p.postfiat_capabilities = [c.strip() for c in row["postfiat_capabilities"].split(";")]
            prospects.append(p)
    return prospects


def load_json(path: str) -> list[Prospect]:
    """Load prospects from a JSON array."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    prospects = []
    for item in data:
        manual_scores = item.pop("manual_scores", {})
        p = Prospect(**{k: v for k, v in item.items() if hasattr(Prospect, k)})
        p.manual_scores = manual_scores
        prospects.append(p)
    return prospects
