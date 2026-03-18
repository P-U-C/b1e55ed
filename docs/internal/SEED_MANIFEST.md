# SEED_MANIFEST.md — Reproducibility Proof

> Status: STUB — populated during Week 0 operator onboarding.

## What This Is

Cryptographic proof that the oracle's initial karma scores are reproducible
by anyone.  Clone the repo, run the commands below, verify you get the same
hashes.

No trust required.  The hash does not lie.

---

## Producers in Seed Dataset

| Producer | Type | Verifiable? | Notes |
|----------|------|-------------|-------|
| synthetic_momentum_v1 | Synthetic | ✓ | Deterministic from OHLCV |
| synthetic_mean_revert_v1 | Synthetic | ✓ | Deterministic from OHLCV |
| noise_generator_v1 | Adversarial | ✓ | Known-bad: random signals |
| lagging_indicator_v1 | Adversarial | ✓ | Known-bad: SMA(200) on 1h |
| external_btc_feed_v1 | External | ✓ | Public BTC data, b1e55ed doesn't control |

---

## Reproduce

```bash
git clone https://github.com/P-U-C/b1e55ed
cd b1e55ed && uv sync

# Run seed data generation
b1e55ed export karma --format jsonl --include-chain --output karma-seed-v1.jsonl

# Compare hash with SEED_MANIFEST_HASH below
sha256sum karma-seed-v1.jsonl
```

On macOS, replace `sha256sum` with `shasum -a 256`.

---

## SEED_MANIFEST_HASH

```
[populated at Week 0 — placeholder]
```

---

## Separation Chart

[Placeholder: good/bad producer karma divergence over epochs]

> At Week 0 completion, this will show:
> - `synthetic_momentum_v1` and `synthetic_mean_revert_v1` converging to karma > 0.7
> - `noise_generator_v1` staying near 0.5 (random walk)
> - `lagging_indicator_v1` drifting below 0.4

---

## Counterfactual

[Placeholder: "Following known-bad producers would have increased loss by X% over the seed period"]

---

## Adversarial Framing

The seed dataset **includes producers designed to fail**.

If the system cannot separate `noise_generator_v1` (random signals) from
`synthetic_momentum_v1` (deterministic, signal-rich), it has no business
serving provenance to anyone.

The adversarial producers are not an afterthought.  They are the primary
test.  Any system that scores a random signal generator above chance across
30+ signals has a defect in its scoring logic.

---

## Audit Trail

All seed events are written into the hash-chained event store.
Anyone with a copy of `karma-seed-v1.jsonl` can verify:

1. The event sequence matches the chain hashes in order.
2. The karma scores computed from those events match the oracle's current output.
3. No events were silently dropped or reordered.

This is the minimum bar for a provenance system worth trusting.
