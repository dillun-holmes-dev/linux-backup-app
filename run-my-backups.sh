#!/bin/sh
# Quick way to run the app from a checkout (no packaging needed).
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m my_backups "$@"
