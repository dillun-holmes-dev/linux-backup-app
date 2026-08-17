#!/usr/bin/env bash
# Build a self-contained VaultLeaf Backup AppImage.
#
# Runtime dependencies are bundled: Python, PyGObject, GTK4, restic and rclone.
# Build dependencies are intentionally taken from the build machine. For broad
# distro compatibility, build on the oldest Linux release you plan to support.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
APP_NAME="VaultLeafBackup"
APP_ID="io.github.dillunholmes.VaultLeafBackup"
ARCH="${ARCH:-$(uname -m)}"
APPDIR="$HERE/build/AppDir"
OUT="$ROOT/$APP_NAME-$ARCH.AppImage"
MINISIGN_VERSION="0.12"
MINISIGN_ARCHIVE_SHA256="9a599b48ba6eb7b1e80f12f36b94ceca7c00b7a5173c95c3efc88d9822957e73"

case "$ARCH" in
    x86_64|aarch64) ;;
    *) echo "Unsupported architecture: $ARCH" >&2; exit 2 ;;
esac

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Build dependency '$1' is missing." >&2
        exit 2
    }
}
for command in python3 curl ldd file find cp; do need "$command"; done

python3 - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
print(f"==> Bundling Python with GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}")
PY

PYTHON="$(readlink -f "$(command -v python3)")"
PY_VERSION="$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_STDLIB="$($PYTHON -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"
GI_DIR="$($PYTHON -c 'import gi, pathlib; print(pathlib.Path(gi.__file__).parent)')"
MULTIARCH="$($PYTHON -c 'import sysconfig; print(sysconfig.get_config_var("MULTIARCH") or "")')"

GTK_LIB="$(ldconfig -p | awk '/libgtk-4\.so\.1 / {print $NF; exit}')"
TYPELIB_DIR="/usr/lib/$MULTIARCH/girepository-1.0"
[ -n "$GTK_LIB" ] && [ -f "$GTK_LIB" ] || { echo "GTK4 runtime not found." >&2; exit 2; }
[ -d "$TYPELIB_DIR" ] || TYPELIB_DIR="/usr/lib/girepository-1.0"
[ -d "$TYPELIB_DIR" ] || { echo "GObject typelibs not found." >&2; exit 2; }

echo "==> Preparing self-contained AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/my-backups" \
    "$APPDIR/usr/lib/python3/dist-packages" "$APPDIR/usr/lib/girepository-1.0" \
    "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps"

cp -a "$ROOT/src/my_backups" "$APPDIR/usr/lib/my-backups/"
cp -aL "$PYTHON" "$APPDIR/usr/bin/python3"
cp -a "$PY_STDLIB" "$APPDIR/usr/lib/python$PY_VERSION"
cp -a "$GI_DIR" "$APPDIR/usr/lib/python3/dist-packages/gi"
cp -a "$TYPELIB_DIR/." "$APPDIR/usr/lib/girepository-1.0/"
cp -aL "$(command -v restic)" "$APPDIR/usr/bin/restic"
cp -aL "$(command -v rclone)" "$APPDIR/usr/bin/rclone"
cp -aL "$GTK_LIB" "$APPDIR/usr/lib/$(basename "$GTK_LIB")"

# Pin and hash-check the official static verifier used for secure updates.
MINISIGN_ARCHIVE="$HERE/minisign-$MINISIGN_VERSION-linux.tar.gz"
if [ ! -f "$MINISIGN_ARCHIVE" ]; then
    echo "==> Downloading minisign $MINISIGN_VERSION"
    curl --proto '=https' --tlsv1.2 -fL -o "$MINISIGN_ARCHIVE" \
        "https://github.com/jedisct1/minisign/releases/download/$MINISIGN_VERSION/minisign-$MINISIGN_VERSION-linux.tar.gz"
fi
echo "$MINISIGN_ARCHIVE_SHA256  $MINISIGN_ARCHIVE" | sha256sum -c -
tar -xOf "$MINISIGN_ARCHIVE" "minisign-linux/$ARCH/minisign" \
    >"$APPDIR/usr/bin/minisign"
chmod 755 "$APPDIR/usr/bin/minisign"

# GTK loads these resources dynamically, so ldd cannot discover them.
if [ -d "/usr/lib/$MULTIARCH/gio/modules" ]; then
    mkdir -p "$APPDIR/usr/lib/gio"
    cp -a "/usr/lib/$MULTIARCH/gio/modules" "$APPDIR/usr/lib/gio/"
fi
for source in "/usr/lib/$MULTIARCH/gdk-pixbuf-2.0" \
              "/usr/lib/$MULTIARCH/gtk-4.0"; do
    [ ! -d "$source" ] || cp -a "$source" "$APPDIR/usr/lib/"
done
if [ -d /usr/share/glib-2.0/schemas ]; then
    mkdir -p "$APPDIR/usr/share/glib-2.0"
    cp -a /usr/share/glib-2.0/schemas "$APPDIR/usr/share/glib-2.0/"
fi

query_loaders="$(command -v gdk-pixbuf-query-loaders 2>/dev/null || true)"
if [ -z "$query_loaders" ] && \
   [ -x "/usr/lib/$MULTIARCH/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders" ]; then
    query_loaders="/usr/lib/$MULTIARCH/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders"
fi
if [ -n "$query_loaders" ]; then
    cp -aL "$query_loaders" "$APPDIR/usr/bin/gdk-pixbuf-query-loaders"
fi

# Recursively copy shared-library dependencies into one private library path.
# glibc and the dynamic loader remain supplied by Linux for compatibility.
declare -A seen=()
copy_dependencies() {
    local candidate dependency base changed=0
    while IFS= read -r -d '' candidate; do
        file "$candidate" | grep -q 'ELF' || continue
        while IFS= read -r dependency; do
            [ -f "$dependency" ] || continue
            base="$(basename "$dependency")"
            case "$base" in
                libc.so.*|libm.so.*|libpthread.so.*|libdl.so.*|librt.so.*|\
                libresolv.so.*|libutil.so.*|libanl.so.*|libnss_*.so.*|\
                ld-linux*.so.*) continue ;;
            esac
            if [ -z "${seen[$base]+x}" ]; then
                seen[$base]=1
                cp -aL "$dependency" "$APPDIR/usr/lib/$base"
                changed=1
            fi
        done < <(ldd "$candidate" 2>/dev/null | awk \
            '/=> \// {print $3} /^[[:space:]]*\// {print $1}')
    done < <(find "$APPDIR/usr/bin" "$APPDIR/usr/lib" -type f -print0)
    return "$changed"
}
while ! copy_dependencies; do :; done

