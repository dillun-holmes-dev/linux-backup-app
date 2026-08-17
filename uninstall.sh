#!/bin/sh
# Remove VaultLeaf's user-level installation without deleting backup data.
set -eu

APP_ID="io.github.dillunholmes.VaultLeafBackup"
USER_UNITS="$HOME/.config/systemd/user"
DATA_DIR="$HOME/.local/share/my-backups"

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now \
        my-backups-daily.timer my-backups-weekly.timer \
        my-backups-monthly.timer my-backups-integrity.timer \
        my-backups-rclone.service >/dev/null 2>&1 || true
fi

for stem in daily weekly monthly integrity; do
    rm -f "$USER_UNITS/my-backups-$stem.service" \
          "$USER_UNITS/my-backups-$stem.timer"
done
rm -f "$USER_UNITS/my-backups-rclone.service" \
      "$HOME/.config/autostart/$APP_ID.desktop" \
      "$HOME/.config/autostart/my-backups.desktop" \
      "$HOME/.local/share/applications/$APP_ID.desktop" \
      "$HOME/.local/share/applications/my-backups.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/$APP_ID.svg" \
      "$HOME/.local/bin/my-backups" "$HOME/.local/bin/vaultleaf-backup" \
      "$HOME/.local/bin/vaultleaf-uninstall" \
      "$DATA_DIR/run-backup.sh" "$DATA_DIR/run-integrity.sh" \
      "$DATA_DIR/start-app.sh" "$DATA_DIR/install-dependencies.sh"
rm -rf "$HOME/.local/lib/my-backups" "$DATA_DIR/bin"

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

echo "VaultLeaf Backup was uninstalled."
echo "Your settings, encryption key, logs, and backup repositories were preserved."
