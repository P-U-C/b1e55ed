"""engine.config.github_app_defaults

Baked-in public constants for the community GitHub App.

These are public identifiers — not secrets.
The private key is ALWAYS loaded from the B1E55ED_GITHUB_APP_KEY environment
variable at runtime; it is never stored in source code or config files.

Update COMMUNITY_APP_ID and COMMUNITY_INSTALLATION_ID once the GitHub App
has been created (e.g. by zoz) and the values are known.
"""

from __future__ import annotations

# Placeholder values — update when the GitHub App is created.
# These are public info (visible in GitHub UI), not secrets.
COMMUNITY_APP_ID: int = 2953603
COMMUNITY_INSTALLATION_ID: int = 112556330
