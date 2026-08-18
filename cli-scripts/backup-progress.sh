#!/bin/bash
# Live progress bar for the currently running scheduled backup.
#   ./backup-progress.sh            -> daily (default)
#   ./backup-progress.sh weekly     -> weekly
# Press Ctrl+C to stop watching.
JSON="${1:-daily}"
case "$JSON" in
  daily)  STATUS=/var/tmp/backup-daily.json ;;
  weekly) STATUS=/var/tmp/backup-weekly.json ;;
  *) STATUS="$JSON" ;;
esac

echo "Monitoring $STATUS  (Ctrl+C to quit)"
while :; do
  line="$(tail -n 1 "$STATUS" 2>/dev/null | grep '"message_type":"status"')"
  pct="$(echo "$line" | sed -n 's/.*"percent_done":\([0-9.]*\).*/\1/p')"
  if [ -n "$pct" ]; then
    p="$(awk -v x="$pct" 'BEGIN{printf "%d", x*100}')"
    [ "$p" -gt 100 ] && p=100
    filled=$((p/2)); spaces=$((50-filled))
    bar="$(printf '%*s' "$filled" '' | tr ' ' '#'; printf '%*s' "$spaces" '')"
    printf '\r[%s] %3d%%' "$bar" "$p"
  else
    printf '\r[ scanning / uploading ... ] 0%%'
  fi
  sleep 1
done
