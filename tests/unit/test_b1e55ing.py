"""Tests for scripts/b1e55ing.py — the Easter egg injection hook.

All Anthropic and GitHub API calls are mocked. Tests exercise:
- max_blessings scaling algorithm (logarithmic budget table)
- LLMClient agent and gemini path dispatch
- patch application logic (module_docstring, inline_comment, constant, etc.)
- parse_llm_response caps (per-file and global)
- dry-run mode (no file writes)
- brand filter constants presence in system prompt
- anchor-not-found and invalid-Python guard paths
- workflow "already blessed" check logic
- fork PR skip guard (b1e55ing.yml)
- post-merge already-blessed short-circuit (b1e55ing-merge.yml)
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Make scripts/ importable without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import b1e55ing as hook  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_egg(
    file: str = "engine/core/contributors.py",
    anchor: str = "class ContributorRegistry:",
    placement: str = "after_class",
    content: str = "# Szabo: identity is a property of protocols, not people.",
    tradition: str = "cypherpunk_lineage",
    mode: str = "obscure",
    rationale: str = "Maps to Szabo's work on digital identity.",
) -> dict:
    return {
        "file": file,
        "anchor": anchor,
        "placement": placement,
        "content": content,
        "tradition": tradition,
        "mode": mode,
        "rationale": rationale,
    }


def _tmp_py(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# max_blessings scaling
# ---------------------------------------------------------------------------


def test_max_blessings_scaling() -> None:
    """Verify every documented step of the logarithmic budget table."""
    assert hook.max_blessings(0) == 0  # edge: empty PR

    assert hook.max_blessings(1) == 1  # 1 file  → 1

    assert hook.max_blessings(2) == 2  # 2–4     → 2
    assert hook.max_blessings(3) == 2
    assert hook.max_blessings(4) == 2

    assert hook.max_blessings(5) == 3  # 5–10    → 3
    assert hook.max_blessings(10) == 3

    assert hook.max_blessings(11) == 4  # 11–20   → 4
    assert hook.max_blessings(20) == 4

    assert hook.max_blessings(21) == 5  # 21–50   → 5
    assert hook.max_blessings(50) == 5

    assert hook.max_blessings(51) == 6  # 51+     → 6 (hard cap)
    assert hook.max_blessings(200) == 6
    assert hook.max_blessings(10_000) == 6


def test_max_blessings_negative() -> None:
    """Negative file counts return 0."""
    assert hook.max_blessings(-1) == 0
    assert hook.max_blessings(-99) == 0


# ---------------------------------------------------------------------------
# LLMClient — agent mode (Anthropic)
# ---------------------------------------------------------------------------


def test_llm_client_agent_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent mode calls anthropic.Anthropic with the correct model."""
    # Build a fake anthropic module
    fake_content = SimpleNamespace(text="mock response")
    fake_message = SimpleNamespace(content=[fake_content])
    fake_create = MagicMock(return_value=fake_message)
    fake_client_instance = MagicMock()
    fake_client_instance.messages.create = fake_create
    fake_anthropic_cls = MagicMock(return_value=fake_client_instance)

    fake_anthropic_module = MagicMock()
    fake_anthropic_module.Anthropic = fake_anthropic_cls

    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-agent")

    client = hook.LLMClient(mode="agent", api_key="test-key-agent")
    result = client.complete("system", "user")

    assert result == "mock response"
    fake_anthropic_cls.assert_called_once_with(api_key="test-key-agent")
    call_kwargs = fake_create.call_args
    assert call_kwargs.kwargs["model"] == hook.ANTHROPIC_MODEL
    assert call_kwargs.kwargs["system"] == "system"


