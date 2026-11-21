#!/bin/sh
# Build the Solar System Now AppImage (Linux x86_64).
#
# Usage: packaging/build_appimage.sh
#   - builds the PyInstaller one-file bundle (dist/ssnow)
#   - assembles packaging/SolarSystemNow.AppDir
#   - produces packaging/Solar_System_Now-x86_64.AppImage
#
# appimagetool is downloaded on demand into packaging/tools/ when absent, and
# is executed with APPIMAGE_EXTRACT_AND_RUN=1 so FUSE is not required.
set -e
ROOT="$(dirname "$(readlink -f "$0")")/.."
APPDIR="$ROOT/packaging/SolarSystemNow.AppDir"
TOOLS="$ROOT/packaging/tools"
APPIMAGETOOL="$TOOLS/appimagetool-x86_64.AppImage"

mkdir -p "$TOOLS" "$APPDIR/usr/bin"

# 1. Bundle.
if [ -x "$ROOT/.venv/bin/pyinstaller" ]; then
    PYINSTALLER="$ROOT/.venv/bin/pyinstaller"
else
    PYINSTALLER="$(command -v pyinstaller || true)"
fi
if [ -z "$PYINSTALLER" ]; then
    echo "pyinstaller not found: pip install pyinstaller (or create .venv)" >&2
    exit 1
fi
"$PYINSTALLER" "$ROOT/packaging/ssnow.spec" --noconfirm
cp "$ROOT/dist/ssnow" "$APPDIR/usr/bin/ssnow"

# 2. AppDir skeleton (icon, desktop entry, AppRun launcher).
cp "$ROOT/packaging/ssnow.svg" "$APPDIR/ssnow.svg"

cat > "$APPDIR/ssnow.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Solar System Now
Comment=Real-data Earth and space-weather dashboard
Exec=ssnow
Icon=ssnow
Categories=Science;Education;
Terminal=false
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QTWEBENGINE_DISABLE_SANDBOX=1
exec "$HERE/usr/bin/ssnow" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# 3. appimagetool (cached; downloaded only when missing).
if [ ! -x "$APPIMAGETOOL" ]; then
    echo "Downloading appimagetool..."
    curl -fsSL -o "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

# 4. Package (works without FUSE via extract-and-run).
cd "$ROOT/packaging"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "Solar_System_Now-x86_64.AppImage"
echo "AppImage ready: packaging/Solar_System_Now-x86_64.AppImage"
