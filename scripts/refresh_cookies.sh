#!/bin/sh
# Стабильная обёртка для cron: не зависит от CWD и от того, где venv.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec "$DIR/venv/bin/python" "$DIR/scripts/refresh_cookies.py"