def test_llm_client_gemini_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """gemini mode calls google.generativeai with the correct model."""
    fake_response = SimpleNamespace(text="gemini mock response")
    fake_model_instance = MagicMock()
    fake_model_instance.generate_content = MagicMock(return_value=fake_response)
    fake_generative_model_cls = MagicMock(return_value=fake_model_instance)
    fake_configure = MagicMock()

    fake_genai_module = MagicMock()
    fake_genai_module.GenerativeModel = fake_generative_model_cls
    fake_genai_module.configure = fake_configure

    monkeypatch.setitem(sys.modules, "google.generativeai", fake_genai_module)
    # Also mock the top-level google module so the import succeeds
    fake_google = MagicMock()
    fake_google.generativeai = fake_genai_module
    monkeypatch.setitem(sys.modules, "google", fake_google)

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-gemini")

    client = hook.LLMClient(mode="gemini", api_key="test-key-gemini")
    result = client.complete("system", "user")

    assert result == "gemini mock response"
    fake_configure.assert_called_once_with(api_key="test-key-gemini")
    fake_generative_model_cls.assert_called_once_with(hook.GEMINI_MODEL, system_instruction="system")


def test_llm_client_unknown_mode() -> None:
    """Unknown mode raises ValueError at construction time."""
    with pytest.raises(ValueError, match="Unknown mode"):
        hook.LLMClient(mode="openai")


# ---------------------------------------------------------------------------
# Workflow "already blessed" logic
# ---------------------------------------------------------------------------


def test_workflow_skip_if_already_blessed() -> None:
    """The 'already blessed' check searches for 'a b1e55ing' in commit history.

    We test the contract: if the commit message contains the canonical blessing
    string, the workflow step would output already_blessed=true and skip Gemini.
    This verifies the grep string used in easter-eggs.yml matches the actual
    commit message logged by b1e55ing.py.
    """
    # The commit message the workflow greps for
    workflow_grep_string = "a b1e55ing"

    # The commit message b1e55ing.py logs (and that the CI step uses)
    script_source = Path(hook.__file__).read_text(encoding="utf-8")
    assert "chore: a b1e55ing [skip ci]" in script_source

    # The grep string must be a substring of the commit message
    assert workflow_grep_string in "chore: a b1e55ing [skip ci]"

    # The workflow YAML must use the same grep string
    workflow_path = Path(__file__).parent.parent.parent / ".github" / "workflows" / "easter-eggs.yml"
    if workflow_path.exists():
        workflow_src = workflow_path.read_text(encoding="utf-8")
        assert workflow_grep_string in workflow_src
        assert "sleep 600" in workflow_src  # 10-minute wait is present
        assert "already_blessed" in workflow_src  # guard step is wired up


# ---------------------------------------------------------------------------
# Patch application — module_docstring
# ---------------------------------------------------------------------------


def test_apply_module_docstring_egg_no_existing(tmp_path: Path) -> None:
    """Adding a module docstring to a file with no existing docstring."""
    src = "from __future__ import annotations\n\nX = 1\n"
    p = _tmp_py(tmp_path, "mod.py", src)
    egg = _make_egg(
        file=str(p),
        anchor="",
        placement="module_docstring",
        content="# Wei Dai b-money, 1998. Nobody read it until it was too late.",
    )
    result = hook.apply_egg(p, egg)
    assert result is True
    patched = p.read_text()
    assert "Wei Dai" in patched
    ast.parse(patched)


def test_apply_module_docstring_egg_existing_docstring(tmp_path: Path) -> None:
    """Appends content inside an existing module docstring."""
    src = '"""Existing module docstring."""\n\nX = 1\n'
    p = _tmp_py(tmp_path, "mod.py", src)
    egg = _make_egg(
        file=str(p),
        anchor="",
        placement="module_docstring",
        content="# Szabo: bit gold, 2005.",
    )
    result = hook.apply_egg(p, egg)
    assert result is True
    patched = p.read_text()
    assert "Szabo" in patched
    assert "Existing module docstring." in patched
    ast.parse(patched)


# ---------------------------------------------------------------------------
# Patch application — inline_comment / before_function
# ---------------------------------------------------------------------------


