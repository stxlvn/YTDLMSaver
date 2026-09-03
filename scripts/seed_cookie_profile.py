#!/usr/bin/env python3
"""Засев headless-профилей Playwright из уже валидных cookies-файлов —
без видимого браузера и без VNC/X11.

Разбирает:

* ``config.COOKIES_FILE`` (cookies.txt) — берёт Instagram-cookies и кладёт
  их в основной профиль;
* ``config.YT_COOKIES_FILE`` (yt_cookies.txt), если существует — берёт
  Google/YouTube-cookies и кладёт в профиль ``<...>-yt`` (нужен только для
  возрастных видео).

Профиль(и) потом поддерживает живым ``scripts/refresh_cookies.py``.
Запускать, когда refresh_cookies.py начал ругаться на "сессия слетела" и
пришло уведомление в Telegram: пользователь заново экспортирует нужный
cookies-файл (расширение браузера → ~/Downloads → deploy_cookies.sh), а
этот скрипт переносит его в профиль.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import config  # noqa: E402

_BASE_PROFILE = Path(
    os.environ.get("COOKIE_PROFILE_DIR", Path.home() / ".cache/ytdlmsaver-cookie-profile")
).expanduser()

_JOBS = [
    ("instagram", Path(config.COOKIES_FILE), _BASE_PROFILE, ("instagram.com",)),
    (
        "youtube",
        Path(config.YT_COOKIES_FILE),
        _BASE_PROFILE.with_name(_BASE_PROFILE.name + "-yt"),
        ("youtube.com", "google.com", "google.ru"),
    ),
]


def _parse_netscape_cookies(path: Path, markers: tuple[str, ...]) -> list[dict]:
    cookies = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _inc, cpath, secure, expiry, name, value = parts
        if not any(m in domain for m in markers):
            continue
        cookie = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": cpath or "/",
            "secure": secure.upper() == "TRUE",
            "sameSite": "Lax",
        }
        if expiry.isdigit() and int(expiry) > 0:
            cookie["expires"] = int(expiry)
        cookies.append(cookie)
    return cookies


def _seed(name: str, cookies_file: Path, profile_dir: Path, markers: tuple[str, ...]) -> bool:
    if not cookies_file.is_file() or cookies_file.stat().st_size == 0:
        return False
    cookies = _parse_netscape_cookies(cookies_file, markers)
    if not cookies:
        print(f"{name}: в {cookies_file.name} нет подходящих cookies — пропускаю")
        return False
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(profile_dir), headless=True
        )
        context.add_cookies(cookies)
        context.close()
    print(f"{name}: засеяно {len(cookies)} cookies в {profile_dir}")
    return True


def main() -> int:
    seeded = [
        name
        for name, cookies_file, profile_dir, markers in _JOBS
        if _seed(name, cookies_file, profile_dir, markers)
    ]
    if not seeded:
        print("Нечего засевать: ни один cookies-файл не содержит нужных cookies", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
