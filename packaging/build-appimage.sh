#!/usr/bin/env bash
# Build "VaultLeaf Backup" as an AppImage.
#
# The AppImage bundles the app code and ships a small launcher that uses
# your system's python3 + GTK (python3-gi / GTK4).  That keeps it light
# and reliable on this Ubuntu/GNOME machine while still giving you a
# single double-clickable, icon-and-menu aware AppImage.
#
# Prerequisites: bash, curl.  (python3 + PyGObject + GTK4 on the host.)
# Usage:   bash packaging/build-appimage.sh
# Output:  VaultLeafBackup-x86_64.AppImage in the project root.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
APP_NAME="VaultLeafBackup"
ARCH="x86_64"
APPDIR="$HERE/build/AppDir"
OUT="$ROOT/$APP_NAME-$ARCH.AppImage"

echo "==> Preparing AppDir: $APPDIR"
rm -rf "$APPDIR"
mkdir -p \
    "$APPDIR/usr/lib/my-backups" \
    "$APPDIR/usr/bin" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps"

# 1) App code (keep the package directory so `python3 -m my_backups` works)
cp -R "$ROOT/my_backups" "$APPDIR/usr/lib/my-backups/"

# 2) Launcher inside the AppImage + AppRun entry point
cat > "$APPDIR/usr/bin/my-backups" <<'SH'
#!/bin/sh
APP_LIB="$(CDPATH= cd -- "$(dirname "$0")/../lib/my-backups" && pwd)"
export PYTHONPATH="$APP_LIB${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m my_backups "$@"
SH
chmod +x "$APPDIR/usr/bin/my-backups"
cp "$HERE/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

# 3) Desktop entry + icon
#    appimagetool requires a .desktop file at the AppDir root, and the
#    system menu entry goes under usr/share/applications.
cp "$HERE/my-backups.desktop" "$APPDIR/my-backups.desktop"
cp "$HERE/my-backups.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT/my_backups/data/icon.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/my-backups.svg"
cp "$ROOT/my_backups/data/icon.svg" "$APPDIR/my-backups.svg"
cp "$ROOT/my_backups/data/icon.svg" "$APPDIR/.DirIcon"

# 4) appimagetool (downloaded once into packaging/)
TOOL="$HERE/appimagetool-$ARCH.AppImage"
if [ ! -f "$TOOL" ]; then
    echo "==> Downloading appimagetool…"
    curl -fL -o "$TOOL" \
        "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi

# 5) Build
echo "==> Building $OUT"
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"

echo ""
echo "==> Done: $OUT"
echo "    Run it:            chmod +x \"$OUT\" && \"$OUT\""
echo "    Install (optional): sudo mkdir -p /opt && sudo cp \"$OUT\" /opt/ && "
echo "                        ln -s \"/opt/$(basename "$OUT")\" ~/.local/bin/my-backups"