def test_apply_inline_comment_egg(tmp_path: Path) -> None:
    """Inserts comment line before the anchor line (before_function style)."""
    src = "def process():\n    pass\n"
    p = _tmp_py(tmp_path, "proc.py", src)
    egg = _make_egg(
        file=str(p),
        anchor="def process():",
        placement="inline_comment",
        content="# Wu wei: the trade that executes itself.",
    )
    result = hook.apply_egg(p, egg)
    assert result is True
    lines = p.read_text().splitlines()
    comment_idx = next(i for i, ln in enumerate(lines) if "Wu wei" in ln)
    def_idx = next(i for i, ln in enumerate(lines) if "def process" in ln)
    assert comment_idx < def_idx
    ast.parse(p.read_text())


def test_apply_before_function_egg(tmp_path: Path) -> None:
    """before_function placement inserts above the matched def line."""
    src = "class Foo:\n    def bar(self):\n        pass\n"
    p = _tmp_py(tmp_path, "foo.py", src)
    egg = _make_egg(
        file=str(p),
        anchor="def bar(self):",
        placement="before_function",
        content="# Ashby's law: only variety absorbs variety.",
    )
    result = hook.apply_egg(p, egg)
    assert result is True
    patched = p.read_text()
    assert "Ashby" in patched
    ast.parse(patched)


# ---------------------------------------------------------------------------
# Patch application — constant
# ---------------------------------------------------------------------------


def test_apply_constant_egg(tmp_path: Path) -> None:
    """Adds a named constant after the anchor line."""
    src = "GENESIS_HASH = '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f'\n\nX = 1\n"
    p = _tmp_py(tmp_path, "genesis.py", src)
    egg = _make_egg(
        file=str(p),
        anchor="GENESIS_HASH",
        placement="constant",
        content="WHITEPAPER_PAGES = 9  # Nine pages changed the topology of trust.",
    )
    result = hook.apply_egg(p, egg)
    assert result is True
    patched = p.read_text()
    assert "WHITEPAPER_PAGES" in patched
    ast.parse(patched)


# ---------------------------------------------------------------------------
# Guard paths
# ---------------------------------------------------------------------------


def test_invalid_python_after_patch_is_skipped(tmp_path: Path) -> None:
    """If patching produces invalid Python, the egg is skipped and file unchanged."""
    src = "X = 1\n"
    p = _tmp_py(tmp_path, "bad.py", src)
    egg = _make_egg(
        file=str(p),
        anchor="X = 1",
        placement="inline_comment",
        content="def (broken syntax",  # will produce SyntaxError
    )
    result = hook.apply_egg(p, egg)
    assert result is False
    assert p.read_text() == src


def test_anchor_not_found_is_skipped(tmp_path: Path) -> None:
    """If the anchor string is not present in the file, egg is skipped gracefully."""
    src = "X = 1\n"
    p = _tmp_py(tmp_path, "nf.py", src)
    egg = _make_egg(
        file=str(p),
        anchor="THIS_ANCHOR_DOES_NOT_EXIST",
        placement="inline_comment",
        content="# should not appear",
    )
    result = hook.apply_egg(p, egg)
    assert result is False
    assert "should not appear" not in p.read_text()


def test_file_not_found_is_skipped(tmp_path: Path) -> None:
    """Missing file returns False without raising."""
    egg = _make_egg(file=str(tmp_path / "ghost.py"), anchor="X", placement="inline_comment", content="# hi")
    result = hook.apply_egg(tmp_path / "ghost.py", egg)
    assert result is False


# ---------------------------------------------------------------------------
# Dry-run produces no file changes
# ---------------------------------------------------------------------------


def test_dry_run_produces_no_file_changes(tmp_path: Path) -> None:
    """apply_egg with dry_run=True returns True but writes nothing."""
    src = "def process():\n    pass\n"
    p = _tmp_py(tmp_path, "proc.py", src)
    egg = _make_egg(
        file=str(p),
        anchor="def process():",
        placement="inline_comment",
        content="# Kelly: bet only what you can afford to re-examine.",
    )
    result = hook.apply_egg(p, egg, dry_run=True)
    assert result is True
    assert p.read_text() == src  # disk unchanged


