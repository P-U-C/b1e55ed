"""a b1e55ing — Easter egg injection hook for b1e55ed PRs.

Analyzes PR diffs and adds brand-appropriate cultural references as
comments/docstrings to changed Python files. Blessings scale logarithmically
with PR size: small PRs get focused attention, large PRs get signal not noise.

Agent usage (primary path — local, uses ANTHROPIC_API_KEY from env):
    python scripts/b1e55ing.py \\
        --pr-number 77 \\
        --github-token $GH_TOKEN \\
        --mode agent

Gemini fallback (CI — uses GOOGLE_API_KEY from env):
    python scripts/b1e55ing.py \\
        --pr-number 77 \\
        --github-token $GH_TOKEN \\
        --mode gemini

Dry-run (inspect suggestions without writing files):
    python scripts/b1e55ing.py --pr-number 77 --github-token $GH_TOKEN \\
        --mode agent --dry-run

# 0xb1e55ed = "blessed" — the name is the first egg.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import sys
import textwrap
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
ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"
GEMINI_MODEL = "gemini-2.0-flash-exp"
MAX_EGGS_PER_FILE = 2
REFERENCE_PATH = Path(__file__).parent.parent / "docs" / "EASTER_EGG_REFERENCE.md"

# Brand-filter phrases that must appear in the system prompt.
BRAND_FILTER_PHRASES = [
    "Timeless over trendy",
    "Conviction over consensus",
    "Builders over tourists",
]

SYSTEM_PROMPT = textwrap.dedent("""
    You are a cultural reference curator for the b1e55ed codebase. Your job is to add
    meaningful Easter eggs — comments, docstrings, constants — to Python files changed
    in a PR. You have deep knowledge of the intellectual traditions described in the
    reference document.

    Rules:
    - Only add comments, docstrings, or named constants. Never modify logic.
    - Prefer obscure over obvious — rewards people who read the code.
    - Every egg must pass the brand filter:
      Timeless over trendy. Conviction over consensus. Builders over tourists.
    - No crypto-twitter vernacular. No exclamation marks. Precision carries the energy.
    - Wit is understated. Humor from precision, not performance.
    - Maximum 2 eggs per file. Quality over quantity.
    - If no egg fits naturally, return empty for that file — forced eggs are worse
      than none.

    Return ONLY valid JSON — no markdown fences, no prose. Schema:
    {
      "eggs": [
        {
          "file": "<relative path>",
          "anchor": "<exact string to locate in file>",
          "placement": "<module_docstring|after_class|before_function|inline_comment|constant>",
          "content": "<text to insert>",
          "tradition": "<intellectual_tradition_slug>",
          "mode": "<obscure|obvious>",
          "rationale": "<one sentence>"
        }
      ],
      "skipped": ["<file>"],
      "skip_reasons": {"<file>": "<reason>"}
    }
