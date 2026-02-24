"""Allow ``python -m engine.cli`` module execution.

This re-enables direct module invocation (e.g. in source checkouts or tooling
that bypasses the installed console-script entrypoint)::

    python -m engine.cli --help
    python -m engine.cli backtest walkforward --prices prices.csv
"""

from engine.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
