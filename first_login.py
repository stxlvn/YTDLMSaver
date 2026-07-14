#!/usr/bin/env python3
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

STATE_FILE = str(Path(__file__).resolve().parent / "state.json")

async def main():
    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        await page.goto("https://www.youtube.com/", timeout=120000)
        input("👉 Войдите в YouTube в открывшемся браузере, затем нажмите Enter здесь...")
        await context.storage_state(path=STATE_FILE)
        print("✅ Состояние сохранено")
        await browser.close()

asyncio.run(main())
