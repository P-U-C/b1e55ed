"""engine.cli

Command line interface package for b1e55ed (AG2 decomposition).

Public API:
- ``main(argv)`` — CLI entry point
- ``build_parser()`` — argparse parser
- ``CliContext`` — CLI execution context

Internal helpers are re-exported for backward compatibility with tests.
"""

from __future__ import annotations

from engine.cli.main import (  # noqa: F401
    CliContext,
    _cmd_setup,
    _identity_forge,
    _identity_show,
    _json_dumps,
    _parse_grid_spec,
    _parse_param_spec,
    build_parser,
    main,
)

__all__ = ["main", "build_parser", "CliContext"]
