"""Tests for scripts/b1e55ing.py session-driven modes."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

# Make scripts/ importable without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import b1e55ing as hook  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_egg(
    file: str,
    anchor: str,
    placement: str = "inline_comment",
    content: str = "# Information is compression with intent.",
    tradition: str = "information-theory",
    mode: str = "obscure",
    rationale: str = "One-line rationale.",
) -> dict[str, str]:
    return {
        "file": file,
        "anchor": anchor,
        "placement": placement,
        "content": content,
        "tradition": tradition,
        "mode": mode,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# max_blessings scaling
# ---------------------------------------------------------------------------


def test_max_blessings_scaling() -> None:
    assert hook.max_blessings(0) == 0
    assert hook.max_blessings(1) == 1
    assert hook.max_blessings(4) == 2
    assert hook.max_blessings(5) == 3
    assert hook.max_blessings(10) == 3
    assert hook.max_blessings(11) == 4
    assert hook.max_blessings(21) == 5
    assert hook.max_blessings(51) == 6


# ---------------------------------------------------------------------------
# dump_context mode
# ---------------------------------------------------------------------------


def test_dump_context_returns_required_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target_file = repo_root / "engine" / "core" / "events.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("def handle_event():\n    return 1\n", encoding="utf-8")

    ref = repo_root / "docs" / "EASTER_EGG_REFERENCE.md"
    ref.parent.mkdir(parents=True)
    ref.write_text("reference text", encoding="utf-8")

    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(hook, "REFERENCE_PATH", ref)
    monkeypatch.setattr(hook, "fetch_pr", lambda _pr, _tok: {"title": "feat(p0a): add event flow", "body": "body text"})
    monkeypatch.setattr(
        hook,
        "fetch_pr_files",
        lambda _pr, _tok: [
            {
                "filename": "engine/core/events.py",
                "status": "modified",
                "patch": "@@ -1 +1 @@\n+def handle_event():\n+    return 1",
            },
            {"filename": "README.md", "status": "modified", "patch": "@@"},
            {"filename": "engine/core/old.py", "status": "removed", "patch": "@@"},
        ],
    )

    context = hook.dump_context(211, "gh-token")

    assert {"pr_number", "pr_title", "budget", "files", "reference"}.issubset(context.keys())
    assert context["pr_number"] == 211
    assert context["pr_title"] == "feat(p0a): add event flow"
    assert context["reference"] == "reference text"
    assert context["budget"] == hook.max_blessings(1)
    assert len(context["files"]) == 1
    assert context["files"][0]["path"] == "engine/core/events.py"
    assert "def handle_event" in context["files"][0]["content"]


# ---------------------------------------------------------------------------
# apply_egg behavior (existing apply logic)
# ---------------------------------------------------------------------------


def test_apply_egg_inline_comment(tmp_path: Path) -> None:
    path = tmp_path / "events.py"
    path.write_text("def handle_event():\n    return 1\n", encoding="utf-8")

    egg = _make_egg(file=str(path), anchor="def handle_event():")
    applied = hook.apply_egg(path, egg)

    assert applied is True
    patched = path.read_text(encoding="utf-8")
    assert "Information is compression with intent." in patched
    ast.parse(patched)


def test_apply_egg_invalid_python_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "events.py"
    original = "X = 1\n"
    path.write_text(original, encoding="utf-8")

    egg = _make_egg(file=str(path), anchor="X = 1", content="def (broken syntax")
    applied = hook.apply_egg(path, egg)

    assert applied is False
    assert path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# main() modes
# ---------------------------------------------------------------------------


def test_main_apply_eggs_mode_applies_from_json(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    file_path = repo_root / "engine" / "core" / "events.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("def handle_event():\n    return 1\n", encoding="utf-8")

    payload = {
        "eggs": [
            _make_egg(
                file="engine/core/events.py",
                anchor="def handle_event():",
                placement="inline_comment",
                content="# Channel capacity sets the boundary of certainty.",
            )
        ],
        "skipped": [],
        "skip_reasons": {},
    }
    eggs_file = tmp_path / "eggs.json"
    eggs_file.write_text(json.dumps(payload), encoding="utf-8")

    rc = hook.main(
        [
            "--pr-number",
            "211",
            "--github-token",
            "gh-token",
            "--mode",
            "apply-eggs",
            "--eggs-file",
            str(eggs_file),
            "--repo-root",
            str(repo_root),
        ]
    )

    assert rc == 0
    assert "Channel capacity sets the boundary of certainty." in file_path.read_text(encoding="utf-8")


def test_main_dry_run_mode_does_not_write(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    file_path = repo_root / "engine" / "core" / "events.py"
    file_path.parent.mkdir(parents=True)
    before = "def handle_event():\n    return 1\n"
    file_path.write_text(before, encoding="utf-8")

    payload = {
        "eggs": [
            _make_egg(
                file="engine/core/events.py",
                anchor="def handle_event():",
                placement="inline_comment",
                content="# Dry-run should never write this.",
            )
        ],
        "skipped": [],
        "skip_reasons": {},
    }
    eggs_file = tmp_path / "eggs.json"
    eggs_file.write_text(json.dumps(payload), encoding="utf-8")

    rc = hook.main(
        [
            "--pr-number",
            "211",
            "--github-token",
            "gh-token",
            "--mode",
            "dry-run",
            "--eggs-file",
            str(eggs_file),
            "--repo-root",
            str(repo_root),
        ]
    )

    assert rc == 0
    assert file_path.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# LLM references removed
# ---------------------------------------------------------------------------


def test_script_contains_no_llm_client_symbols() -> None:
    src = Path(hook.__file__).read_text(encoding="utf-8")
    assert "LLMClient" not in src
    assert "ANTHROPIC_MODEL" not in src
    assert "XAI_MODEL" not in src
