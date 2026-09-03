import logging
import yt_dlp

import config

logger = logging.getLogger(__name__)


def run_ydl_with_geo_fallback(ydl_opts: dict, action):
    """Run `action(ydl)`; on an apparent region block, retry once through
    config.PROXY_URL (if configured) instead of just failing outright."""
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return action(ydl)
    except Exception as exc:
        if not config.PROXY_URL or not config.is_geo_blocked_error(str(exc)):
            raise
        logger.info("Похоже на региональную блокировку (%s), пробую через прокси", exc)
        proxied_opts = {**ydl_opts, **config.proxy_ydl_opts()}
        with yt_dlp.YoutubeDL(proxied_opts) as ydl:
            return action(ydl)


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
            **config.youtube_ydl_opts(),
            **config.geo_ydl_opts(),
        }

        info = run_ydl_with_geo_fallback(ydl_opts, lambda ydl: ydl.extract_info(url, download=False))
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
            **config.youtube_ydl_opts(),
            **config.geo_ydl_opts(),
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if not info:
                return False

            subtitles = info.get('subtitles', {})
            auto_captions = info.get('automatic_captions', {})

            has_subtitles = bool(subtitles or auto_captions)

            return has_subtitles

    except Exception as e:
        logger.warning(f"Ошибка при проверке субтитров: {e}")
        return False
