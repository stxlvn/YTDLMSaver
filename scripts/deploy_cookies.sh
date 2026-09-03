#!/bin/bash
# Ставится в системный cron раз в минуту:
#   * * * * * /root/ReSave/scripts/deploy_cookies.sh
#
# Забирает вручную экспортированные cookies из ~/Downloads и кладёт их
# туда, где их ждёт бот. Исходники удаляются, чтобы не копировать повторно.
set -eu

RESAVE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOWNLOADS="${HOME}/Downloads"
LOG=/var/log/cookies_update.log

deploy_one() {
    src="$DOWNLOADS/$1"
    dst="$RESAVE_DIR/$1"
    [ -f "$src" ] || return 0
    cp "$src" "$dst"
    chmod 644 "$dst"
    rm -f "$src"
    echo "$(date -Is) $1 updated" >> "$LOG"
}

deploy_one cookies.txt      # Instagram (общий cookies.txt)
deploy_one yt_cookies.txt   # YouTube 18+ (опционально)
