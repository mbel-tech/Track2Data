"""
Deprecated re-export shim.

ProjectStore moved to ui/store/project_store.py (D-004, issue #27) once
ui/store/task_runner.py existed for it to own and forward signals from.
Import from there directly in new code; this module is kept only so
existing `from app.state import ProjectStore` call sites keep working.
"""

from __future__ import annotations

from ui.store.project_store import ProjectStore

__all__ = ["ProjectStore"]
