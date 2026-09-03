#!/usr/bin/env python3
"""Периодическое (cron) продление залогиненных сессий без повторного входа.

Открывает headless-Firefox с постоянным профилем (его наполняет
``scripts/login_cookie_profile.py`` — ручной вход — или
``scripts/seed_cookie_profile.py`` — засев из свежего экспортированного
cookies-файла), заходит обычным GET-запросом (не логин!) на сайт и
переписывает свежие cookies в целевой файл. Такой "прогрев" раз в
несколько часов заметно продлевает жизнь ``sessionid`` / Google-сессии.

Управляемые сайты:

* **instagram** — всегда. Пишет Instagram-cookies в ``config.COOKIES_FILE``
  (общий cookies.txt для gallery-dl и yt-dlp).
* **youtube** — только если задан ``config.YT_COOKIES_FILE`` и файл уже
  существует (то есть админ завёл отдельный «одноразовый» age-verified
  Google-аккаунт для возрастных видео). Пишет Google/YouTube-cookies в
  ЭТОТ отдельный файл — на основной (cookie-free) путь YouTube никак не
  влияет.

У каждого сайта свой профиль (``<PROFILE_DIR>`` и ``<PROFILE_DIR>-yt``),
чтобы Instagram и Google не делили один browser-fingerprint.

Если сессия слетела (сайт отдаёт страницу логина) — cookies НЕ
перезаписываются протухшими, а админам уходит уведомление в Telegram
(не чаще раза в сутки).
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

_BASE_PROFILE = Path(
    os.environ.get("COOKIE_PROFILE_DIR", Path.home() / ".cache/ytdlmsaver-cookie-profile")
).expanduser()

_ALERT_STAMP = Path(tempfile.gettempdir()) / "resave-cookie-alert.stamp"
_ALERT_MIN_INTERVAL = 24 * 3600

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("refresh_cookies")


class Site:
    def __init__(self, name: str, profile_dir: Path, cookies_file: Path, markers: tuple[str, ...]):
        self.name = name
        self.profile_dir = profile_dir
        self.cookies_file = cookies_file
        self.markers = markers

    def owns(self, domain: str) -> bool:
        return any(m in domain for m in self.markers)

    def logged_in(self, page) -> bool:
        if self.name == "instagram":
            page.goto("https://www.instagram.com/", wait_until="networkidle", timeout=30000)
            return "/accounts/login" not in page.url
        # youtube
        page.goto("https://www.youtube.com/", wait_until="networkidle", timeout=30000)
        try:
            return not page.get_by_text("Sign in", exact=False).first.is_visible(timeout=3000)
        except Exception:  # noqa: BLE001
            return False


def _active_sites() -> list[Site]:
    sites = [
        Site(
            "instagram",
            _BASE_PROFILE,
            Path(config.COOKIES_FILE),
            ("instagram.com",),
        )
    ]
    yt_file = Path(config.YT_COOKIES_FILE)
    if yt_file.is_file() and yt_file.stat().st_size > 0:
        sites.append(
            Site(
                "youtube",
                _BASE_PROFILE.with_name(_BASE_PROFILE.name + "-yt"),
                yt_file,
                ("youtube.com", "google.com", "google.ru"),
            )
        )
    return sites


def _notify_admins(text: str) -> None:
    token, admin_ids = config.BOT_TOKEN, config.ADMIN_IDS
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


def _alert_text(site_name: str) -> str:
    if site_name == "instagram":
        return (
            "⚠️ ReSave: сессия Instagram слетела.\n\n"
            "Скачивание из Instagram не работает, пока не обновишь cookies:\n"
            "1) в браузере с логином в Instagram экспортируй cookies "
            "(расширение «Get cookies.txt»);\n"
            "2) положи файл в ~/Downloads/cookies.txt на сервере;\n"
            "3) дальше автоматически (deploy_cookies.sh + seed_cookie_profile.py).\n\n"
            "YouTube это не затрагивает."
        )
    return (
        "⚠️ ReSave: сессия YouTube (yt_cookies.txt) слетела.\n\n"
        "Обычные видео работают без cookies. Перестанут открываться только "
        "видео 18+.\n"
        "Чтобы вернуть 18+: экспортируй cookies одноразового age-verified "
        "Google-аккаунта и положи в ~/Downloads/yt_cookies.txt "
        "(deploy_cookies.sh подхватит), потом seed_cookie_profile.py."
    )


def _read_existing_cookies(path: Path) -> "dict[tuple[str, str], str]":
    existing: "dict[tuple[str, str], str]" = {}
    if not path.exists():
        return existing
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) == 7:
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


def _write_cookies(site: Site, fresh: list[dict]) -> None:
    existing = _read_existing_cookies(site.cookies_file)
    managed = {(c["domain"], c["name"]) for c in fresh}
    lines = ["# Netscape HTTP Cookie File", "# This file is generated by yt-dlp.  Do not edit.", ""]
    lines += [line for key, line in existing.items() if key not in managed]
    lines += [_cookie_to_netscape_line(c) for c in fresh]

    site.cookies_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(site.cookies_file.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp_path, site.cookies_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    logger.info(
        "%s: %s обновлён (%s свежих записей, %s прочих сохранено)",
        site.name,
        site.cookies_file.name,
        len(managed),
        len(existing) - len([k for k in existing if k in managed]),
    )


def _refresh_site(site: Site) -> bool:
    if not site.profile_dir.exists() or not any(site.profile_dir.iterdir()):
        logger.error(
            "%s: профиль %s пуст — сначала seed_cookie_profile.py / login_cookie_profile.py",
            site.name,
            site.profile_dir,
        )
        return False

    with sync_playwright() as p:
        context = p.firefox.launch_persistent_context(
            user_data_dir=str(site.profile_dir), headless=True
        )
        try:
            page = context.new_page()
            try:
                alive = site.logged_in(page)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: не удалось проверить сессию: %s", site.name, exc)
                alive = False
            if not alive:
                logger.warning("%s: сессия слетела — %s не трогаю", site.name, site.cookies_file.name)
                return False
            logger.info("%s: сессия жива", site.name)
            fresh = [c for c in context.cookies() if site.owns(c["domain"])]
        finally:
            context.close()

    _write_cookies(site, fresh)
    return True


def main() -> int:
    sites = _active_sites()
    logger.info("Активные сайты: %s", ", ".join(s.name for s in sites))

    any_ok = False
    for site in sites:
        try:
            ok = _refresh_site(site)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s: ошибка при обновлении: %s", site.name, exc)
            ok = False
        if ok:
            any_ok = True
        else:
            _notify_admins(_alert_text(site.name))

    return 0 if any_ok else 1


if __name__ == "__main__":
    sys.exit(main())
