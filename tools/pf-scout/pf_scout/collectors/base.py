"""Base classes for pf-scout collectors."""

from dataclasses import dataclass, field


@dataclass
class Prospect:
    """A single prospect profile with raw signal data."""

    handle: str  # Primary identifier (GitHub handle, wallet, Twitter handle)
    display_name: str | None = None
    source: str = "manual"  # Where this came from: github, postfiat, twitter, manual

    # Raw signals (populated by collectors)
    github_repos: int = 0
    github_followers: int = 0
    github_contributions: dict = field(default_factory=dict)  # repo → commit count
    github_bio: str = ""
    github_company: str = ""
    github_location: str = ""

    postfiat_capabilities: list = field(default_factory=list)  # from /profile Expert Knowledge
    postfiat_task_count: int = 0
    postfiat_pft_earned: float = 0.0
    postfiat_tenure_days: int = 0

    twitter_followers: int = 0
    twitter_bio: str = ""
    twitter_market_posts: int = 0  # posts with market analysis keywords

    discord_message_count: int = 0
    discord_channels_active: list = field(default_factory=list)

    # Manual override fields
    notes: str = ""  # Free-text evidence notes
    manual_scores: dict = field(default_factory=dict)  # dimension_id → score (overrides auto)

    # Computed (filled by scorer)
    dimension_scores: dict = field(default_factory=dict)  # dimension_id → score
    dimension_evidence: dict = field(default_factory=dict)  # dimension_id → evidence string
    total_score: float = 0.0
    weighted_score: float = 0.0
    tier: str = ""
    recruitment_angle: str = ""