cp "$HERE/AppRun" "$APPDIR/AppRun"
cp "$HERE/vaultleaf-backup" "$APPDIR/usr/bin/vaultleaf-backup"
cp "$ROOT/uninstall.sh" "$APPDIR/usr/bin/vaultleaf-uninstall"
chmod 755 "$APPDIR/AppRun" "$APPDIR/usr/bin/"*
cp "$HERE/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
cp "$HERE/$APP_ID.desktop" "$APPDIR/usr/share/applications/"
cp "$HERE/$APP_ID.metainfo.xml" \
    "$APPDIR/usr/share/metainfo/$APP_ID.appdata.xml"
cp "$ROOT/src/my_backups/data/icon.svg" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
cp "$ROOT/src/my_backups/data/icon.svg" "$APPDIR/$APP_ID.svg"
cp "$ROOT/src/my_backups/data/icon.svg" "$APPDIR/.DirIcon"

TOOL="$HERE/appimagetool-$ARCH.AppImage"
if [ ! -f "$TOOL" ]; then
    echo "==> Downloading appimagetool"
    curl -fL -o "$TOOL" \
        "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod 755 "$TOOL"
fi

echo "==> Verifying the bundled runtime"
"$APPDIR/AppRun" --version
PATH=/usr/bin:/bin "$APPDIR/AppRun" --version
PATH=/usr/bin:/bin "$APPDIR/AppRun" --self-test

echo "==> Building $OUT"
rm -f "$OUT"
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"
chmod 755 "$OUT"

echo "==> Done: $OUT"
echo "    No Python, GTK, restic, rclone, or minisign installation is required."
