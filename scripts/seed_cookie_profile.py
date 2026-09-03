#!/usr/bin/env python3
"""Разовый (или "когда снова слетит") засев headless-профиля Playwright из
уже валидного cookies.txt — без видимого браузера и без VNC/X11.

Экран нужен только для РУЧНОГО логина (scripts/login_cookie_profile.py).
Обычно же пользователь экспортирует cookies.txt расширением браузера,
кладёт в ~/Downloads (deploy_cookies.sh подхватывает), а этим скриптом
Instagram-cookies переносятся в headless-профиль, который потом
поддерживает живым scripts/refresh_cookies.py.

Запускать заново, когда refresh_cookies.py начал ругаться на "сессия
слетела" и пришло уведомление в Telegram.
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

PROFILE_DIR = Path(
    os.environ.get("COOKIE_PROFILE_DIR", Path.home() / ".cache/ytdlmsaver-cookie-profile")
).expanduser()
COOKIES_FILE = Path(config.COOKIES_FILE)
MANAGED_MARKER = "instagram.com"


def _parse_netscape_cookies(path: Path) -> list[dict]:
    cookies = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _include_subdomains, cpath, secure, expiry, name, value = parts
        if MANAGED_MARKER not in domain:
            continue
        expiry_int = int(expiry) if expiry.isdigit() else 0
        cookie = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": cpath or "/",
            "secure": secure.upper() == "TRUE",
            "sameSite": "Lax",
        }
        if expiry_int > 0:
            cookie["expires"] = expiry_int
        cookies.append(cookie)
    return cookies


def main() -> int:
    if not COOKIES_FILE.exists():
        print(f"{COOKIES_FILE} не найден", file=sys.stderr)
        return 1

    cookies = _parse_netscape_cookies(COOKIES_FILE)
    if not cookies:
        print("Не нашёл ни одной Instagram-cookie в cookies.txt", file=sys.stderr)
        return 1

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
        )
        context.add_cookies(cookies)
        context.close()

    print(f"Засеяно {len(cookies)} Instagram-cookies в {PROFILE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
