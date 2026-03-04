#!/usr/bin/env python3
"""Validate code dependency graph matches actual imports.

Checks:
1. No circular dependencies in internal modules
2. Layer rules respected (lower layers may not import from higher layers)
3. Basic structural sanity
"""

import ast
import sys
from pathlib import Path

# Layer definitions — lower layer number = more foundational.
# A module may only import from its own layer or lower layers.
LAYERS: dict[int, list[str]] = {
    0: [
        # Primitives — no internal dependencies
        "engine/core/events.py",
        "engine/core/types.py",
        "engine/core/metrics.py",
        "engine/core/exceptions.py",
        "engine/core/time.py",
        "engine/core/allowlists.py",
        "engine/core/permissions.py",
        "engine/core/policy.py",
        "engine/security/ssrf.py",  # standalone, no internal deps
    ],
    1: [
        # Core models, config, DB, projections
        "engine/core/models.py",
        "engine/core/config.py",
        "engine/core/client.py",
        "engine/core/database.py",
        "engine/core/projections.py",
        "engine/core/cache.py",
        "engine/core/rate_limiter.py",
        "engine/core/webhooks.py",
        "engine/core/contributors.py",
        "engine/core/scoring.py",
        "engine/core/ingestion.py",
    ],
    2: [
        # Security — depends on core
        "engine/security/",
    ],
    3: [
        # Data producers, backtest strategies, social collectors
        "engine/producers/",
        "engine/backtest/strategies/",
        "engine/social/collectors/",
        "engine/social/extractors/",
        "engine/social/filters/",
        "engine/social/scoring/",
        "engine/social/config.py",
        "engine/tradfi/",
    ],
    4: [
        # Brain, backtest engine, social pipeline
        "engine/brain/",
        "engine/backtest/engine.py",
        "engine/backtest/io.py",
        "engine/backtest/regime.py",
        "engine/backtest/simulator.py",
        "engine/backtest/stats.py",
        "engine/backtest/sweep.py",
        "engine/backtest/validation.py",
        "engine/backtest/walkforward.py",
        "engine/social/pipeline.py",
    ],
    5: [
        # Execution, integration, integrations, oracle primitives
        "engine/execution/",
        "engine/integration/",
        "engine/integrations/",
        "engine/core/provenance.py",
        "engine/core/oracle_query_log.py",
    ],
    6: [
        # Interface layer — API, dashboard, CLI
        "api/",
        "dashboard/",
        "engine/cli/",
        "engine/cli_keys.py",
    ],
}


def get_module_layer(module_path: str) -> int | None:
    """Return the layer for a module path, or None if not in the layer system."""
    for layer, patterns in LAYERS.items():
        for pattern in patterns:
            if pattern.endswith("/"):
                if module_path.startswith(pattern):
                    return layer
            else:
                base = pattern.removesuffix(".py")
                if module_path in (pattern, base) or module_path.startswith(base + "."):
                    return layer
    return None


def extract_imports(file_path: Path) -> list[str]:
    """Extract module-level imports from a Python file.

    Lazy imports inside functions/methods are intentional (e.g. optional
    integrations using dependency injection) and are excluded from layer
    violation checks.
    """
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []
    # Only walk the top-level body — skip function/class/if bodies
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        # Also catch imports inside top-level `if TYPE_CHECKING:` blocks
        elif isinstance(node, ast.If):
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Import):
                    for alias in subnode.names:
                        imports.append(alias.name)
                elif isinstance(subnode, ast.ImportFrom) and subnode.module:
                    imports.append(subnode.module)
    return imports


def _import_to_path(imp: str) -> str | None:
    """Convert a dotted import string to a file-path prefix, or None if external."""
    if not (imp.startswith("engine.") or imp.startswith("api.") or imp.startswith("dashboard.")):
        return None
    return imp.replace(".", "/")


def check_layer_violations(
    file_path: Path,
    imports: list[str],
    repo_root: Path,
) -> list[str]:
    errors: list[str] = []
    rel_path = str(file_path.relative_to(repo_root))
    module_layer = get_module_layer(rel_path)

    if module_layer is None:
        return []

    for imp in imports:
        import_path = _import_to_path(imp)
        if import_path is None:
            continue
        import_layer = get_module_layer(import_path)
        if import_layer is None:
            continue
        if import_layer > module_layer:
            errors.append(f"LAYER VIOLATION: {rel_path} (layer {module_layer}) imports {imp} (layer {import_layer})")
    return errors


# Königsberg, 1736. Euler proved you cannot cross all seven bridges exactly once.
# Graph theory was born from a walk that couldn't be taken.
# Every cycle detector since is a footnote to that proof.
def check_circular_deps(imports: dict[str, set[str]]) -> list[str]:
    """Detect circular dependencies using iterative DFS."""
    errors: list[str] = []
    visited: set[str] = set()

    def visit(module: str, path: list[str]) -> None:
        if module in path:
            cycle = " → ".join(path[path.index(module) :] + [module])
            if cycle not in errors:
                errors.append(f"CIRCULAR DEPENDENCY: {cycle}")
            return
        if module in visited or module not in imports:
            return
        for dep in imports[module]:
            visit(dep, path + [module])
        visited.add(module)

    for module in imports:
        visit(module, [])
    return errors


def main() -> int:
    repo_root = Path(__file__).parent.parent
    errors: list[str] = []

    print("🔍 Validating code dependencies...")

    python_files = [
        f
        for f in (list(repo_root.glob("engine/**/*.py")) + list(repo_root.glob("api/**/*.py")) + list(repo_root.glob("dashboard/**/*.py")))
        if "__pycache__" not in str(f) and ".venv" not in str(f)
    ]

    all_imports: dict[str, set[str]] = {}

    for file in python_files:
        raw_imports = extract_imports(file)
        module_name = str(file.relative_to(repo_root)).replace("/", ".").removesuffix(".py")
        internal_imports = {i for i in raw_imports if i.startswith("engine.") or i.startswith("api.") or i.startswith("dashboard.")}
        all_imports[module_name] = internal_imports
        errors.extend(check_layer_violations(file, raw_imports, repo_root))

    errors.extend(check_circular_deps(all_imports))

    if errors:
        print("\n❌ Dependency validation failed:\n")
        for err in errors:
            print(f"  {err}")
        print(f"\n{len(errors)} violation(s) found.")
        return 1

    print("✅ No circular dependencies or layer violations detected.")
    print(f"   Checked {len(python_files)} Python files across 7 layers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