def test_print_dry_run_header(capsys: pytest.CaptureFixture) -> None:
    """Dry-run output header is branded correctly."""
    hook.print_dry_run([], [], {})
    out = capsys.readouterr().out
    assert "--- a b1e55ing (dry run) ---" in out


# ---------------------------------------------------------------------------
# Brand filter in system prompt
# ---------------------------------------------------------------------------


def test_brand_filter_constants_present() -> None:
    """BRAND_FILTER_PHRASES are all present in SYSTEM_PROMPT."""
    for phrase in hook.BRAND_FILTER_PHRASES:
        assert phrase in hook.SYSTEM_PROMPT, f"Missing brand phrase in SYSTEM_PROMPT: {phrase!r}"


def test_brand_filter_voice_constraints_present() -> None:
    """System prompt enforces key voice constraints."""
    assert "No exclamation marks" in hook.SYSTEM_PROMPT
    assert "Precision carries the energy" in hook.SYSTEM_PROMPT
    assert "forced eggs" in hook.SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# parse_llm_response — per-file and global caps
# ---------------------------------------------------------------------------


def test_max_two_eggs_per_file() -> None:
    """parse_llm_response caps at 2 eggs per file regardless of LLM output."""
    eggs = [
        _make_egg(file="engine/core/a.py", anchor="X", placement="inline_comment", content="# 1"),
        _make_egg(file="engine/core/a.py", anchor="Y", placement="inline_comment", content="# 2"),
        _make_egg(file="engine/core/a.py", anchor="Z", placement="inline_comment", content="# 3 — dropped"),
    ]
    raw = json.dumps({"eggs": eggs, "skipped": [], "skip_reasons": {}})
    result = hook.parse_llm_response(raw)
    kept = [e for e in result["eggs"] if e["file"] == "engine/core/a.py"]
    assert len(kept) == 2


def test_global_budget_cap_enforced() -> None:
    """parse_llm_response respects total_budget even when per-file cap isn't hit."""
    eggs = [
        _make_egg(file="a.py", anchor="X", placement="inline_comment", content="# 1"),
        _make_egg(file="b.py", anchor="X", placement="inline_comment", content="# 2"),
        _make_egg(file="c.py", anchor="X", placement="inline_comment", content="# 3 — over budget"),
    ]
    raw = json.dumps({"eggs": eggs, "skipped": [], "skip_reasons": {}})
    result = hook.parse_llm_response(raw, total_budget=2)
    assert len(result["eggs"]) == 2


def test_parse_llm_response_strips_markdown_fences() -> None:
    """JSON wrapped in ```json fences is handled gracefully."""
    eggs = [_make_egg()]
    payload = {"eggs": eggs, "skipped": [], "skip_reasons": {}}
    raw = f"```json\n{json.dumps(payload)}\n```"
    result = hook.parse_llm_response(raw)
    assert len(result["eggs"]) == 1


def test_parse_llm_response_malformed_json() -> None:
    """Non-JSON response returns empty structure without raising."""
    result = hook.parse_llm_response("I couldn't decide. The files seemed fine.", total_budget=3)
    assert result["eggs"] == []
    assert result["skipped"] == []


# ---------------------------------------------------------------------------
# build_user_prompt includes budget
# ---------------------------------------------------------------------------


def test_build_user_prompt_includes_budget() -> None:
    """The LLM prompt must include the budget number and scaling table."""
    prompt = hook.build_user_prompt(
        pr_title="feat: add signal aggregator",
        pr_body="Aggregates multiple signal producers into a unified score.",
        file_contexts=[{"filename": "engine/core/synthesis.py", "patch": "@@ -1 +1 @@\n+X = 1", "content_preview": "X = 1"}],
        reference_text="# reference stub",
        total_budget=3,
    )
    assert "total budget of 3 blessing" in prompt
    assert "logarithmic" in prompt.lower() or "Logarithmic" in prompt


