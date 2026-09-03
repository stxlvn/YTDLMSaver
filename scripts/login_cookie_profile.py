#!/usr/bin/env python3
"""Ручной вход в Instagram в постоянный Playwright-профиль.

Нужен экран (локально или через VNC/X11-forwarding). Открывает видимый
Firefox с тем же профилем, что использует scripts/refresh_cookies.py;
пользователь логинится руками, после чего сессия остаётся в профиле и
её поддерживает keep-alive.

Альтернатива без экрана: экспортировать cookies.txt расширением браузера
и прогнать scripts/seed_cookie_profile.py.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

PROFILE_DIR = Path(
    os.environ.get("COOKIE_PROFILE_DIR", Path.home() / ".cache/ytdlmsaver-cookie-profile")
).expanduser()


async def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        context = await p.firefox.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.instagram.com/accounts/login/", timeout=120000)
        input("👉 Войди в Instagram в открывшемся браузере, затем нажми Enter здесь...")
        await context.close()
    print(f"✅ Сессия сохранена в профиле {PROFILE_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
