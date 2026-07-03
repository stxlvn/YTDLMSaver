#!/usr/bin/env python3
import asyncio
import os
import sys
from playwright.async_api import async_playwright

COOKIE_FILE = "/root/ReSave/cookies.txt"
STATE_FILE = "/root/ReSave/state.json"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        context = await browser.new_context(
            storage_state=STATE_FILE if os.path.exists(STATE_FILE) else None,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        await page.goto("https://www.youtube.com/")
        await page.wait_for_load_state("networkidle")

        if "Войти" in await page.title() or "Sign in" in await page.title():
            print("🔑 Выполняем вход...")
            await page.goto("https://accounts.google.com/")
            await page.fill('input[type="email"]', os.environ.get("YOUTUBE_EMAIL", ""))
            await page.click('button:has-text("Далее")')
            await page.wait_for_load_state("networkidle")
            await page.fill('input[type="password"]', os.environ.get("YOUTUBE_PASSWORD", ""))
            await page.click('button:has-text("Далее")')
            await page.wait_for_load_state("networkidle")
            try:
                await page.click('button:has-text("Подтвердить")')
            except:
                pass
            await context.storage_state(path=STATE_FILE)
            print("✅ Вход выполнен, состояние сохранено")

        cookies = await context.cookies()
        with open(COOKIE_FILE, "w") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for cookie in cookies:
                f.write(f"{cookie['domain']}\tTRUE\t{cookie['path']}\t")
                f.write(f"{'TRUE' if cookie.get('secure', False) else 'FALSE'}\t")
                f.write(f"{cookie.get('expires', 0)}\t{cookie['name']}\t{cookie['value']}\n")
        print("✅ Куки обновлены")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
