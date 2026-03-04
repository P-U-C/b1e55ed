"""Tests for scripts/b1e55ing.py session-driven modes."""

from __future__ import annotations

import ast
import json
import subprocess
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


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@b1e55ed.test"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "b1e55ed-test"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_root, check=True, capture_output=True)


def _apply_payload(tmp_path: Path, payload: dict[str, object], repo_root: Path) -> int:
    eggs_file = tmp_path / "eggs.json"
    eggs_file.write_text(json.dumps(payload), encoding="utf-8")
    return hook.main(
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

    assert {"pr_number", "pr_title", "budget", "files", "reference", "existing_eggs"}.issubset(context.keys())
    assert context["pr_number"] == 211
    assert context["pr_title"] == "feat(p0a): add event flow"
    assert context["reference"] == "reference text"
    assert context["budget"] == hook.max_blessings(1)
    assert len(context["files"]) == 1
    assert context["files"][0]["path"] == "engine/core/events.py"
    assert "def handle_event" in context["files"][0]["content"]
    assert context["existing_eggs"]["engine/core/events.py"] == []


def test_dump_context_includes_existing_eggs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    target_file = repo_root / "engine" / "core" / "events.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("def handle_event():\n    return 1\n", encoding="utf-8")

    ref = repo_root / "docs" / "EASTER_EGG_REFERENCE.md"
    ref.parent.mkdir(parents=True)
    ref.write_text("reference text", encoding="utf-8")

    manifest_path = repo_root / "docs" / "b1e55ing-manifest.json"
    manifest = {
        "version": "1",
        "eggs": [
            {
                "id": "egg_1234abcd",
                "file": "engine/core/events.py",
                "anchor": "def handle_event():",
                "tradition": "ebbinghaus-forgetting-curve",
                "content": "# Ebbinghaus...",
                "placement": "before_function",
                "pr_number": 200,
                "applied_at": "2026-03-02T21:00:00Z",
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(hook, "REFERENCE_PATH", ref)
    monkeypatch.setattr(hook, "fetch_pr", lambda _pr, _tok: {"title": "feat: events", "body": "body text"})
    monkeypatch.setattr(
        hook,
        "fetch_pr_files",
        lambda _pr, _tok: [
            {
                "filename": "engine/core/events.py",
                "status": "modified",
                "patch": "@@ -1 +1 @@\n+def handle_event():\n+    return 1",
            }
        ],
    )

    context = hook.dump_context(211, "gh-token")

    assert "existing_eggs" in context
    assert len(context["existing_eggs"]["engine/core/events.py"]) == 1
    assert context["existing_eggs"]["engine/core/events.py"][0]["tradition"] == "ebbinghaus-forgetting-curve"


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


def test_removal_strips_comment_line(tmp_path: Path) -> None:
    path = tmp_path / "events.py"
    path.write_text("def handle_event():\n    # Ebbinghaus...\n    return 1\n", encoding="utf-8")

    removed = hook.apply_removal(path, {"content": "# Ebbinghaus...", "tradition": "ebbinghaus-forgetting-curve"})

    assert removed is True
    patched = path.read_text(encoding="utf-8")
    assert "# Ebbinghaus..." not in patched
    assert "return 1" in patched
    ast.parse(patched)


# ---------------------------------------------------------------------------
# main() modes
# ---------------------------------------------------------------------------


def test_main_apply_eggs_mode_applies_from_json(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    file_path = repo_root / "engine" / "core" / "events.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("def handle_event():\n    return 1\n", encoding="utf-8")

    _init_git_repo(repo_root)

    payload = {
        "eggs": [
            _make_egg(
                file="engine/core/events.py",
                anchor="def handle_event():",
                placement="inline_comment",
                content="# Channel capacity sets the boundary of certainty.",
            )
        ],
        "removals": [],
        "skipped": [],
        "skip_reasons": {},
    }

    rc = _apply_payload(tmp_path, payload, repo_root)

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
        "removals": [],
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


def test_manifest_created_on_first_apply(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    file_path = repo_root / "engine" / "core" / "events.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("def handle_event():\n    return 1\n", encoding="utf-8")
    _init_git_repo(repo_root)

    payload = {
        "eggs": [
            _make_egg(
                file="engine/core/events.py",
                anchor="def handle_event():",
                content="# First blessing.",
                tradition="first-tradition",
            )
        ],
        "removals": [],
        "skipped": [],
        "skip_reasons": {},
    }

    rc = _apply_payload(tmp_path, payload, repo_root)

    manifest_path = repo_root / "docs" / "b1e55ing-manifest.json"
    assert rc == 0
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == "1"


def test_manifest_records_applied_egg(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    file_path = repo_root / "engine" / "core" / "events.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("def handle_event():\n    return 1\n", encoding="utf-8")
    _init_git_repo(repo_root)

    egg = _make_egg(
        file="engine/core/events.py",
        anchor="def handle_event():",
        content="# Audit me.",
        tradition="audit-tradition",
        placement="before_function",
    )
    payload = {
        "eggs": [egg],
        "removals": [],
        "skipped": [],
        "skip_reasons": {},
    }

    rc = _apply_payload(tmp_path, payload, repo_root)

    assert rc == 0
    manifest_path = repo_root / "docs" / "b1e55ing-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["eggs"]) == 1

    entry = manifest["eggs"][0]
    assert entry["id"] == hook.manifest_entry_id("engine/core/events.py", "def handle_event():", "audit-tradition")
    assert entry["file"] == "engine/core/events.py"
    assert entry["anchor"] == "def handle_event():"
    assert entry["tradition"] == "audit-tradition"
    assert entry["content"] == "# Audit me."
    assert entry["placement"] == "before_function"
    assert entry["pr_number"] == 211
    assert entry["applied_at"].endswith("Z")


def test_duplicate_tradition_in_same_file_is_skipped(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    file_path = repo_root / "engine" / "core" / "events.py"
    file_path.parent.mkdir(parents=True)
    before = "def handle_event():\n    return 1\n"
    file_path.write_text(before, encoding="utf-8")
    _init_git_repo(repo_root)

    manifest_path = repo_root / "docs" / "b1e55ing-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing_entry = {
        "id": hook.manifest_entry_id("engine/core/events.py", "def handle_event():", "dupe-tradition"),
        "file": "engine/core/events.py",
        "anchor": "def handle_event():",
        "tradition": "dupe-tradition",
        "content": "# Existing blessing.",
        "placement": "before_function",
        "pr_number": 200,
        "applied_at": "2026-03-02T21:00:00Z",
    }
    manifest_path.write_text(json.dumps({"version": "1", "eggs": [existing_entry]}, indent=2), encoding="utf-8")

    payload = {
        "eggs": [
            _make_egg(
                file="engine/core/events.py",
                anchor="def handle_event():",
                content="# New duplicate blessing.",
                tradition="dupe-tradition",
            )
        ],
        "removals": [],
        "skipped": [],
        "skip_reasons": {},
    }

    rc = _apply_payload(tmp_path, payload, repo_root)

    assert rc == 0
    assert file_path.read_text(encoding="utf-8") == before
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["eggs"]) == 1
    assert manifest["eggs"][0]["content"] == "# Existing blessing."


def test_removal_updates_manifest(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    file_path = repo_root / "engine" / "core" / "events.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("def handle_event():\n    # Ebbinghaus...\n    return 1\n", encoding="utf-8")
    _init_git_repo(repo_root)

    manifest_path = repo_root / "docs" / "b1e55ing-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "version": "1",
                "eggs": [
                    {
                        "id": hook.manifest_entry_id(
                            "engine/core/events.py",
                            "def handle_event():",
                            "ebbinghaus-forgetting-curve",
                        ),
                        "file": "engine/core/events.py",
                        "anchor": "def handle_event():",
                        "tradition": "ebbinghaus-forgetting-curve",
                        "content": "# Ebbinghaus...",
                        "placement": "before_function",
                        "pr_number": 201,
                        "applied_at": "2026-03-02T21:00:00Z",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = {
        "eggs": [],
        "removals": [
            {
                "file": "engine/core/events.py",
                "content": "# Ebbinghaus...",
                "tradition": "ebbinghaus-forgetting-curve",
            }
        ],
        "skipped": [],
        "skip_reasons": {},
    }

    rc = _apply_payload(tmp_path, payload, repo_root)

    assert rc == 0
    patched = file_path.read_text(encoding="utf-8")
    assert "# Ebbinghaus..." not in patched

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["eggs"] == []


# ---------------------------------------------------------------------------
# LLM references removed
# ---------------------------------------------------------------------------


def test_script_contains_no_llm_client_symbols() -> None:
    src = Path(hook.__file__).read_text(encoding="utf-8")
    assert "LLMClient" not in src
    assert "ANTHROPIC_MODEL" not in src
    assert "XAI_MODEL" not in src