""").strip()


# ---------------------------------------------------------------------------
# Scaling — blessings proportional to PR size, with diminishing returns
# ---------------------------------------------------------------------------

# Explicit tiers so the boundary is unambiguous and readable.
# Mirrors the docstring table exactly.
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
# LLM abstraction — agent (Anthropic) and gemini (Google) paths
# ---------------------------------------------------------------------------


class LLMClient:
    """Thin wrapper that routes completions to the right backend.

    Both backends use lazy imports — neither is a hard dependency at import time.
    The fallback path (gemini) is invisible: the blessing looks the same
    regardless of which path ran.
    """

    def __init__(self, mode: str, api_key: str = "") -> None:
        if mode not in ("agent", "gemini"):
            raise ValueError(f"Unknown mode: {mode!r} — use 'agent' or 'gemini'")
        self.mode = mode
        self.api_key = api_key

    def complete(self, system: str, user: str) -> str:
        """Return LLM text completion given *system* and *user* prompts."""
        if self.mode == "agent":
            return self._call_anthropic(system, user)
        return self._call_gemini(system, user)

    def _call_anthropic(self, system: str, user: str) -> str:
        """Anthropic Claude via the official SDK. API key from env."""
        try:
            import anthropic  # lazy — not required in gemini mode
        except ImportError as exc:
            raise RuntimeError("anthropic package not installed — run: pip install anthropic") from exc

        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot proceed in agent mode")

        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return str(message.content[0].text)  # type: ignore[union-attr]

    def _call_gemini(self, system: str, user: str) -> str:
        """Google Gemini 2.0 Flash (free tier). API key from env."""
        try:
            import google.generativeai as genai  # lazy — not required in agent mode
        except ImportError as exc:
            raise RuntimeError("google-generativeai package not installed — run: pip install google-generativeai") from exc

        key = self.api_key or os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            raise RuntimeError("GOOGLE_API_KEY is not set — cannot proceed in gemini mode")

        genai.configure(api_key=key)
        model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=system)
        resp = model.generate_content(user)
        return str(resp.text)


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


def fetch_pr_meta(pr_number: int, github_token: str) -> dict[str, Any]:
    """Return PR title and body."""
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


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

_BLESSING_BUDGET_TABLE = textwrap.dedent("""
    Blessing budget (logarithmic — quality over quantity):
      1 file   → 1 blessing total
      2–4      → 2 blessings total
      5–10     → 3 blessings total
      11–20    → 4 blessings total
      21–50    → 5 blessings total
      51+      → 6 blessings total (hard cap)

    A 50-file PR should feel MORE curated than a 1-file PR, not more cluttered.
    Allocate your budget to the files where a blessing will land best.
    Forced eggs are worse than none.
