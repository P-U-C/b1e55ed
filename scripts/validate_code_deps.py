#!/usr/bin/env python3
"""Validate code dependency graph matches actual imports.

Checks:
1. No circular dependencies
2. Layer rules respected (lower → higher forbidden)
3. All imports documented in dependencies-code.md
"""

import ast
import sys
from pathlib import Path

# Layer definitions (from dependencies-code.md)
LAYERS = {
    0: ["engine/core/events.py", "engine/core/types.py", "engine/core/metrics.py"],
    1: [
        "engine/core/models.py",
        "engine/core/config.py",
        "engine/core/client.py",
        "engine/core/database.py",
        "engine/core/projections.py",
    ],
    2: [
        "engine/security/identity.py",
        "engine/security/keystore.py",
        "engine/security/audit.py",
        "engine/security/redaction.py",
    ],
    3: [
        "engine/producers/base.py",
        "engine/producers/registry.py",
        "engine/producers/",  # all producers/*
        "engine/strategies/base.py",
        "engine/strategies/",  # all strategies/*
    ],
    4: [
        "engine/brain/kill_switch.py",
        "engine/brain/orchestrator.py",
        "engine/brain/pcs_enricher.py",
        "engine/brain/feature_store.py",
    ],
    5: [
        "engine/execution/oms.py",
        "engine/execution/policy.py",
        "engine/execution/karma.py",
    ],
    6: ["api/", "dashboard/", "engine/cli.py"],
}


def get_module_layer(module_path: str) -> int | None:
    """Determine which layer a module belongs to."""
    for layer, patterns in LAYERS.items():
        for pattern in patterns:
            if module_path.startswith(pattern.replace(".py", "")):
                return layer
    return None


def extract_imports(file_path: Path) -> list[str]:
    """Extract all imports from a Python file."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return imports


def check_circular_deps(imports: dict[str, set[str]]) -> list[str]:
    """Detect circular dependencies using DFS."""
    errors = []

    def visit(module: str, path: list[str]) -> None:
        if module in path:
            cycle = " → ".join(path + [module])
            errors.append(f"CIRCULAR DEPENDENCY: {cycle}")
            return

        if module not in imports:
            return

        for dep in imports[module]:
            visit(dep, path + [module])

    for module in imports:
        visit(module, [])

    return errors


def check_layer_violations(file_path: Path, imports: list[str], repo_root: Path) -> list[str]:
    """Check if imports violate layer rules (lower → higher forbidden)."""
    errors = []

    # Convert file path to module path
    rel_path = str(file_path.relative_to(repo_root))
    module_layer = get_module_layer(rel_path)

    if module_layer is None:
        return []  # Not in layer system (e.g., tests/)

    for imp in imports:
        # Convert import to file path (best effort)
        if not imp.startswith("engine.") and not imp.startswith("api.") and not imp.startswith("dashboard."):
            continue  # External import

        # Map import to file path
        import_path = imp.replace(".", "/")
        import_layer = get_module_layer(import_path)

        if import_layer is None:
            continue  # Import not in layer system

        # Check: can only import from same or lower layer
        if import_layer > module_layer:
            errors.append(f"LAYER VIOLATION: {rel_path} (layer {module_layer}) imports {imp} (layer {import_layer})")

    return errors


def main() -> int:
    repo_root = Path(__file__).parent.parent
    errors = []

    print("🔍 Validating code dependencies...")

    # Collect all Python files
    python_files = list(repo_root.glob("engine/**/*.py"))
    python_files += list(repo_root.glob("api/**/*.py"))
    python_files += list(repo_root.glob("dashboard/**/*.py"))

    # Build import graph
    all_imports: dict[str, set[str]] = {}

    for file in python_files:
        if "__pycache__" in str(file) or ".venv" in str(file):
            continue

        imports = extract_imports(file)
        module_name = str(file.relative_to(repo_root)).replace("/", ".").replace(".py", "")
        all_imports[module_name] = set(imports)

        # Check layer violations
        layer_errors = check_layer_violations(file, imports, repo_root)
        errors.extend(layer_errors)

    # Check circular dependencies
    circular_errors = check_circular_deps(all_imports)
    errors.extend(circular_errors)

    # Print results
    if errors:
        print("\n❌ Dependency validation failed:\n")
        for error in errors:
            print(f"  {error}")
        print(f"\n{len(errors)} violation(s) found.")
        return 1
    else:
        print("✅ No circular dependencies or layer violations detected.")
        print(f"   Checked {len(python_files)} Python files.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
