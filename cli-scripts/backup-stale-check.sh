#!/bin/bash
# Runs at every boot. If no daily backup has finished in the last 26h
# and none is currently running, start one. (Belt-and-suspenders on top of
# the Persistent=true timers that catch up missed scheduled runs.)
set -u

LOG="/var/log/backup-daily.log"
STALE_HOURS=26

# Already running? Nothing to do.
if systemctl is-active --quiet backup-daily.service; then
  exit 0
fi

# Find the timestamp of the last successfully finished daily backup.
last_finish="$(grep '=== Backup finished' "$LOG" 2>/dev/null | tail -n 1 | sed 's/=== Backup finished //; s/ ===//')"
if [ -n "$last_finish" ]; then
  last_epoch="$(date -d "$last_finish" +%s 2>/dev/null || echo 0)"
  now="$(date +%s)"
  age=$(( (now - last_epoch) / 3600 ))
  if [ "$age" -lt "$STALE_HOURS" ]; then
    exit 0   # backed up recently enough
  fi
fi

# No recent backup -> start one (without blocking this service).
systemctl start --no-block backup-daily.service
