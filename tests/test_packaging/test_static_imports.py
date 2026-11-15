"""
Built-in plugins must be reachable by static imports.

PyInstaller collects code by following ``import`` statements it can read in
the source. A module loaded only through ``__import__(name)`` over a loop
variable is invisible to it, so the frozen app starts without that exporter
and an export silently writes nothing. These tests fail when a built-in
exporter or metric module is not imported by name in its registry package.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _registering_modules(pkg_dir: Path) -> list[str]:
    """Modules that register a plugin at import time (``_register(...)``)."""
    out = []
    for p in sorted(pkg_dir.glob("*.py")):
        if p.stem == "__init__":
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in {"_register", "register"}
            ):
                out.append(p.stem)
                break
    return out


def _static_imports(init_py: Path) -> set[str]:
    tree = ast.parse(init_py.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize("package", ["exporters"])
def test_every_builtin_module_is_statically_imported(package: str) -> None:
    pkg_dir = REPO_ROOT / "track2data" / package
    imported = _static_imports(pkg_dir / "__init__.py")
    modules = _registering_modules(pkg_dir)
    assert modules, f"no built-in modules found in {pkg_dir}"
    missing = [m for m in modules if f"track2data.{package}.{m}" not in imported]
    assert not missing, (
        f"track2data/{package}/__init__.py does not import {missing} by name; "
        "PyInstaller cannot see them and the frozen app would lack them"
    )


def test_exporter_registry_lists_every_builtin() -> None:
    from track2data.exporters import list_exporters

    for name in ("csv_long", "csv_wide", "excel", "feather", "readme"):
        assert name in list_exporters()
