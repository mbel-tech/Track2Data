#!/usr/bin/env bash
# Packages the PyInstaller onefile build (dist/Track2Data) into a Linux
# .AppImage (issue #46). Run from the repo root, after
# `pyinstaller packaging/track2data.spec` has produced dist/Track2Data.
#
# Requires appimagetool -- downloaded fresh each run rather than vendored,
# since it's a large third-party binary and this only ever runs in CI
# (see .github/workflows/release.yml).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f dist/Track2Data ]; then
    echo "error: dist/Track2Data not found -- run the PyInstaller build first" >&2
    exit 1
fi

APPDIR="dist/Track2Data.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp dist/Track2Data "$APPDIR/usr/bin/Track2Data"
cp packaging/icons/icon.png "$APPDIR/track2data.png"
ln -sf usr/bin/Track2Data "$APPDIR/AppRun"

cat > "$APPDIR/track2data.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Track2Data
Comment=Convert idtracker.ai output into analysis-ready behavioural datasets
Exec=Track2Data
Icon=track2data
Categories=Science;
Terminal=false
EOF

if [ ! -x appimagetool ]; then
    curl -fsSL -o appimagetool \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool
fi

ARCH=x86_64 ./appimagetool "$APPDIR" dist/Track2Data-x86_64.AppImage
echo "wrote dist/Track2Data-x86_64.AppImage"