# ---------------------------------------------------------------------------
# Commit message and log branding
# ---------------------------------------------------------------------------


def test_commit_message_brand_in_source() -> None:
    """The canonical commit message 'chore: a b1e55ing [skip ci]' appears in the script source."""
    src = Path(hook.__file__).read_text(encoding="utf-8")
    assert "chore: a b1e55ing [skip ci]" in src


def test_log_format_brand() -> None:
    """Log format string in b1e55ing.py is branded 'a b1e55ing:'.

    logging.basicConfig is a no-op if pytest has already configured the root
    logger, so we verify the format literal in the module source instead —
    that's the canonical, deterministic location.
    """
    src = Path(hook.__file__).read_text(encoding="utf-8")
    assert '"a b1e55ing: %(message)s"' in src or "'a b1e55ing: %(message)s'" in src, "Expected branded log format string in b1e55ing.py source"


# ---------------------------------------------------------------------------
# Two-workflow design: fork guard + post-merge fallback
# ---------------------------------------------------------------------------


def test_skip_fork_pr() -> None:
    """b1e55ing.yml must have a fork-guard step as the first step in the job.

    Fork PRs can't receive pushes before merge, so we skip the pre-merge
    Gemini path and let b1e55ing-merge.yml handle it post-merge instead.
    We verify:
    - The guard condition references the fork flag correctly
    - The guard exits 0 (doesn't fail the workflow — just skips gracefully)
    - The guard message is informative
    """
    workflow_path = Path(__file__).parent.parent.parent / ".github" / "workflows" / "b1e55ing.yml"
    assert workflow_path.exists(), "b1e55ing.yml not found"
    src = workflow_path.read_text(encoding="utf-8")

    # Guard must check the fork flag on the head repo
    assert "pull_request.head.repo.fork" in src

    # Guard must be a conditional step that exits cleanly (exit 0)
    assert "exit 0" in src

    # Informative message pointing to the fallback
    assert "on-merge fallback" in src or "b1e55ing-merge" in src or "Fork PR" in src

    # The merge workflow must exist as the named fallback
    merge_workflow = Path(__file__).parent.parent.parent / ".github" / "workflows" / "b1e55ing-merge.yml"
    assert merge_workflow.exists(), "b1e55ing-merge.yml not found — fork fallback is dangling"


def test_post_merge_already_blessed_skips() -> None:
    """b1e55ing-merge.yml must gate all expensive steps on 'already_blessed == false'.

    The idempotency contract: if the agent (or a previous Gemini run) already
    added 'a b1e55ing' to the log, neither Python setup, pip install, nor the
    script itself should run. Verifies the workflow YAML structure enforces this.
    """
    merge_path = Path(__file__).parent.parent.parent / ".github" / "workflows" / "b1e55ing-merge.yml"
    assert merge_path.exists(), "b1e55ing-merge.yml not found"
    src = merge_path.read_text(encoding="utf-8")

    # The blessed-check step must exist and output a flag
    assert "already_blessed" in src
    assert "GITHUB_OUTPUT" in src

    # The grep target must match the canonical commit message prefix
    assert "a b1e55ing" in src

    # Every expensive step must be conditional on the flag
    # Count occurrences of the guard condition vs expensive operations
    assert src.count("already_blessed == 'false'") >= 3  # setup-python, install+bless, commit

    # The workflow only fires on merged PRs — not on closed-without-merge
    assert "merged == true" in src

    # Trigger is pull_request closed, not push (must not run on direct commits)
    assert "types: [closed]" in src

    # Commit message is canonical
    assert "chore: a b1e55ing [skip ci]" in src

    # Author identity is consistent with the rest of the system
    assert 'user.name "a b1e55ing"' in src
    assert "bot@permanentupperclass.com" in src
