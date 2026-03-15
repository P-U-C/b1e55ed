"""tests.mocks.scenarios — One scenario definition per file.

Each scenario module exports a dict (or dataclass) with:
  - asset: str
  - price_series: list[float]
  - signal_inputs: dict
  - expected_outcome: dict
"""
