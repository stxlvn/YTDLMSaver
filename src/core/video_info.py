import logging
import yt_dlp

import config

logger = logging.getLogger(__name__)


def run_ydl_with_geo_fallback(ydl_opts: dict, action):
    """Run ``action(ydl)`` and, if it fails in a recoverable way, retry once:

    - apparent region block -> retry through ``config.PROXY_URL`` (if set);
    - YouTube age-gate -> retry with ``yt_cookies.txt`` (if present). This is
      the only place account cookies touch YouTube; the main path stays
      cookie-free.
    """
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return action(ydl)
    except Exception as exc:
        text = str(exc)

        if config.is_age_restricted_error(text) and config.has_yt_cookies():
            logger.info("Возрастное ограничение (%s), пробую с yt_cookies.txt", exc)
            aged_opts = {**ydl_opts, **config.yt_cookie_ydl_opts()}
            with yt_dlp.YoutubeDL(aged_opts) as ydl:
                return action(ydl)

        if config.PROXY_URL and config.is_geo_blocked_error(text):
            logger.info("Похоже на региональную блокировку (%s), пробую через прокси", exc)
            proxied_opts = {**ydl_opts, **config.proxy_ydl_opts()}
            with yt_dlp.YoutubeDL(proxied_opts) as ydl:
                return action(ydl)

        raise


def _is_formatless(info: dict | None) -> bool:
    """True when extract_info succeeded but returned no playable formats.

    With ``ignore_no_formats_error`` set, an age-gate doesn't raise (which is
    what run_ydl_with_geo_fallback's except-based retry needs) — it just comes
    back as an info dict with an empty ``formats`` list. Catch that case here.
    """
    return bool(info) and info.get("_type") != "playlist" and not info.get("formats")


def fetch_video_info_result(url):
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
            "socket_timeout": 10,
            "retries": 2,
            "extractor_retries": 2,
            "nocheckcertificate": True,
            "ignore_no_formats_error": True,
            **config.cookie_ydl_opts(),
            **config.common_ydl_opts(),
            **config.geo_ydl_opts(),
        }

        info = run_ydl_with_geo_fallback(ydl_opts, lambda ydl: ydl.extract_info(url, download=False))

        if _is_formatless(info) and config.has_yt_cookies():
            logger.info("Нет форматов (похоже на возрастное ограничение), пробую с yt_cookies.txt")
            aged_opts = {**ydl_opts, **config.yt_cookie_ydl_opts()}
            with yt_dlp.YoutubeDL(aged_opts) as ydl:
                aged_info = ydl.extract_info(url, download=False)
            if aged_info and aged_info.get("formats"):
                info = aged_info

        return info, None

    except Exception as e:
        logger.info("Ссылка не поддерживается или недоступна: %s", e)
        return None, str(e)


def fetch_video_info(url):
    info, _error = fetch_video_info_result(url)
    return info


def check_subtitles_available(url):
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
            "socket_timeout": 5,
            "retries": 2,
            "extractor_retries": 2,
            "nocheckcertificate": True,
            "ignore_no_formats_error": True,
            **config.cookie_ydl_opts(),
            **config.common_ydl_opts(),
            **config.geo_ydl_opts(),
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if _is_formatless(info) and config.has_yt_cookies():
            aged_opts = {**ydl_opts, **config.yt_cookie_ydl_opts()}
            with yt_dlp.YoutubeDL(aged_opts) as ydl:
                info = ydl.extract_info(url, download=False)

        if not info:
            return False

        subtitles = info.get('subtitles', {})
        auto_captions = info.get('automatic_captions', {})

        return bool(subtitles or auto_captions)

    except Exception as e:
        logger.warning(f"Ошибка при проверке субтитров: {e}")
        return False
