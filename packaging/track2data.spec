# PyInstaller spec for the Track2Data desktop app (issue #42).
#
# Build:
#   pip install -e ".[ui]" pyinstaller
#   pyinstaller packaging/track2data.spec
#
# Output: dist/Track2Data(.exe on Windows) -- a single-file executable
# bundling the interpreter, PySide6, and every track2data dependency.
# The release workflow (.github/workflows/release.yml, issue #43) runs
# this on each of windows-2022 / macos-26 / ubuntu-22.04.
#
# hiddenimports below cover the one case PyInstaller's static analysis
# can't see on its own: pandas' to_feather()/to_excel() import
# pyarrow/openpyxl lazily at call time, not via a top-level `import` --
# see the matching comments in pyproject.toml's [dev] extra, which
# needed the same explanation for a different reason (test collection).
# scipy itself needs no manual handling: pyinstaller-hooks-contrib ships
# a dedicated scipy hook that already collects exactly what a real
# import graph needs. An earlier version of this spec used
# collect_submodules("scipy") to be safe -- that pulls in scipy's own
# *test suite* (scipy.stats.tests, scipy.special.tests, ...), which
# transitively drags in matplotlib/sympy/tensorflow-hook-probing and
# turned a multi-minute build into a 20+ minute one for no benefit.

import sys
from pathlib import Path

REPO_ROOT = Path(SPECPATH).parent  # noqa: F821 -- SPECPATH is injected by PyInstaller

# Placeholder icon (packaging/icons/) -- a simple generated mark, not final
# branding; swap the source PNG and regenerate the per-OS formats whenever
# real artwork exists. .ico for Windows, .icns for macOS; Linux's AppImage
# step (issue #46) uses the .png directly.
_ICON_ICO = REPO_ROOT / "packaging" / "icons" / "icon.ico"
_ICON_ICNS = REPO_ROOT / "packaging" / "icons" / "icon.icns"
if sys.platform == "win32":
    _icon = str(_ICON_ICO) if _ICON_ICO.exists() else None
elif sys.platform == "darwin":
    _icon = str(_ICON_ICNS) if _ICON_ICNS.exists() else None
else:
    _icon = None

hidden_imports = [
    "pyarrow",
    "openpyxl",
]

# track2data has no dependency on any of these -- none appear anywhere in
# track2data/, app/, or ui/. They showed up in an early local build anyway
# (confirmed via build/track2data/xref-track2data.html): PyInstaller's
# matplotlib-backend-discovery hook scans every already-collected module
# for `matplotlib.use()` calls once matplotlib itself is pulled in by
# something else's *optional* integration (pandas.plotting), and that
# scan is what dragged in sympy/torch/tensorflow-probing on a dev
# machine that happens to have them globally installed -- a fresh CI
# environment installing only pyproject.toml's declared extras wouldn't
# have them to pull in at all, but excluding them explicitly is cheap
# insurance against a many-hundred-MB binary on any environment where
# they're merely importable, not actually used.
excludes = ["matplotlib", "sympy", "torch", "tensorflow", "IPython", "jupyter"]

a = Analysis(  # noqa: F821 -- Analysis/PYZ/EXE are injected by PyInstaller
    [str(REPO_ROOT / "app" / "main.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Track2Data",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

# macOS needs a real .app bundle (not just the raw onefile executable) for
# `.dmg` packaging (issue #45) -- Finder, Gatekeeper, and hdiutil all expect
# one. EXE() alone is sufficient on Windows/Linux, where the release
# workflow (issue #43) wraps the executable directly (Inno Setup / AppImage).
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        exe,
        name="Track2Data.app",
        icon=_icon,
        bundle_identifier="io.track2data.app",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
