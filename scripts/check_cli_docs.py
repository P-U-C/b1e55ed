#!/usr/bin/env python3
"""Verify every CLI command registered in engine/cli/main.py has a section in docs/cli-reference.md.

Exits 1 if any commands are undocumented.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
CLI_FILE = REPO / "engine" / "cli" / "main.py"
CLI_REF = REPO / "docs" / "operations" / "cli-reference.mdx"


def extract_cli_commands(path: Path) -> set[str]:
    """Extract top-level subcommand names from engine/cli/*.

    Scans main.py for `sub.add_parser("name")` calls and also scans
    engine/cli/commands/ for `build_*_parser(sub)` modules that register
    their own top-level commands.
    """
    commands: set[str] = set()

    # 1. Top-level registrations in main.py (variable 'sub')
    source = path.read_text()
    for match in re.finditer(r'\bsub\.add_parser\(\s*["\']([^"\']+)["\']', source):
        commands.add(match.group(1))

    # 2. Commands registered by external build_*_parser(sub) modules
    commands_dir = path.parent / "commands"
    if commands_dir.is_dir():
        for mod in commands_dir.glob("*.py"):
            mod_source = mod.read_text()
            for match in re.finditer(r'\bsub\.add_parser\(\s*["\']([^"\']+)["\']', mod_source):
                commands.add(match.group(1))

    return commands


def extract_documented_commands(path: Path) -> set[str]:
    """Extract command names from ### `b1e55ed <command>` headings in cli-reference.md."""
    text = path.read_text()
    documented: set[str] = set()
    for match in re.finditer(r"^\s*### `b1e55ed ([^`]+)`", text, re.MULTILINE):
        # First token after 'b1e55ed' is the top-level command
        cmd = match.group(1).strip().split()[0]
        documented.add(cmd)
    return documented


def main() -> int:
    cli_commands = extract_cli_commands(CLI_FILE)
    documented = extract_documented_commands(CLI_REF)

    # Commands that are implementation details / not user-facing
    ignored = {"help"}
    cli_commands -= ignored

    missing = cli_commands - documented
    extra = documented - cli_commands

    ok = True
    if missing:
        print(f"❌ {len(missing)} CLI command(s) not documented in docs/cli-reference.md:")
        for cmd in sorted(missing):
            print(f"   b1e55ed {cmd}")
        ok = False

    if extra:
        # Extra docs entries are informational only — don't fail
        print(f"ℹ️  {len(extra)} documented command(s) not found in CLI source (may be aliases or removed):")
        for cmd in sorted(extra):
            print(f"   b1e55ed {cmd}")

    if ok:
        print(f"✅ All {len(cli_commands)} CLI commands documented.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
