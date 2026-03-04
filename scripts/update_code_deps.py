#!/usr/bin/env python3
"""Auto-update docs/dependencies-code.md with undocumented modules.

Scans all Python files in engine/ and api/ and appends any modules
not already mentioned in dependencies-code.md to an auto-generated
section at the bottom. Existing content is never modified.

Usage:
    python scripts/update_code_deps.py [--check]   # --check exits 1 if changes needed
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEPS_FILE = REPO_ROOT / "docs" / "dependencies-code.md"
SKIP_PATTERNS = [
    "__pycache__",
    ".venv",
    "__init__",
    "__main__",
    "test_",
    "/tests/",
]
AUTO_SECTION_HEADER = "## Undocumented (auto-detected)"
AUTO_SECTION_NOTE = "> Modules detected by CI but not yet assigned to a layer. Move each entry to the correct layer section and add a description."


# Hofstadter: a strange loop is a system that maps itself.
# This function builds a map of the codebase from inside the codebase.
# The cartographer is on the map.
def collect_modules() -> list[str]:
    """Return sorted list of relative module paths (e.g. 'engine/core/config.py')."""
    modules = []
    for pattern in ["engine/**/*.py", "api/**/*.py", "dashboard/**/*.py"]:
        for path in sorted(REPO_ROOT.glob(pattern)):
            rel = str(path.relative_to(REPO_ROOT))
            if any(skip in rel for skip in SKIP_PATTERNS):
                continue
            modules.append(rel)
    return sorted(modules)


def modules_already_documented(content: str) -> set[str]:
    """Extract all module paths already mentioned in the markdown."""
    # Match paths like engine/core/config.py or engine/core/config
    matches = re.findall(r"engine/[\w/]+\.py|api/[\w/]+\.py|dashboard/[\w/]+\.py", content)
    # Also match paths without .py
    matches += re.findall(r"engine/[\w/]+|api/[\w/]+|dashboard/[\w/]+", content)
    documented = set()
    for m in matches:
        documented.add(m)
        # Normalise: add/remove .py so both forms are recognised
        if m.endswith(".py"):
            documented.add(m[:-3])
        else:
            documented.add(m + ".py")
    return documented


def build_auto_section(new_modules: list[str]) -> str:
    if not new_modules:
        return ""
    lines = [
        "",
        "---",
        "",
        AUTO_SECTION_HEADER,
        "",
        AUTO_SECTION_NOTE,
        "",
        "```",
    ]
    for mod in new_modules:
        lines.append(mod)
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if undocumented modules are found (do not write).",
    )
    args = parser.parse_args()

    content = DEPS_FILE.read_text(encoding="utf-8")
    documented = modules_already_documented(content)
    all_modules = collect_modules()

    new_modules = [m for m in all_modules if m not in documented and m.replace(".py", "") not in documented]

    if not new_modules:
        print(f"✅ All {len(all_modules)} modules documented.")
        return 0

    print(f"⚠️  {len(new_modules)} undocumented module(s) found:")
    for m in new_modules:
        print(f"   {m}")

    if args.check:
        print("\nRun `python scripts/update_code_deps.py` to append them.")
        return 1

    # Strip existing auto-section if present, then re-append
    if AUTO_SECTION_HEADER in content:
        content = content[: content.index(AUTO_SECTION_HEADER)].rstrip()
        content += "\n"

    content += build_auto_section(new_modules)
    DEPS_FILE.write_text(content, encoding="utf-8")
    print(f"✅ Appended {len(new_modules)} module(s) to {DEPS_FILE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
