#!/bin/sh
# Build the Solar System Now AppImage (Linux x86_64).
# Requires: appimagetool (https://github.com/AppImage/appimagetool).
# Produces: packaging/Solar_System_Now-x86_64.AppImage
set -e
ROOT="$(dirname "$(readlink -f "$0")")/.."
APPDIR="$ROOT/packaging/SolarSystemNow.AppDir"

"$ROOT/.venv/bin/pyinstaller" "$ROOT/packaging/ssnow.spec" --noconfirm
cp "$ROOT/dist/ssnow" "$APPDIR/usr/bin/ssnow"

ARCH=x86_64 appimagetool "$APPDIR"
echo "AppImage ready in packaging/"
