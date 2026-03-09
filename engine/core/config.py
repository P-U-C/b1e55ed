"""engine.core.config

Three config surfaces only:
1) `config/default.yaml` + `config/presets/*.yaml`
2) Environment variables (secrets only)
3) `data/learned_weights.yaml` (optional overlay)

Everything else is derived.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings

from engine.core.exceptions import ConfigError
from engine.core.paths import data_dir as _data_dir
from engine.core.paths import get_db_path as get_db_path  # re-exported: single DB path authority

__all__ = ["get_db_path"]


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class DomainWeights(BaseModel):
    """Synthesis domain weights. Must sum to 1.0 (±0.001)."""

    curator: float = 0.25
    onchain: float = 0.25
    tradfi: float = 0.20
    social: float = 0.15
    technical: float = 0.10
    events: float = 0.05

    @field_validator("events", mode="after")
    @classmethod
    def weights_must_sum_to_one(cls, v: float, info) -> float:
        # info.data contains previously validated fields; v is the current field's value
        prior = ["curator", "onchain", "tradfi", "social", "technical"]
        total = sum(float(info.data.get(f, 0.0)) for f in prior) + v
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Domain weights must sum to 1.0, got {total}")
        return v


class RiskConfig(BaseModel):
    max_leverage: float = 2.0
    max_position_pct: float = 0.10
    max_portfolio_heat_pct: float = 0.06
    daily_loss_limit_pct: float = 0.03
    max_drawdown_pct: float = 0.30
    portfolio_value_usd: float = 10000.0
    max_open_risk_pct: float = 0.05
    max_single_loss_pct: float = 0.02

    @field_validator("max_leverage")
    @classmethod
    def max_leverage_positive(cls, v: float) -> float:
        if v < 1.0:
            raise ValueError(f"max_leverage must be >= 1.0, got {v}")
        return v

    @field_validator("max_position_pct")
    @classmethod
    def max_position_pct_valid(cls, v: float) -> float:
        if not 0 < v <= 1.0:
            raise ValueError(f"max_position_pct must be between 0 and 1.0, got {v}")
        return v

    @field_validator("daily_loss_limit_pct")
    @classmethod
    def daily_loss_limit_pct_valid(cls, v: float) -> float:
        if not 0 < v <= 1.0:
            raise ValueError(f"daily_loss_limit_pct must be between 0 and 1.0, got {v}")
        return v

    @field_validator("max_drawdown_pct")
    @classmethod
    def max_drawdown_pct_valid(cls, v: float) -> float:
        if not 0 < v <= 1.0:
            raise ValueError(f"max_drawdown_pct must be between 0 and 1.0, got {v}")
        return v

    @field_validator("portfolio_value_usd")
    @classmethod
    def portfolio_value_usd_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"portfolio_value_usd must be > 0, got {v}")
        return v

    @field_validator("max_open_risk_pct")
    @classmethod
    def max_open_risk_pct_valid(cls, v: float) -> float:
        if not 0 < v <= 1.0:
            raise ValueError(f"max_open_risk_pct must be between 0 and 1.0, got {v}")
        return v

    @field_validator("max_single_loss_pct")
    @classmethod
    def max_single_loss_pct_valid(cls, v: float) -> float:
        if not 0 < v <= 1.0:
            raise ValueError(f"max_single_loss_pct must be between 0 and 1.0, got {v}")
        return v


class BrainConfig(BaseModel):
    cycle_interval_seconds: int = 1800
    auto_paper_trade: bool = True
    """Enable automatic paper trading when a conviction meets the confidence and magnitude
    thresholds.  Set to ``False`` to require manual confirmation for every trade."""

    # Lower default than 0.65 so paper mode can execute in moderate-conviction regimes.
    auto_paper_trade_min_confidence: float = 0.35
    """Minimum confidence score (0–1) required to open a paper trade.
    Lower values allow trades on less-certain signals.  Default: 0.35."""

    auto_paper_trade_min_magnitude: float = 5.0
    """Minimum conviction magnitude (0–10 scale) required to open a paper trade.

    Lower values increase trade frequency but reduce signal quality.

    WARNING: Values below 3.0 will trade on weak signals and are only appropriate
    for testing.  Default: 5.0 (production-safe).
    Recommended testing range: 2.5–4.0."""


class ExecutionConfig(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    paper_start_balance: float = 10000.0
    confirmation_threshold_usd: float = 500.0
    paper_min_days: int = 14
    # Paper-mode throughput settings
    paper_max_positions_per_symbol: int = 2
    """Maximum concurrent open positions per symbol in paper mode.
    Default: 2 (allows conviction-flip / new entries while one is open).
    Set to 1 to restore legacy behaviour."""

    paper_max_hold_hours: int = 72
    """Auto-close paper positions older than this many hours. 0 = disabled. Default: 72h."""

    paper_ignore_consecutive_loss_gate: bool = True
    """Bypass the KS-1 consecutive-loss kill-switch escalation in paper mode.
    Keeps kill-switch at SAFE so repeated paper losses don't freeze paper trading. Default: True."""

    # Bundle-aware execution policy defaults (safe by default).
    allowed_bundle_asset_classes: list[str] = Field(default_factory=lambda: ["crypto"])
    allowed_bundle_venues: list[str] = Field(default_factory=lambda: ["global", "paper", "hyperliquid", "binance", "coinbase"])

    @field_validator("paper_min_days")
    @classmethod
    def paper_min_days_cannot_be_zero(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("paper_min_days must be >= 1")
        return v

    @staticmethod
    def _normalize_lower_unique(values: Any) -> list[str]:
        vals = values if isinstance(values, list) else []
        out: list[str] = []
        seen: set[str] = set()
        for raw in vals:
            item = str(raw or "").strip().lower()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @field_validator("allowed_bundle_asset_classes", "allowed_bundle_venues", mode="before")
    @classmethod
    def _normalize_policy_lists(cls, v: Any) -> list[str]:
        return cls._normalize_lower_unique(v)


class KillSwitchConfig(BaseModel):
    l1_daily_loss_pct: float = 0.03
    l2_portfolio_heat_pct: float = 0.06
    l3_crisis_threshold: int = 2
    l4_max_drawdown_pct: float = 0.30


class KarmaConfig(BaseModel):
    # default-on per PRD §18; operators can disable with karma.enabled = false in user.yaml
    enabled: bool = True
    percentage: float = 0.005
    settlement_mode: Literal["manual", "daily", "weekly", "threshold"] = "manual"
    threshold_usd: float = 50.0
    treasury_address: str = ""


class DaemonConfig(BaseModel):
    brain_interval_seconds: int = 300  # 5 min
    brain_full_interval_seconds: int = 21600  # 6 hours
    resolver_interval_seconds: int = 1800  # 30 min
    prune_interval_seconds: int = 86400  # 24 hours


class RetentionConfig(BaseModel):
    enabled: bool = True
    events_keep_days: int = 90  # Keep events for 90 days
    conviction_log_keep_days: int = 180  # Keep conviction history longer
    feature_snapshots_keep_days: int = 90
    api_rate_limits_keep_hours: int = 2
    vacuum_on_prune: bool = True  # VACUUM after pruning


class UniverseBundle(BaseModel):
    id: str
    name: str
    symbols: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    asset_class: str = "crypto"
    venue: str = "global"
    execution_mode_hint: str | None = None
    enabled: bool = True
    source: Literal["wizard", "user", "system"] = "user"

    @field_validator("id", "name", mode="before")
    @classmethod
    def _required_text(cls, v: Any) -> str:
        text = str(v or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("asset_class", "venue", mode="before")
    @classmethod
    def _normalize_lower_text(cls, v: Any) -> str:
        text = str(v or "").strip().lower()
        return text or "unknown"

    @field_validator("execution_mode_hint", mode="before")
    @classmethod
    def _normalize_execution_hint(cls, v: Any) -> str | None:
        text = str(v or "").strip().lower()
        return text or None

    @field_validator("symbols", mode="before")
    @classmethod
    def _normalize_symbols(cls, v: Any) -> list[str]:
        vals = v if isinstance(v, list) else []
        out: list[str] = []
        seen: set[str] = set()
        for raw in vals:
            sym = str(raw or "").strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append(sym)
        return out

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, v: Any) -> list[str]:
        vals = v if isinstance(v, list) else []
        out: list[str] = []
        seen: set[str] = set()
        for raw in vals:
            tag = str(raw or "").strip().lower()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            out.append(tag)
        return out


def get_scoring_symbols(universe_config: UniverseConfig) -> list[str]:
    """Derive the set of symbols the brain should score.

    Priority / merge order:
    1. Enabled bundle symbols come first (union of all enabled bundles, deduped,
       order preserved).
    2. Explicit ``universe.symbols`` supplements — any symbols not already in
       the bundle union are appended after.

    Key behaviours:

    * If ``universe.symbols`` is empty/absent, bundles drive everything.
    * If ``universe.symbols`` is non-empty and no bundles are configured, the
      explicit list is used as-is (backward-compatible).
    * Disabled bundle symbols are never included.
    * Deduplication is order-preserving (first occurrence wins).
    """
    normalize = UniverseConfig.normalize_symbols
    explicit = normalize(list(universe_config.symbols or []))

    raw_bundle: list[str] = []
    for bundle in universe_config.bundles or []:
        if bundle.enabled:
            raw_bundle.extend(bundle.symbols or [])
    bundle_syms = normalize(raw_bundle)

    # Bundles first, explicit supplements appended — deduplicated, order preserved
    seen: set[str] = set()
    result: list[str] = []
    for s in bundle_syms + explicit:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


class UniverseConfig(BaseModel):
    # Optional: explicit symbol list.  If empty (default), the scoring universe
    # is automatically derived from enabled bundle symbols.  If set, these
    # symbols *supplement* (not replace) enabled bundle symbols.
    symbols: list[str] = Field(default_factory=list)
    max_size: int = 100
    max_symbols: int = 0  # 0 = process all active symbols; set >0 to cap for performance
    bundles: list[UniverseBundle] = Field(default_factory=list)

    # TradFi symbols (stocks / ETFs) — disabled by default, zero-config via yfinance.
    # Enable by adding to your user config:
    #   universe.tradfi_symbols: [SPY, QQQ, GLD, TLT]
    #
    # Supported symbols: SPY (S&P 500), QQQ (Nasdaq), GLD (Gold), TLT (Long bonds),
    #                    IWM (Small-cap), USO (Oil) — any Yahoo Finance ticker works.
    #
    # These symbols are automatically merged into the active symbol list and routed
    # to the TradFiFeed (yfinance primary, Twelve Data backup) inside the TA producer.
    tradfi_symbols: list[str] = Field(default_factory=list)

    @staticmethod
    def normalize_symbols(values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in values:
            sym = str(raw or "").strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append(sym)
        return out

    @field_validator("symbols", mode="before")
    @classmethod
    def _normalize_symbol_list(cls, v: Any) -> list[str]:
        vals = v if isinstance(v, list) else []
        return cls.normalize_symbols(vals)

    def enabled_bundles(self) -> list[UniverseBundle]:
        return [b for b in self.bundles if b.enabled]

    def active_symbols(self) -> list[str]:
        """Return the deduplicated, capped symbol list the brain and producers use.

        Uses :func:`get_scoring_symbols` to merge enabled bundle symbols with
        any explicit ``universe.symbols`` supplement, then appends optional
        TradFi symbols and applies ``max_size``.
        """
        max_size = int(self.max_size or 0)
        if max_size <= 0:
            max_size = 1

        base = get_scoring_symbols(self)

        if not base:
            import logging as _log_uni

            _log_uni.getLogger("b1e55ed.universe").warning("UNIVERSE_EMPTY: no symbols to score — set universe.symbols or configure bundles")

        # Merge optional TradFi symbols (appended after core symbols, deduped)
        if self.tradfi_symbols:
            tradfi = self.normalize_symbols(self.tradfi_symbols)
            merged = list(dict.fromkeys(base + tradfi))  # preserve order, dedupe
            return merged[:max_size]

        return base[:max_size]

    def execution_metadata_for_symbol(self, symbol: str) -> dict[str, list[str]]:
        sym = str(symbol or "").strip().upper()
        if not sym:
            return {
                "bundle_ids": [],
                "asset_classes": [],
                "venues": [],
                "tags": [],
                "execution_mode_hints": [],
            }

        bundles = [b for b in self.enabled_bundles() if sym in b.symbols]
        tags = sorted({tag for bundle in bundles for tag in bundle.tags if tag})
        mode_hints = sorted({bundle.execution_mode_hint for bundle in bundles if bundle.execution_mode_hint})

        return {
            "bundle_ids": [bundle.id for bundle in bundles],
            "asset_classes": sorted({bundle.asset_class for bundle in bundles if bundle.asset_class}),
            "venues": sorted({bundle.venue for bundle in bundles if bundle.venue}),
            "tags": tags,
            "execution_mode_hints": mode_hints,
        }


class LoggingConfig(BaseModel):
    level: str = "INFO"
    json_output: bool = False


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5050
    auth_token: str = ""
    kill_switch_token: str = ""  # Separate auth boundary for kill switch endpoints


class DashboardConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 5051
    auth_token: str = ""


class MCPConfig(BaseModel):
    enabled: bool = True
    port: int = 7337
    require_auth: bool = False  # set True in production if port is public
    api_keys: list[str] = Field(default_factory=list)


class OnChainConfig(BaseModel):
    """ERC-8004 on-chain identity & reputation layer."""

    enabled: bool = False
    rpc_url: str = ""
    private_key: SecretStr = SecretStr("")  # Never logged — use .get_secret_value() when passing to ChainClient
    network: str = "base-sepolia"
    public_base_url: str = ""  # Fully-qualified external URL (e.g. https://b1e55ed.xyz) for on-chain agentURI minting
    identity_registry_address: str = ""
    reputation_registry_address: str = ""
    validation_registry_address: str = ""
    system_agent_id: int = 0


class EASConfig(BaseModel):
    enabled: bool = True  # off-chain attestations work without rpc_url; on-chain needs rpc_url
    rpc_url: str = "https://eth.llamarpc.com"  # Free public RPC
    eas_contract: str = "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587"
    schema_registry: str = "0xA7b39296258348C78294F95B872b282326A97BDF"
    schema_uid: str = ""  # Set after schema registration
    attester_private_key: SecretStr = SecretStr("")  # Never logged — use .get_secret_value() when passing to EAS client
    mode: Literal["onchain", "offchain"] = "offchain"


class PublishGithubConfig(BaseModel):
    owner: str = "P-U-C"
    repo: str = "b1e55ed"
    token: str = ""  # PAT (legacy); never logged
    # GitHub App auth (preferred when app_id is non-zero)
    # Private key is loaded from B1E55ED_GITHUB_APP_KEY env var — never stored in config.
    app_id: int = 0  # GitHub App ID
    installation_id: int = 0  # GitHub App Installation ID
    labels: list[str] = Field(default_factory=lambda: ["b1e55ed-attestation"])
    mode: str = "issues"  # future: contents/ipfs


class PublishConfig(BaseModel):
    github: PublishGithubConfig = Field(default_factory=PublishGithubConfig)


class Config(BaseSettings):
    """Root configuration. Single source of truth."""

    # Paths — use default_factory so Path.home() is evaluated at construction
    # time, not import time (allows tests to monkeypatch HOME).
    data_dir: Path = Field(default_factory=lambda: _data_dir())

    config_dir: Path = Path("config")

    # Preset selection
    preset: Literal["conservative", "balanced", "degen", "custom"] = "balanced"

    # Component configs
    weights: DomainWeights = Field(default_factory=DomainWeights)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    brain: BrainConfig = Field(default_factory=BrainConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    kill_switch: KillSwitchConfig = Field(default_factory=KillSwitchConfig)
    karma: KarmaConfig = Field(default_factory=KarmaConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    onchain: OnChainConfig = Field(default_factory=OnChainConfig)
    eas: EASConfig = Field(default_factory=EASConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)
    github_publish: PublishGithubConfig = Field(default_factory=PublishGithubConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)

    model_config = {"env_prefix": "B1E55ED_", "env_nested_delimiter": "__"}

    @classmethod
    def from_yaml(cls, path: Path) -> Config:
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")

        raw = yaml.safe_load(path.read_text()) or {}

        preset_name = raw.get("preset", "balanced")
        preset_path = path.parent / "presets" / f"{preset_name}.yaml"
        if preset_path.exists():
            preset_data = yaml.safe_load(preset_path.read_text()) or {}
            raw = _deep_merge(preset_data, raw)

        raw = cls._apply_learned_weights_overlay(raw, config_path=path)

        return cls(**raw)

    @classmethod
    def _bundled_config_root(cls) -> Path:
        """Return the package-bundled config directory (works when installed as uv tool)."""
        return Path(__file__).resolve().parents[1] / "data" / "config"

    @classmethod
    def _learned_weights_path(cls, *, config_path: Path) -> Path:
        resolved_cfg = config_path.resolve()
        bundled_root = cls._bundled_config_root().resolve()
        if resolved_cfg.is_relative_to(bundled_root):
            return _data_dir() / "learned_weights.yaml"
        return config_path.parent.parent / "data" / "learned_weights.yaml"

    @classmethod
    def _apply_learned_weights_overlay(cls, raw: dict[str, Any], *, config_path: Path) -> dict[str, Any]:
        # Learned weights overlay (surface 3)
        learned = cls._learned_weights_path(config_path=config_path)
        if learned.exists():
            learned_data = yaml.safe_load(learned.read_text()) or {}
            if isinstance(learned_data.get("weights"), dict):
                raw.setdefault("weights", {}).update(learned_data["weights"])
        return raw

    @classmethod
    def from_repo_defaults(cls, repo_root: Path | None = None) -> Config:
        root = repo_root or Path.cwd()
        config_path = root / "config" / "default.yaml"
        if not config_path.exists():
            # Fall back to bundled config — handles `uv tool install` where cwd
            # is the user's home dir, not the package source root.
            config_path = cls._bundled_config_root() / "default.yaml"
        return cls.from_yaml(config_path)

    @classmethod
    def from_preset(
        cls,
        preset: Literal["conservative", "balanced", "degen"],
        *,
        repo_root: Path | None = None,
    ) -> Config:
        root = repo_root or Path.cwd()
        default_path = root / "config" / "default.yaml"
        if not default_path.exists():
            default_path = cls._bundled_config_root() / "default.yaml"
        raw = yaml.safe_load(default_path.read_text()) or {}
        raw["preset"] = preset
        # Emulate from_yaml's behavior (preset chain) without requiring a temp file.
        preset_path = default_path.parent / "presets" / f"{preset}.yaml"
        if not preset_path.exists():
            raise ConfigError(f"Preset file not found: {preset_path}")
        preset_data = yaml.safe_load(preset_path.read_text()) or {}
        raw = _deep_merge(preset_data, raw)
        raw = cls._apply_learned_weights_overlay(raw, config_path=default_path)
        return cls(**raw)
