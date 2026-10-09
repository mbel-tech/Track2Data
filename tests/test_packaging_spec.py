"""
The frozen build has to carry the files the app reads at start-up.

PyInstaller collects code by following imports, so a data file that is only
opened at run time is left out unless the spec lists it. ``app/theme.py``
reads ``app/resources/track2data-<theme>.qss`` the moment the main window is
built; with ``datas=[]`` the released Linux and macOS binaries died on start
with ``FileNotFoundError`` (caught by the release workflow's smoke test, not by
any test that runs from source, where the files simply exist).
"""

from __future__ import annotations

from pathlib import Path

import app.theme as theme

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = REPO_ROOT / "packaging" / "track2data.spec"


def test_spec_bundles_the_app_resources_folder() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert '"app" / "resources"' in text, "the spec no longer points at app/resources"
    assert '"app/resources"' in text, "app/resources must keep its path inside the bundle"


def test_every_stylesheet_the_theme_loads_lives_in_the_bundled_folder() -> None:
    """The folder named in the spec is the one theme.py reads from."""
    assert theme.RESOURCES == REPO_ROOT / "app" / "resources"
    for name in ("light", "dark"):
        assert (theme.RESOURCES / f"track2data-{name}.qss").is_file()
