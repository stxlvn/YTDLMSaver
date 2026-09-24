import logging
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

TIKWM_API_URL = "https://www.tikwm.com/api/"


def _tikwm_proxies() -> dict | None:
    # tikwm.com's Cloudflare WAF blocks this VPS's IP outright (plain 403,
    # not rate-limiting) while working fine through the FI proxy already
    # configured for YouTube geo-bypass - reuse it here too.
    if not config.PROXY_URL:
        return None
    return {"http": config.PROXY_URL, "https": config.PROXY_URL}


def is_tiktok_photo_url(url: str) -> bool:
    url_lower = url.lower()

    if 'tiktok.com' not in url_lower:
        return False

    # Если в ссылке явно указано, что это фото
    if '/photo/' in url_lower:
        return True

    # Если это короткая ссылка (редирект), мы должны узнать финальный адрес
    if 'vm.tiktok.com' in url_lower or 'vt.tiktok.com' in url_lower:
        try:
            # Делаем быстрый запрос без скачивания (HEAD), чтобы получить полный URL
            response = requests.head(url, allow_redirects=True, timeout=5)
            if '/photo/' in response.url.lower():
                return True
        except Exception as e:
            logger.debug(f"Не удалось раскрыть короткую ссылку TikTok: {e}")

    # Если это обычное видео, возвращаем False
    return False


def _tikwm_lookup(url: str) -> dict:
    response = requests.post(
        TIKWM_API_URL, data={"url": url, "hd": 1}, timeout=20, proxies=_tikwm_proxies()
    )
    data = response.json()
    if data.get("code") != 0 or "data" not in data:
        msg = data.get("msg", "Неизвестная ошибка API")
        logger.error(f"TikWM API Error: {msg}")
        raise ValueError(f"API отклонил запрос: {msg}")
    return data["data"]


def download_tiktok_photos(url: str, work_dir: Path) -> list[Path]:
    logger.info(f"Запрос фото TikTok через TikWM API: {url}")

    try:
        data = _tikwm_lookup(url)
        images = data.get("images", [])

        if not images:
            raise ValueError("В этом посте нет фотографий (возможно, это видео).")

        downloaded_paths = []

        for idx, img_url in enumerate(images):
            try:
                img_res = requests.get(img_url, timeout=15, proxies=_tikwm_proxies())
                if img_res.status_code == 200:
                    file_path = work_dir / f"tiktok_photo_{idx:02d}.jpg"
                    with open(file_path, "wb") as f:
                        f.write(img_res.content)
                    downloaded_paths.append(file_path)
            except Exception as e:
                logger.warning(f"Не удалось скачать одно из фото ({img_url}): {e}")

        if downloaded_paths:
            logger.info(f"Успешно скачано {len(downloaded_paths)} фото через API.")
            return downloaded_paths
        else:
            raise ValueError("Не удалось сохранить ни одного изображения на диск.")

    except Exception as e:
        logger.error(f"Критическая ошибка при скачивании фото: {e}")
        raise RuntimeError(f"Не удалось получить доступ к TikTok: {str(e)}")


def download_tiktok_video(url: str, work_dir: Path) -> tuple[Path, dict]:
    """Скачивает видео TikTok через TikWM - запасной путь на случай, когда
    yt-dlp'шный экстрактор упирается в антибот-челлендж TikTok (что сейчас
    происходит регулярно и не лечится сменой клиента/прокси на стороне
    yt-dlp - TikWM тем временем работает нормально)."""
    logger.info(f"Запрос видео TikTok через TikWM API: {url}")

    data = _tikwm_lookup(url)
    video_url = data.get("hdplay") or data.get("play") or data.get("wmplay")
    if not video_url:
        raise ValueError("TikWM не вернул ссылку на видео (возможно, это фото-пост).")

    response = requests.get(video_url, timeout=60, proxies=_tikwm_proxies(), stream=True)
    response.raise_for_status()

    file_path = work_dir / "tiktok_video.mp4"
    with open(file_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if chunk:
                f.write(chunk)

    metadata = {
        "title": data.get("title") or "",
        "duration": data.get("duration"),
        "uploader": (data.get("author") or {}).get("nickname"),
    }
    return file_path, metadata
