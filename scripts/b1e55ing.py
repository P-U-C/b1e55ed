"""a b1e55ing — Easter egg injection hook for b1e55ed PRs.

Usage:

  # Step 1 — dump context for AI session to read:
  python scripts/b1e55ing.py --pr-number 77 --github-token $GH_TOKEN --mode dump-context > /tmp/ctx.json

  # Step 2 — AI session reads ctx.json, generates eggs, writes to /tmp/eggs.json

  # Step 3 — apply the eggs:
  python scripts/b1e55ing.py --pr-number 77 --github-token $GH_TOKEN --mode apply-eggs --eggs-file /tmp/eggs.json

  # Dry-run (inspect without writing):
  python scripts/b1e55ing.py --pr-number 77 --github-token $GH_TOKEN --mode dry-run --eggs-file /tmp/eggs.json

# 0xb1e55ed = "blessed" — the name is the first egg.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Logging — branded prefix on every line
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="a b1e55ing: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO = "P-U-C/b1e55ed"
REFERENCE_PATH = Path(__file__).parent.parent / "docs" / "EASTER_EGG_REFERENCE.md"
MAX_EGGS_PER_FILE = 2

# ---------------------------------------------------------------------------
# Scaling — blessings proportional to PR size, with diminishing returns
# ---------------------------------------------------------------------------

# The Talmud is commentary layered onto Torah, then commentary onto commentary.
# A codebase accumulates cultural strata the same way. This script is the ritual.
_BUDGET_TIERS: list[tuple[int, int]] = [
    (1, 1),  # 1 file       → 1
    (4, 2),  # 2–4 files    → 2
    (10, 3),  # 5–10 files   → 3
    (20, 4),  # 11–20 files  → 4
    (50, 5),  # 21–50 files  → 5
]
_BUDGET_HARD_CAP = 6  # 51+ files → 6


def max_blessings(n_files: int) -> int:
    """Logarithmic scaling. Small PRs get focused attention.
    Large PRs get meaningful signal, not noise.

    1 file  → 1
    2-4     → 2
    5-10    → 3
    11-20   → 4
    21-50   → 5
    51+     → 6 (hard cap)
    """
    if n_files <= 0:
        return 0
    for limit, level in _BUDGET_TIERS:
        if n_files <= limit:
            return level
    return _BUDGET_HARD_CAP


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


def fetch_pr_files(pr_number: int, github_token: str) -> list[dict[str, Any]]:
    """Return list of file objects from the GitHub PR Files API."""
    url = f"https://api.github.com/repos/{REPO}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]


def fetch_pr(pr_number: int, github_token: str) -> dict[str, Any]:
    """Return PR metadata from the GitHub PR API."""
    url = f"https://api.github.com/repos/{REPO}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()  # type: ignore[return-value]


def dump_context(pr_number: int, github_token: str) -> dict[str, Any]:
    """Fetch PR metadata, files, and diffs. Return structured context for AI session."""
    pr_meta = fetch_pr(pr_number, github_token)
    files = fetch_pr_files(pr_number, github_token)
    python_files = [f for f in files if f.get("filename", "").endswith(".py") and f.get("status") != "removed"]

    reference = ""
    ref_path = REFERENCE_PATH
    if ref_path.exists():
        reference = ref_path.read_text(encoding="utf-8")

    file_contexts: list[dict[str, str]] = []
    for f in python_files:
        rel_path = f.get("filename", "")
        path = Path(rel_path)
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        file_contexts.append(
            {
                "path": rel_path,
                "content": content,
                "patch": f.get("patch", ""),
            }
        )

    return {
        "pr_number": pr_number,
        "pr_title": pr_meta.get("title", ""),
        "pr_body": pr_meta.get("body", ""),
        "budget": max_blessings(len(python_files)),
        "reference": reference,
        "files": file_contexts,
    }


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------


def _insert_lines_after(lines: list[str], anchor: str, content: str) -> list[str]:
    """Return new line list with *content* inserted after the line containing *anchor*."""
    for i, line in enumerate(lines):
        if anchor in line:
            new_lines = content.splitlines(keepends=False)
            return lines[: i + 1] + [ln + "\n" for ln in new_lines] + lines[i + 1 :]
    return lines  # anchor not found — unchanged


def _insert_lines_before(lines: list[str], anchor: str, content: str) -> list[str]:
    """Return new line list with *content* inserted before the line containing *anchor*."""
    for i, line in enumerate(lines):
        if anchor in line:
            new_lines = content.splitlines(keepends=False)
            return lines[:i] + [ln + "\n" for ln in new_lines] + lines[i:]
    return lines  # anchor not found — unchanged


def apply_egg(file_path: Path, egg: dict[str, Any], *, dry_run: bool = False) -> bool:
    """Apply a single egg to *file_path*.

    Returns True if the egg was applied (or would be in dry-run), False if skipped.
    """
    if not file_path.exists():
        log.warning("File not found, skipping egg: %s", file_path)
        return False

    original = file_path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    placement = egg.get("placement", "")
    anchor = egg.get("anchor", "")
    content = egg.get("content", "")

    if not content.endswith("\n"):
        content += "\n"

    if placement == "module_docstring":
        # Append inside an existing module docstring, or prepend a new one.
        stripped = original.lstrip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            close_idx = original.find(quote, original.index(quote) + 3)
            if close_idx != -1:
                insertion = "\n" + content.rstrip("\n")
                patched = original[:close_idx] + insertion + "\n" + original[close_idx:]
            else:
                patched = original  # malformed docstring — skip
        else:
            # Prepend new docstring before the first non-comment line
            prefix_end = 0
            for line in lines:
                stripped_line = line.lstrip()
                if stripped_line.startswith("#") or stripped_line in ("", "\n"):
                    prefix_end += len(line)
                else:
                    break
            new_doc = f'"""\n{content.rstrip(chr(10))}\n"""\n\n'
            patched = original[:prefix_end] + new_doc + original[prefix_end:]

    elif placement == "after_class":
        patched = "".join(_insert_lines_after(lines, anchor, content))

    elif placement in ("before_function", "inline_comment"):
        patched = "".join(_insert_lines_before(lines, anchor, content))

    elif placement == "constant":
        patched = "".join(_insert_lines_after(lines, anchor, content))

    else:
        log.warning("Unknown placement '%s', skipping egg for %s", placement, file_path)
        return False

    if patched == original:
        log.warning("Anchor '%s' not found in %s — egg skipped", anchor, file_path)
        return False

    # Validate Python — never leave broken source
    try:
        ast.parse(patched)
    except SyntaxError as exc:
        log.warning("Patched %s fails ast.parse (%s) — egg skipped", file_path, exc)
        return False

    if dry_run:
        log.info("(dry run) would patch %s [%s / %s]", file_path, egg.get("tradition"), egg.get("mode"))
        return True

    file_path.write_text(patched, encoding="utf-8")
    log.info("patched %s — %s / %s", file_path, egg.get("tradition"), egg.get("mode"))
    return True


# ---------------------------------------------------------------------------
# Dry-run display
# ---------------------------------------------------------------------------


def print_dry_run(eggs: list[dict[str, Any]], skipped: list[str], skip_reasons: dict[str, str]) -> None:
    print("--- a b1e55ing (dry run) ---")
    if not eggs:
        print("no eggs suggested for this PR")
    for egg in eggs:
        print(f"\nfile:      {egg.get('file')}")
        print(f"placement: {egg.get('placement')}  anchor: {egg.get('anchor')!r}")
        print(f"tradition: {egg.get('tradition')}  mode: {egg.get('mode')}")
        print(f"rationale: {egg.get('rationale')}")
        print("content:")
        for line in egg.get("content", "").splitlines():
            print(f"  {line}")
    if skipped:
        print("\nskipped files:")
        for f in skipped:
            reason = skip_reasons.get(f, "")
            print(f"  {f}: {reason}")
    print("--- end dry run ---")


def _load_eggs_payload(eggs_file: Path) -> dict[str, Any]:
    """Read and normalize eggs payload from disk."""
    payload = json.loads(eggs_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("eggs file must contain a JSON object")

    eggs = payload.get("eggs", [])
    skipped = payload.get("skipped", [])
    skip_reasons = payload.get("skip_reasons", {})

    if not isinstance(eggs, list):
        eggs = []
    if not isinstance(skipped, list):
        skipped = []
    if not isinstance(skip_reasons, dict):
        skip_reasons = {}

    payload["eggs"] = eggs
    payload["skipped"] = skipped
    payload["skip_reasons"] = skip_reasons
    return payload


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="a b1e55ing — Easter egg injection hook")
    parser.add_argument("--pr-number", required=True, type=int, help="PR number")
    parser.add_argument("--github-token", required=True, help="GitHub API token")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["dump-context", "apply-eggs", "dry-run"],
        help="Operation mode",
    )
    parser.add_argument("--eggs-file", default="", help="Path to JSON file containing egg suggestions")
    parser.add_argument("--base-branch", default="", help="Base branch (informational, optional)")
    parser.add_argument("--repo-root", default=".", help="Path to repo root (default: cwd)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()

    if args.mode == "dump-context":
        context = dump_context(args.pr_number, args.github_token)
        print(json.dumps(context, ensure_ascii=False))
        return 0

    if not args.eggs_file:
        log.error("--eggs-file is required for %s mode", args.mode)
        return 1

    eggs_path = Path(args.eggs_file).resolve()
    if not eggs_path.exists():
        log.error("eggs file not found: %s", eggs_path)
        return 1

    try:
        payload = _load_eggs_payload(eggs_path)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("invalid eggs payload: %s", exc)
        return 1

    eggs: list[dict[str, Any]] = payload.get("eggs", [])
    skipped: list[str] = payload.get("skipped", [])
    skip_reasons: dict[str, str] = payload.get("skip_reasons", {})

    if args.mode == "dry-run":
        print_dry_run(eggs, skipped, skip_reasons)
        would_apply = 0
        for egg in eggs:
            rel_path = str(egg.get("file", ""))
            abs_path = repo_root / rel_path
            if apply_egg(abs_path, egg, dry_run=True):
                would_apply += 1
        log.info("(dry run) %d egg(s) would apply", would_apply)
        return 0

    applied = 0
    for egg in eggs:
        rel_path = str(egg.get("file", ""))
        abs_path = repo_root / rel_path
        if apply_egg(abs_path, egg, dry_run=False):
            applied += 1

    if applied == 0:
        log.info("no eggs applied — nothing to commit")
        return 0

    log.info("%d egg(s) applied — committing", applied)
    import subprocess  # noqa: PLC0415

    result = subprocess.run(
        ["git", "add", "-A"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("git add failed: %s", result.stderr)
        return 1

    result = subprocess.run(
        ["git", "commit", "-m", "chore: a b1e55ing [skip ci]"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("git commit failed: %s", result.stderr)
        return 1

    log.info("committed: %s", result.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
