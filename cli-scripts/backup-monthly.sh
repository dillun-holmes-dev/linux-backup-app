#!/bin/bash
# Monthly FULL bootable disk image of the OS drive, encrypted, uploaded to Google Drive.
# dd -> zstd -> AES-256 -> split into 4G parts -> rclone.
# Restore: rejoin parts, decrypt, dd back onto a new NVMe, boot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export RCLONE_CONFIG="$HOME/.config/rclone/rclone.conf"
DISK="${DISK:-/dev/nvme0n1}"
REMOTE="gdrive:monthly"
KEYFILE="$SCRIPT_DIR/backup-key.bin"
STAGE="/var/tmp/backup-monthly"
STAMP="$(date +%Y-%m-%d_%H-%M)"
LOG="/var/log/backup-monthly.log"

mkdir -p "$STAGE"

# Run only on the true last day of the month (timer fires on the 28th-31st),
# OR catch up on the 1st-2nd if last month's image is missing.
today="$(date +%Y-%m)"
if [ "$(date -d 'tomorrow' +%d)" != "01" ]; then
  if [ "$(date +%d)" -gt 2 ]; then
    echo "$(date): Not the last day of the month, skipping monthly image." >> "$LOG"
    exit 0
  fi
  latest="$(rclone lsf "$REMOTE" --dirs-only 2>/dev/null | sort | tail -n 1)"
  prev="$(date -d 'last month' +%Y-%m)"
  if [[ "$latest" == "$today"* || "$latest" == "$prev"* ]]; then
    echo "$(date): Monthly image already exists, skipping." >> "$LOG"
    exit 0
  fi
fi

echo "=== Monthly image started $(date) ===" >> "$LOG"

# Create encryption key on first run (KEEP THIS FILE — needed to decrypt!)
if [ ! -f "$KEYFILE" ]; then
  openssl rand 32 > "$KEYFILE"
  chmod 600 "$KEYFILE"
fi

# Clone OS disk -> compress -> encrypt -> split into 4GiB parts
dd if="$DISK" bs=4M status=progress \
  | zstd -T0 -q \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass file:"$KEYFILE" \
  | split -b 4G - "$STAGE/system-$STAMP.part."

# Upload only new/changed parts into a date-stamped subfolder (monthly/YYYY-MM-DD_HH-MM)
# --transfers 24 = upload multiple parts in parallel to saturate the connection
rclone copy "$STAGE" "$REMOTE/$STAMP" --checksum --fast-list --transfers 24 --checkers 24 --drive-chunk-size 256M >> "$LOG" 2>&1

# Keep only the current month locally (free up disk); keep only the 1 most recent month remotely
find "$STAGE" -name 'system-*.part.*' -type f ! -name "system-$STAMP.part.*" -delete
rclone lsf "$REMOTE" --dirs-only | sort | head -n -1 | while read -r d; do
  rclone purge "$REMOTE/$d" >> "$LOG" 2>&1 || true
done

echo "=== Monthly image finished $(date) ===" >> "$LOG"
