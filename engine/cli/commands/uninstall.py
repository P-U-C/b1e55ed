"""engine.cli.commands.uninstall

Interactive uninstaller for b1e55ed.

Design constraints:
- stdlib only (no external deps)
- ANSI color codes with TTY detection fallback
- Never silently deletes anything — always asks first
- --yes flag skips confirmations
- --keep-data preserves data + config dirs
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.cli.main import CliContext

# ── ANSI helpers ──────────────────────────────────────────────────────────────

IS_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not IS_TTY:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t: str) -> str:
    return _c("1", t)


def green(t: str) -> str:
    return _c("0;32", t)


def yellow(t: str) -> str:
    return _c("1;33", t)


def red(t: str) -> str:
    return _c("0;31", t)


def dim(t: str) -> str:
    return _c("2", t)


def _ok(msg: str = "") -> str:
    return green("✓") + (f" {msg}" if msg else "")


def _skip(msg: str = "") -> str:
    return dim("–") + (f" {msg}" if msg else "")


def _warn(msg: str = "") -> str:
    return yellow("⚠") + (f" {msg}" if msg else "")


# ── Confirmation helper ───────────────────────────────────────────────────────


def _confirm(prompt: str, *, default: bool, yes_all: bool) -> bool:
    """Ask the user for confirmation. Returns True if confirmed."""
    if yes_all:
        print(f"  {prompt} {dim('[auto-yes]')}")
        return True
    hint = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"  {prompt} {hint}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not raw:
        return default
    return raw in ("y", "yes", "1")


# ── RC file helpers ───────────────────────────────────────────────────────────

_RC_FILES = [
    Path.home() / ".bashrc",
    Path.home() / ".zshrc",
    Path.home() / ".bash_profile",
]

_PATH_MARKER = "# Added by b1e55ed installer"
_LOCAL_BIN_PATTERN = ".local/bin"
_MASTER_PASSWORD_PATTERN = "B1E55ED_MASTER_PASSWORD"


def _remove_lines_from_rc(rc: Path, *, match_patterns: list[str], description: str) -> bool:
    """Remove lines containing any of match_patterns from rc file.

    Also removes the comment line immediately before a matching line if it
    matches _PATH_MARKER. Returns True if any lines were removed.
    """
    if not rc.exists():
        return False

    original = rc.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    new_lines: list[str] = []
    changed = False
    skip_next = False

    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue

        stripped = line.rstrip("\n").rstrip()

        # Check if this is the installer comment marker — if the NEXT line matches
        # one of our patterns, skip both.
        if stripped == _PATH_MARKER and i + 1 < len(lines):
            next_line = lines[i + 1].rstrip("\n").rstrip()
            if any(pat in next_line for pat in match_patterns):
                # Skip this comment and the next line
                skip_next = True
                changed = True
                continue

        if any(pat in stripped for pat in match_patterns):
            changed = True
            continue

        new_lines.append(line)

    if changed:
        rc.write_text("".join(new_lines), encoding="utf-8")
        print(f"  {_ok(f'Removed {description} from {rc}')}")

    return changed


# ── Step implementations ──────────────────────────────────────────────────────


def _step_uv_uninstall(*, yes_all: bool) -> tuple[bool, str]:
    """Uninstall via `uv tool uninstall b1e55ed`. Returns (done, note)."""
    uv = shutil.which("uv")
    if not uv:
        return False, "uv not found in PATH — skipping uv tool uninstall"

    if not _confirm("Remove b1e55ed uv tool installation? (runs: uv tool uninstall b1e55ed)", default=True, yes_all=yes_all):
        return False, "skipped by user"

    try:
        result = subprocess.run(
            [uv, "tool", "uninstall", "b1e55ed"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return True, "uv tool uninstall succeeded"
        else:
            # Not installed as a tool is not a fatal error
            msg = (result.stderr or result.stdout or "").strip()
            return False, f"uv tool uninstall exited {result.returncode}: {msg}"
    except subprocess.TimeoutExpired:
        return False, "uv tool uninstall timed out"
    except Exception as e:  # noqa: BLE001
        return False, f"uv tool uninstall error: {e}"


def _step_remove_binary(*, yes_all: bool) -> tuple[bool, str]:
    """Remove ~/.local/bin/b1e55ed if it still exists."""
    binary = Path.home() / ".local" / "bin" / "b1e55ed"
    if not binary.exists():
        return False, "~/.local/bin/b1e55ed not found (already removed or not installed there)"

    if not _confirm(f"Remove binary {binary}?", default=True, yes_all=yes_all):
        return False, "skipped by user"

    try:
        binary.unlink()
        return True, f"Removed {binary}"
    except Exception as e:  # noqa: BLE001
        return False, f"Could not remove {binary}: {e}"


def _step_remove_dir(path: Path, label: str, *, yes_all: bool, default_confirm: bool) -> tuple[bool, str]:
    """Remove a directory after confirmation."""
    if not path.exists():
        return False, f"{label} ({path}) not found — nothing to remove"

    if not _confirm(f"Remove {label} at {path}?", default=default_confirm, yes_all=yes_all):
        return False, f"skipped by user (kept {path})"

    try:
        shutil.rmtree(path)
        return True, f"Removed {path}"
    except Exception as e:  # noqa: BLE001
        return False, f"Could not remove {path}: {e}"


def _step_remove_path_rc_lines(*, yes_all: bool) -> list[tuple[str, bool]]:
    """Remove PATH export lines from shell rc files."""
    results = []
    for rc in _RC_FILES:
        if not rc.exists():
            continue

        content = rc.read_text(encoding="utf-8")
        if _LOCAL_BIN_PATTERN not in content:
            results.append((str(rc), False))
            continue

        if not _confirm(
            f"Remove ~/.local/bin PATH line from {rc}?",
            default=True,
            yes_all=yes_all,
        ):
            results.append((str(rc), False))
            continue

        changed = _remove_lines_from_rc(
            rc,
            match_patterns=[_LOCAL_BIN_PATTERN],
            description="PATH export line",
        )
        results.append((str(rc), changed))
    return results


def _step_remove_password_rc_lines(*, yes_all: bool) -> list[tuple[str, bool]]:
    """Remove B1E55ED_MASTER_PASSWORD lines from shell rc files."""
    results = []
    for rc in _RC_FILES:
        if not rc.exists():
            continue

        content = rc.read_text(encoding="utf-8")
        if _MASTER_PASSWORD_PATTERN not in content:
            results.append((str(rc), False))
            continue

        if not _confirm(
            f"Remove B1E55ED_MASTER_PASSWORD export from {rc}?",
            default=True,
            yes_all=yes_all,
        ):
            results.append((str(rc), False))
            continue

        changed = _remove_lines_from_rc(
            rc,
            match_patterns=[_MASTER_PASSWORD_PATTERN],
            description="B1E55ED_MASTER_PASSWORD export",
        )
        results.append((str(rc), changed))
    return results


# ── Public entrypoint ─────────────────────────────────────────────────────────


def run_uninstall(ctx: CliContext, args: argparse.Namespace) -> int:
    """Run the interactive b1e55ed uninstaller."""
    yes_all: bool = bool(getattr(args, "yes", False))
    keep_data: bool = bool(getattr(args, "keep_data", False))
    repo_root: Path = ctx.repo_root

    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║" + bold("         b1e55ed uninstaller            ") + "║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    print("  This will remove b1e55ed from your system.")
    if yes_all:
        print(f"  {yellow('--yes mode: all confirmations will be auto-accepted.')}")
    if keep_data:
        print(f"  {yellow('--keep-data mode: data and config directories will be preserved.')}")
    print()

    removed: list[str] = []
    skipped: list[str] = []

    # ── 1. uv tool uninstall ──────────────────────────────────────────────────
    print(bold("  [1/5] uv tool uninstall"))
    done, note = _step_uv_uninstall(yes_all=yes_all)
    if done:
        print(f"  {_ok(note)}")
        removed.append("uv tool (b1e55ed)")
    else:
        print(f"  {_skip(note)}")
        skipped.append(f"uv uninstall: {note}")

    # ── 2. Remove binary ──────────────────────────────────────────────────────
    print()
    print(bold("  [2/5] Remove binary"))
    done, note = _step_remove_binary(yes_all=yes_all)
    if done:
        print(f"  {_ok(note)}")
        removed.append("~/.local/bin/b1e55ed")
    else:
        print(f"  {_skip(note)}")
        skipped.append(f"binary: {note}")

    # ── 3. Remove data / config dirs ─────────────────────────────────────────
    print()
    print(bold("  [3/5] Data and config directories"))

    if keep_data:
        print(f"  {_skip('--keep-data: preserving data and config directories.')}")
        skipped.append("data dir (--keep-data)")
        skipped.append("config dir (--keep-data)")
    else:
        # data/ relative to repo_root (brain.db, etc.)
        data_dir = repo_root / "data"
        done, note = _step_remove_dir(
            data_dir,
            label="local data dir (data/)",
            yes_all=yes_all,
            default_confirm=False,  # default NO for data
        )
        if done:
            print(f"  {_ok(note)}")
            removed.append(str(data_dir))
        else:
            print(f"  {_skip(note)}")
            skipped.append(f"data dir: {note}")

        # .b1e55ed/ (identity + settings)
        config_dir = repo_root / ".b1e55ed"
        done, note = _step_remove_dir(
            config_dir,
            label="config / identity dir (.b1e55ed/)",
            yes_all=yes_all,
            default_confirm=False,  # default NO for identity
        )
        if done:
            print(f"  {_ok(note)}")
            removed.append(str(config_dir))
        else:
            print(f"  {_skip(note)}")
            skipped.append(f"config dir: {note}")

        # ~/.local/share/b1e55ed/ if it exists
        xdg_data = Path.home() / ".local" / "share" / "b1e55ed"
        if xdg_data.exists():
            done, note = _step_remove_dir(
                xdg_data,
                label="XDG data dir (~/.local/share/b1e55ed/)",
                yes_all=yes_all,
                default_confirm=False,
            )
            if done:
                print(f"  {_ok(note)}")
                removed.append(str(xdg_data))
            else:
                print(f"  {_skip(note)}")
                skipped.append(f"XDG data dir: {note}")

        # ~/.config/b1e55ed/ if it exists
        xdg_config = Path.home() / ".config" / "b1e55ed"
        if xdg_config.exists():
            done, note = _step_remove_dir(
                xdg_config,
                label="XDG config dir (~/.config/b1e55ed/)",
                yes_all=yes_all,
                default_confirm=False,
            )
            if done:
                print(f"  {_ok(note)}")
                removed.append(str(xdg_config))
            else:
                print(f"  {_skip(note)}")
                skipped.append(f"XDG config dir: {note}")

    # ── 4. Remove PATH lines from shell rc ────────────────────────────────────
    print()
    print(bold("  [4/5] Shell PATH additions"))
    rc_path_results = _step_remove_path_rc_lines(yes_all=yes_all)
    any_rc_changed = False
    for rc_file, changed in rc_path_results:
        if changed:
            any_rc_changed = True
            removed.append(f"PATH line in {rc_file}")
        elif not Path(rc_file).exists():
            pass  # silently skip missing files
    if not any_rc_changed:
        if not rc_path_results:
            print(f"  {_skip('No shell rc files found.')}")
        else:
            print(f"  {_skip('No PATH lines to remove (already clean or skipped).')}")

    # ── 5. Remove B1E55ED_MASTER_PASSWORD from shell rc ──────────────────────
    print()
    print(bold("  [5/5] Shell password exports"))
    rc_pw_results = _step_remove_password_rc_lines(yes_all=yes_all)
    any_pw_changed = False
    for rc_file, changed in rc_pw_results:
        if changed:
            any_pw_changed = True
            removed.append(f"B1E55ED_MASTER_PASSWORD in {rc_file}")
    if not any_pw_changed:
        if not rc_pw_results:
            print(f"  {_skip('No shell rc files found.')}")
        else:
            print(f"  {_skip('No B1E55ED_MASTER_PASSWORD lines found (already clean or skipped).')}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print(bold(green("  ══════════════════════════════════════")))
    print()
    if removed:
        print(f"  {bold('Removed:')}")
        for item in removed:
            print(f"    {green('✓')} {item}")
    else:
        print(f"  {dim('Nothing was removed.')}")

    if skipped:
        print()
        print(f"  {bold('Skipped / not found:')}")
        for item in skipped:
            print(f"    {dim('–')} {item}")

    print()
    if removed:
        print(f"  {bold(green('Uninstall complete.'))} b1e55ed has been removed.")
    else:
        print(f"  {yellow('Uninstall finished with no changes.')}")

    print()
    print(bold(green("  ══════════════════════════════════════")))
    print()
    return 0
