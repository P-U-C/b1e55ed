"""engine — the irreducible core.

The repo name is the first easter egg:

- ``0xb1e55ed`` = "blessed".

Genesis layer constants are deliberate reminders: systems without memory repeat mistakes.
"""

from __future__ import annotations

__all__ = [
    "__version__",
    "BLESSED_HEX",
    "GENESIS_HASH",
    "GENESIS_TIMESTAMP",
    "ALIGNMENT_CHECK",
]

__version__ = "2.0.0"

# 0xb1e55ed = "blessed"
BLESSED_HEX = 0xB1E55ED

# Bitcoin genesis block (Jan 3, 2009). The headline embedded in block 0 was not decoration.
GENESIS_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
GENESIS_TIMESTAMP = 1231006505  # Jan 3, 2009 18:15:05 UTC

# SHA256("we are all satoshi") — first four chars
ALIGNMENT_CHECK = "8a5d"