""").strip()


def build_user_prompt(
    pr_title: str,
    pr_body: str,
    file_contexts: list[dict[str, str]],
    reference_text: str,
    total_budget: int,
) -> str:
    """Assemble the user-facing LLM prompt."""
    parts: list[str] = [
        f"PR Title: {pr_title}",
        f"PR Description: {pr_body or '(none)'}",
        "",
        f"You have a total budget of {total_budget} blessing(s) for this PR.",
        _BLESSING_BUDGET_TABLE,
        "",
        "=== EASTER EGG REFERENCE ===",
        reference_text,
        "",
        "=== FILES CHANGED IN THIS PR ===",
    ]

    for fc in file_contexts:
        parts.append(f"\n--- {fc['filename']} ---")
        parts.append("DIFF HUNKS:")
        parts.append(fc["patch"])
        parts.append("CURRENT FILE CONTENT (first 100 lines):")
        parts.append(fc["content_preview"])

    parts.append("")
    parts.append(
        f"Analyze the files above. Return JSON with at most {total_budget} egg(s) total, "
        f"max {MAX_EGGS_PER_FILE} per file. Skipped files must be listed in 'skipped'."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_llm_response(raw: str, total_budget: int | None = None) -> dict[str, Any]:
    """Parse and validate the JSON response from the LLM.

    Enforces:
    - Per-file cap of MAX_EGGS_PER_FILE
    - Global cap of *total_budget* eggs (if provided)
    Treats malformed JSON as empty.
    """
    text = raw.strip()
    # Strip markdown fences if the model ignores the instruction
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("LLM returned non-JSON (%s) — treating as no eggs", exc)
        return {"eggs": [], "skipped": [], "skip_reasons": {}}

    eggs: list[dict[str, Any]] = data.get("eggs", [])

    # Enforce per-file cap
    file_counts: dict[str, int] = {}
    capped: list[dict[str, Any]] = []
    for egg in eggs:
        fname = egg.get("file", "")
        count = file_counts.get(fname, 0)
        if count < MAX_EGGS_PER_FILE:
            capped.append(egg)
            file_counts[fname] = count + 1
        else:
            log.warning("Capping eggs for %s at %d — extra egg dropped", fname, MAX_EGGS_PER_FILE)

    # Enforce global budget cap
    if total_budget is not None and len(capped) > total_budget:
        log.warning("Total eggs (%d) exceeds budget (%d) — trimming", len(capped), total_budget)
        capped = capped[:total_budget]

    data["eggs"] = capped
    return data


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
        choices=["agent", "gemini"],
        help="LLM backend: 'agent' (Anthropic, primary) or 'gemini' (Google, CI fallback)",
    )
    parser.add_argument("--base-branch", default="", help="Base branch (informational, optional)")
    parser.add_argument("--dry-run", action="store_true", help="Print suggestions without writing files")
    parser.add_argument("--repo-root", default=".", help="Path to repo root (default: cwd)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()

    # Resolve API key from environment
    if args.mode == "agent":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            log.error("ANTHROPIC_API_KEY is not set — cannot proceed in agent mode")
            return 1
    else:
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            log.error("GOOGLE_API_KEY is not set — cannot proceed in gemini mode")
            return 1

    llm = LLMClient(mode=args.mode, api_key=api_key)

    # Load reference document
    if not REFERENCE_PATH.exists():
        log.error("Easter egg reference not found at %s", REFERENCE_PATH)
        return 1
    reference_text = REFERENCE_PATH.read_text(encoding="utf-8")

    # Fetch PR metadata
    log.info("fetching PR #%d metadata", args.pr_number)
    pr_meta = fetch_pr_meta(args.pr_number, args.github_token)
    pr_title: str = pr_meta.get("title", "")
    pr_body: str = pr_meta.get("body", "") or ""

    # Fetch changed files
    log.info("fetching PR #%d file list", args.pr_number)
    pr_files = fetch_pr_files(args.pr_number, args.github_token)

    # Filter to Python files that are added or modified
    python_files = [f for f in pr_files if f.get("filename", "").endswith(".py") and f.get("status") in ("added", "modified")]

    if not python_files:
        log.info("no Python files changed — nothing to do")
        return 0

    n_files = len(python_files)
    budget = max_blessings(n_files)
    log.info("%d Python file(s) in scope — blessing budget: %d (mode: %s)", n_files, budget, args.mode)

    # Build per-file context
    file_contexts: list[dict[str, str]] = []
    for pf in python_files:
        fname = pf.get("filename", "")
        patch = pf.get("patch", "")
        abs_path = repo_root / fname
        if abs_path.exists():
            content_lines = abs_path.read_text(encoding="utf-8").splitlines()
            content_preview = "\n".join(content_lines[:100])
        else:
            content_preview = "(file not available on disk)"
        file_contexts.append({"filename": fname, "patch": patch, "content_preview": content_preview})

    # Build prompt and call LLM
    user_prompt = build_user_prompt(pr_title, pr_body, file_contexts, reference_text, budget)
    log.info("calling %s (budget: %d)", args.mode, budget)
    raw_response = llm.complete(SYSTEM_PROMPT, user_prompt)

    # Parse response — enforce both per-file and global caps
    result = parse_llm_response(raw_response, total_budget=budget)
    eggs: list[dict[str, Any]] = result.get("eggs", [])
    skipped: list[str] = result.get("skipped", [])
    skip_reasons: dict[str, str] = result.get("skip_reasons", {})

    if not eggs:
        log.info("no eggs suggested for this PR")
        return 0

    log.info("%d egg(s) suggested across %d file(s)", len(eggs), len({e.get("file") for e in eggs}))

    if args.dry_run:
        print_dry_run(eggs, skipped, skip_reasons)
        return 0

    # Apply patches
    applied = 0
    for egg in eggs:
        rel_path = egg.get("file", "")
        abs_path = repo_root / rel_path
        if apply_egg(abs_path, egg, dry_run=False):
            applied += 1

    log.info("%d egg(s) applied — commit message: 'chore: a b1e55ing [skip ci]'", applied)
    return 0


if __name__ == "__main__":
    sys.exit(main())
