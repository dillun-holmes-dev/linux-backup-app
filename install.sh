#!/bin/sh
# One-time, cross-distribution bootstrap installer for VaultLeaf Backup.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)

if [ "$(id -u)" -eq 0 ]; then
    AS_ROOT=""
else
    command -v sudo >/dev/null 2>&1 || {
        echo "sudo is required for the one-time dependency installation." >&2
        exit 1
    }
    echo "Administrator access is requested once to install system packages."
    sudo -v
    AS_ROOT="sudo"
fi

if command -v apt-get >/dev/null 2>&1; then
    $AS_ROOT apt-get update
    $AS_ROOT apt-get install -y restic rclone fuse3 python3 python3-gi gir1.2-gtk-4.0 policykit-1
elif command -v dnf >/dev/null 2>&1; then
    $AS_ROOT dnf install -y restic rclone fuse3 python3 python3-gobject gtk4 polkit
elif command -v zypper >/dev/null 2>&1; then
    $AS_ROOT zypper --non-interactive install restic rclone fuse3 python3 python3-gobject gtk4 polkit
elif command -v pacman >/dev/null 2>&1; then
    $AS_ROOT pacman -S --needed --noconfirm restic rclone fuse3 python python-gobject gtk4 polkit
elif command -v apk >/dev/null 2>&1; then
    $AS_ROOT apk add restic rclone fuse3 python3 py3-gobject3 gtk4.0 polkit
else
    echo "Package manager not recognized. Install Python 3, GTK4/PyGObject, restic, rclone, and FUSE 3." >&2
    exit 2
fi

INSTALL_DIR="$HOME/.local/lib/my-backups"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APP_ID="io.github.dillunholmes.VaultLeafBackup"
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APP_DIR" "$ICON_DIR"
if [ -e "$INSTALL_DIR/my_backups" ]; then
    mv "$INSTALL_DIR/my_backups" "$INSTALL_DIR/my_backups.previous.$$"
fi
cp -R "$ROOT/src/my_backups" "$INSTALL_DIR/my_backups"

cat >"$BIN_DIR/my-backups" <<EOF
#!/bin/sh
export PYTHONPATH="$INSTALL_DIR"
exec python3 -m my_backups "\$@"
EOF
chmod 755 "$BIN_DIR/my-backups"
cp "$ROOT/uninstall.sh" "$BIN_DIR/vaultleaf-uninstall"
chmod 755 "$BIN_DIR/vaultleaf-uninstall"

cp "$ROOT/src/my_backups/data/icon.svg" "$ICON_DIR/$APP_ID.svg"

cat >"$APP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VaultLeaf Backup
Comment=Automatic restic and rclone backups
Exec=$BIN_DIR/my-backups
Icon=$APP_ID
StartupWMClass=$APP_ID
Categories=Utility;Archiving;FileTools;
EOF

echo "VaultLeaf Backup is installed. No more administrator access is needed."
exec "$BIN_DIR/my-backups"
