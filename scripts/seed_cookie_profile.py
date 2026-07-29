#!/usr/bin/env python3
"""Разовый (или "когда снова слетит") сид headless-профиля Playwright из
уже валидного cookies.txt - без видимого браузера и без VNC/X11 вообще.

Экран нужен только для РУЧНОГО логина; сама периодическая проверка
"жива ли сессия" (scripts/refresh_cookies.py) работает headless и её
профилю ничего не мешает быть засеянным напрямую из уже экспортированных
пользователем cookies (через расширение браузера + deploy_cookies.sh),
а не через отдельный визуальный логин в Playwright-профиль.

Запускать заново, если refresh_cookies.py начал ругаться на "сессия
слетела" - тогда пользователь заново экспортирует cookies.txt как обычно,
и этим скриптом переносим их в headless-профиль.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path("/root/.cache/ytdlmsaver-cookie-profile")
COOKIES_FILE = Path("/root/ReSave/cookies.txt")
MANAGED_MARKERS = ("instagram.com", "youtube.com", "google.com", "google.ru")


def _parse_netscape_cookies(path: Path) -> list[dict]:
    cookies = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, include_subdomains, cpath, secure, expiry, name, value = parts
        if not any(marker in domain for marker in MANAGED_MARKERS):
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
        print("Не нашёл ни одной cookie для instagram/youtube/google в cookies.txt", file=sys.stderr)
        return 1

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Firefox, а не Chromium: для headless keep-alive браузер не должен
        # совпадать с тем, чем пользователь логинился руками - но Playwright
        # автоматизирует Firefox только через свою собственную патченную
        # сборку (протокол Juggler), не системный /usr/bin/firefox, поэтому
        # executable_path тут не передаём.
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
        )
        context.add_cookies(cookies)
        context.close()

    print(f"Засеяно {len(cookies)} cookies в {PROFILE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
