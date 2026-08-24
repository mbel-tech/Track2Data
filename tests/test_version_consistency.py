"""
Every place that states the application's version must agree with the
single source of truth, ``track2data/_version.py``.

This is a provenance-correctness test, not a tidiness one.
``ProjectManifest.app_version`` is stamped into every exported
``manifest.json`` and into the run README's "App version" row
(exporters/readme.py), so it is part of the reproducibility record a
researcher relies on to say which build produced a dataset. When it was
an independent string literal, bumping the release without also editing
that literal would have made every exported dataset claim it came from
the old version -- silently, with nothing failing.

The packaging files matter for the same reason one step out: the
Windows installer's version and the macOS bundle's
CFBundleShortVersionString are what the OS shows the user about which
build they installed.
"""

from __future__ import annotations

import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from track2data import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_manifest_app_version_defaults_to_the_package_version() -> None:
    """The provenance field stamped into every export."""
    from track2data.core.models import ProjectManifest

    now = datetime.now(tz=UTC)
    manifest = ProjectManifest(project_name="x", created_at=now, updated_at=now)
    assert manifest.app_version == __version__


def test_pyproject_version_matches_package_version() -> None:
    """pyproject.toml declares the version for the built wheel/sdist."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)

    project = pyproject["project"]
    if "version" in project:
        assert project["version"] == __version__
    else:
        # Declared dynamic -- the build backend must be pointed at the
        # same _version.py this test imports from, or "dynamic" would
        # just mean "sourced from somewhere else entirely".
        assert "version" in project.get("dynamic", [])
        assert pyproject["tool"]["hatch"]["version"]["path"] == "track2data/_version.py"


def test_gui_reports_the_package_version() -> None:
    """QApplication.applicationVersion() and the About box.

    Asserted on the module constant rather than by launching Qt: this
    test must stay importable in the headless engine-only environment.
    """
    from app import main_window

    assert __version__ == main_window.APP_VERSION


def test_macos_bundle_version_matches_package_version() -> None:
    """CFBundleShortVersionString in packaging/track2data.spec."""
    spec = (REPO_ROOT / "packaging" / "track2data.spec").read_text(encoding="utf-8")
    match = re.search(r'"CFBundleShortVersionString":\s*(.+?),', spec)
    assert match is not None, "CFBundleShortVersionString not found in the spec"
    value = match.group(1).strip()
    assert not re.fullmatch(
        r'"\d+\.\d+\.\d+"', value
    ), f"CFBundleShortVersionString is a hardcoded literal ({value}); derive it from __version__"


def test_windows_installer_version_is_not_a_hardcoded_literal() -> None:
    """MyAppVersion in packaging/inno_setup.iss.

    Inno Setup cannot import Python, so this one can't reference
    __version__ directly -- it must be left overridable so the release
    workflow can pass the real version in with `iscc /DMyAppVersion=...`.
    A bare hardcoded literal would silently ship a stale version in the
    installer's Add/Remove Programs entry.
    """
    iss = (REPO_ROOT / "packaging" / "inno_setup.iss").read_text(encoding="utf-8")
    match = re.search(r"^\s*#define\s+MyAppVersion\s+(.+)$", iss, re.MULTILINE)
    assert match is not None, "MyAppVersion not found in inno_setup.iss"

    # The invariant is that the release workflow can override it, which
    # means the define must sit behind an #ifndef guard. An unguarded
    # #define wins over `iscc /DMyAppVersion=...` and would silently ship
    # a stale version in Add/Remove Programs.
    assert re.search(
        r"^\s*#ifndef\s+MyAppVersion\b", iss, re.MULTILINE
    ), "MyAppVersion must be guarded with #ifndef so the release workflow can override it"

    # The fallback should not look like a plausible real version, so a
    # local build is obviously a local build.
    fallback = match.group(1).strip().strip('"')
    assert not re.fullmatch(
        r"\d+\.\d+\.\d+", fallback
    ), f"the #ifndef fallback ({fallback}) looks like a real version; make it obviously local"
