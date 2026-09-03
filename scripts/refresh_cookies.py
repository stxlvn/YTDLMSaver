#!/usr/bin/env python3
"""Периодическое (cron) продление Instagram-сессии без логина.

Открывает headless-Firefox с постоянным профилем (его наполняет
``scripts/login_cookie_profile.py`` — ручной вход — или
``scripts/seed_cookie_profile.py`` — засев из свежего cookies.txt), заходит
на instagram.com обычным GET-запросом (не логин!) и переписывает свежие
Instagram-cookies в ``cookies.txt``. Такой "прогрев" раз в несколько часов
заметно продлевает жизнь ``sessionid``.

Если сессия всё-таки слетела (Instagram показывает страницу логина) —
cookies НЕ перезаписываются протухшими, а админам уходит уведомление в
Telegram: пора экспортировать cookies.txt заново (расширение браузера →
``~/Downloads/cookies.txt`` → ``deploy_cookies.sh`` подхватит).

YouTube этим скриптом не управляется вообще: там куки не нужны, PO-токены
выдаёт bgutil-провайдер. Куки прочих доменов (TikTok и т.д.) в cookies.txt
не трогаются.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
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
INSTAGRAM_MARKER = "instagram.com"

# Не спамить админов при каждом падении cron (каждые 6 часов) — не чаще
# одного уведомления в сутки.
_ALERT_STAMP = Path(tempfile.gettempdir()) / "resave-ig-cookie-alert.stamp"
_ALERT_MIN_INTERVAL = 24 * 3600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("refresh_cookies")


def _notify_admins(text: str) -> None:
    """Best-effort Telegram-уведомление админам напрямую через Bot API."""
    token = config.BOT_TOKEN
    admin_ids = config.ADMIN_IDS
    if not token or not admin_ids:
        logger.warning("BOT_TOKEN/ADMIN_IDS не заданы — уведомление админам пропущено")
        return

    try:
        if _ALERT_STAMP.exists() and time.time() - _ALERT_STAMP.stat().st_mtime < _ALERT_MIN_INTERVAL:
            logger.info("Уведомление уже отправляли недавно — пропускаю")
            return
    except OSError:
        pass

    for admin_id in admin_ids:
        payload = urllib.parse.urlencode({"chat_id": admin_id, "text": text}).encode()
        try:
            urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/sendMessage", data=payload, timeout=15
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось уведомить админа %s: %s", admin_id, exc)

    try:
        _ALERT_STAMP.touch()
    except OSError:
        pass


def _read_existing_cookies(path: Path) -> "dict[tuple[str, str], str]":
    """(domain, name) -> исходная строка, для доменов вне управления скрипта."""
    existing: "dict[tuple[str, str], str]" = {}
    if not path.exists():
        return existing
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        existing[(parts[0], parts[5])] = line
    return existing


def _cookie_to_netscape_line(cookie: dict) -> str:
    domain = cookie["domain"]
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    expires = cookie.get("expires", -1)
    expiry = "0" if expires is None or expires < 0 else str(int(expires))
    secure = "TRUE" if cookie.get("secure") else "FALSE"
    path = cookie.get("path") or "/"
    return "\t".join(
        [domain, include_subdomains, path, secure, expiry, cookie["name"], cookie["value"]]
    )


def _instagram_logged_in(page) -> bool:
    page.goto("https://www.instagram.com/", wait_until="networkidle", timeout=30000)
    return "/accounts/login" not in page.url


def _stale_session_alert() -> None:
    _notify_admins(
        "⚠️ ReSave: сессия Instagram слетела.\n\n"
        "Скачивание из Instagram работать не будет, пока не обновишь cookies:\n"
        "1) в браузере, где ты залогинен в Instagram, экспортируй cookies "
        "(расширение вида «Get cookies.txt»);\n"
        "2) положи файл в ~/Downloads/cookies.txt на сервере;\n"
        "3) дальше автоматически — deploy_cookies.sh подхватит его в минуту, "
        "затем прогон seed_cookie_profile.py.\n\n"
        "YouTube это не затрагивает — он работает без cookies."
    )


def main() -> int:
    if not PROFILE_DIR.exists() or not any(PROFILE_DIR.iterdir()):
        logger.error(
            "Профиль %s пуст — сначала scripts/seed_cookie_profile.py "
            "(засев из валидного cookies.txt) или scripts/login_cookie_profile.py.",
            PROFILE_DIR,
        )
        _stale_session_alert()
        return 1

    logged_in = False
    fresh_cookies: list[dict] = []

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=True
        )
        try:
            page = context.new_page()
            try:
                logged_in = _instagram_logged_in(page)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось проверить сессию Instagram: %s", exc)
                logged_in = False

            if logged_in:
                logger.info("instagram: сессия жива")
                fresh_cookies = [
                    c for c in context.cookies() if INSTAGRAM_MARKER in c["domain"]
                ]
            else:
                logger.warning("instagram: сессия слетела — cookies.txt не трогаю")
        finally:
            context.close()

    if not logged_in:
        _stale_session_alert()
        return 1

    existing = _read_existing_cookies(COOKIES_FILE)
    managed_keys = {(c["domain"], c["name"]) for c in fresh_cookies}

    lines = ["# Netscape HTTP Cookie File", "# This file is generated by yt-dlp.  Do not edit.", ""]
    lines += [line for key, line in existing.items() if key not in managed_keys]
    lines += [_cookie_to_netscape_line(c) for c in fresh_cookies]

    COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
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
        "cookies.txt обновлён (%s свежих Instagram-записей, %s прочих сохранено)",
        len(managed_keys),
        len(existing) - len([k for k in existing if k in managed_keys]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
