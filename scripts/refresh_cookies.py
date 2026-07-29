#!/usr/bin/env python3
"""Периодическое (cron) обновление cookies.txt без логина.

Открывает headless-Chromium с ТЕМ ЖЕ постоянным профилем, что создаёт
login_cookie_profile.py (уже залогиненный руками через VNC), заходит на
instagram.com/youtube.com обычными GET-запросами (не логин!) и забирает
свежие session-cookies. Если сессия для площадки всё-таки слетела -
НЕ перезаписывает её cookies в cookies.txt (чтобы не убить рабочие
куки протухшими), а только предупреждает в лог, что нужен повторный
ручной вход через login_cookie_profile.py.

Другие домены (TikTok и т.д.), которых этот профиль не касается, в
cookies.txt не трогаются вообще.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path("/root/.cache/ytdlmsaver-cookie-profile")
COOKIES_FILE = Path("/root/ReSave/cookies.txt")

# Домены, которыми управляет именно этот скрипт - куки остальных доменов
# (TikTok, Facebook и т.д.) в cookies.txt никогда не трогаем.
SITE_DOMAIN_MARKERS = {
    "instagram": ("instagram.com",),
    "youtube": ("youtube.com", "google.com", "google.ru"),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("refresh_cookies")


def _is_managed_domain(domain: str, site: str) -> bool:
    return any(marker in domain for marker in SITE_DOMAIN_MARKERS[site])


def _read_existing_cookies(path: Path) -> dict[tuple[str, str], str]:
    """(domain, name) -> full raw line, for domains this script doesn't manage."""
    existing: dict[tuple[str, str], str] = {}
    if not path.exists():
        return existing

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, name = parts[0], parts[5]
        existing[(domain, name)] = line

    return existing


def _cookie_to_netscape_line(cookie: dict) -> str:
    domain = cookie["domain"]
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    expires = cookie.get("expires", -1)
    expiry = "0" if expires is None or expires < 0 else str(int(expires))
    secure = "TRUE" if cookie.get("secure") else "FALSE"
    path = cookie.get("path") or "/"
    return "\t".join([domain, include_subdomains, path, secure, expiry, cookie["name"], cookie["value"]])


def _check_logged_in(page, site: str) -> bool:
    if site == "instagram":
        page.goto("https://www.instagram.com/", wait_until="networkidle", timeout=30000)
        return "/accounts/login" not in page.url
    if site == "youtube":
        page.goto("https://www.youtube.com/", wait_until="networkidle", timeout=30000)
        try:
            signed_out = page.get_by_text("Sign in", exact=False).first
            return not signed_out.is_visible(timeout=3000)
        except Exception:
            # Ошибка проверки - консервативно считаем, что не залогинены,
            # чтобы не рисковать перезаписью рабочих cookies протухшими.
            return False
    raise ValueError(site)


def main() -> int:
    if not PROFILE_DIR.exists() or not any(PROFILE_DIR.iterdir()):
        logger.error(
            "Профиль %s пуст - сначала запусти scripts/seed_cookie_profile.py "
            "(засеять из текущего валидного cookies.txt).",
            PROFILE_DIR,
        )
        return 1

    fresh_cookies: dict[str, list[dict]] = {"instagram": [], "youtube": []}
    logged_in: dict[str, bool] = {}

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
        )
        try:
            page = context.new_page()
            for site in ("instagram", "youtube"):
                try:
                    logged_in[site] = _check_logged_in(page, site)
                except Exception as exc:
                    logger.warning("Не удалось проверить сессию %s: %s", site, exc)
                    logged_in[site] = False
                if logged_in[site]:
                    logger.info("%s: сессия жива", site)
                else:
                    logger.warning(
                        "%s: сессия слетела (похоже на страницу логина) - "
                        "куки для этого сайта НЕ обновляю, нужен повторный "
                        "ручной вход через scripts/login_cookie_profile.py",
                        site,
                    )

            all_cookies = context.cookies()
            for cookie in all_cookies:
                for site in ("instagram", "youtube"):
                    if logged_in.get(site) and _is_managed_domain(cookie["domain"], site):
                        fresh_cookies[site].append(cookie)
        finally:
            context.close()

    if not any(logged_in.values()):
        logger.error("Ни одна сессия не жива - cookies.txt не трогаю.")
        return 1

    existing = _read_existing_cookies(COOKIES_FILE)
    managed_keys: set[tuple[str, str]] = set()
    for site, cookies in fresh_cookies.items():
        for cookie in cookies:
            managed_keys.add((cookie["domain"], cookie["name"]))

    lines = ["# Netscape HTTP Cookie File", "# This file is generated by yt-dlp.  Do not edit.", ""]
    for key, line in existing.items():
        if key not in managed_keys:
            lines.append(line)
    for cookies in fresh_cookies.values():
        for cookie in cookies:
            lines.append(_cookie_to_netscape_line(cookie))

    fd, tmp_path = tempfile.mkstemp(dir=str(COOKIES_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp_path, COOKIES_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    logger.info(
        "cookies.txt обновлён (%s свежих записей, %s сохранено как было)",
        len(managed_keys),
        len(existing) - len([k for k in existing if k in managed_keys]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
