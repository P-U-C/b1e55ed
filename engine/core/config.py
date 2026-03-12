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
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings

from engine.core.exceptions import ConfigError
from engine.core.paths import data_dir as _data_dir


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


class BrainConfig(BaseModel):
    cycle_interval_seconds: int = 1800
    auto_paper_trade: bool = True
    # Lower default than 0.65 so paper mode can execute in moderate-conviction regimes.
    auto_paper_trade_min_confidence: float = 0.35


class ExecutionConfig(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    paper_start_balance: float = 10000.0
    confirmation_threshold_usd: float = 500.0
    paper_min_days: int = 14

    @field_validator("paper_min_days")
    @classmethod
    def paper_min_days_cannot_be_zero(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("paper_min_days must be >= 1")
        return v


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


class UniverseConfig(BaseModel):
    symbols: list[str] = ["BTC", "ETH", "SOL", "SUI", "HYPE"]
    max_size: int = 100


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


class EASConfig(BaseModel):
    enabled: bool = True  # off-chain attestations work without rpc_url; on-chain needs rpc_url
    rpc_url: str = "https://eth.llamarpc.com"  # Free public RPC
    eas_contract: str = "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587"
    schema_registry: str = "0xA7b39296258348C78294F95B872b282326A97BDF"
    schema_uid: str = ""  # Set after schema registration
    attester_private_key: str = ""  # Private key for signing attestations
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
    eas: EASConfig = Field(default_factory=EASConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)
    github_publish: PublishGithubConfig = Field(default_factory=PublishGithubConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)

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
