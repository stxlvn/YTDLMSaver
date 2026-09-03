import logging
import os
import subprocess

import yt_dlp
import config

logger = logging.getLogger(__name__)


def prepare_video_thumbnail(task, work_dir, file_path) -> str | None:
    # Готовим thumbnail только ПОСЛЕ скачивания видео: _download_first_available_variant
    # чистит work_dir в начале каждой попытки (_clear_work_dir), так что thumbnail,
    # подготовленный до неё, гарантированно стирался с диска ещё до отправки -
    # send_video потом молча уходил без превью (thumbnail_path указывал на
    # уже несуществующий файл). Вызывать эту функцию нужно после скачивания.
    if task.action in {"audio", "gif"}:
        return None

    thumbnail_path = None
    logger.info(f"Thumbnail: task_id={task.task_id} url={task.url} - готовим для всех источников")

    try:
        import requests
        # task.info уже получен раньше (в handlers/download_processing.py)
        # через yt-dlp с cookiefile - используем его thumbnail вместо
        # повторного bare-запроса без cookies, который для части видео
        # (например, возрастные ограничения) тихо не находит thumbnail.
        thumbnail_url = (task.info or {}).get('thumbnail')
        logger.info(
            f"Thumbnail: task_id={task.task_id} thumbnail из task.info={thumbnail_url!r}"
        )
        if not thumbnail_url:
            with yt_dlp.YoutubeDL({
                'quiet': True,
                'no_warnings': True,
                **config.cookie_ydl_opts(),
                **config.common_ydl_opts(),
            }) as ydl:
                info = ydl.extract_info(task.url, download=False)
                thumbnail_url = info.get('thumbnail')
            logger.info(
                f"Thumbnail: task_id={task.task_id} thumbnail из повторного yt-dlp запроса={thumbnail_url!r}"
            )

        if not thumbnail_url:
            logger.warning(f"Thumbnail: task_id={task.task_id} не удалось подготовить - yt-dlp не вернул thumbnail для {task.url}")
        else:
            response = requests.get(thumbnail_url, timeout=10)
            logger.info(
                f"Thumbnail: task_id={task.task_id} скачивание {thumbnail_url} -> HTTP {response.status_code}, "
                f"{len(response.content) if response.ok else 0} байт"
            )
            if response.status_code != 200:
                logger.warning(
                    f"Thumbnail: task_id={task.task_id} не удалось подготовить - HTTP {response.status_code} при скачивании {thumbnail_url}"
                )
            else:
                raw_thumb = work_dir / "raw_thumb.jpg"
                tg_thumb = work_dir / "tg_thumb.jpg"
                with open(raw_thumb, 'wb') as f:
                    f.write(response.content)
                try:
                    subprocess.run([
                        'ffmpeg', '-y', '-i', str(raw_thumb),
                        '-vf', 'scale=320:320:force_original_aspect_ratio=decrease',
                        '-q:v', '5', str(tg_thumb)
                    ], check=True, capture_output=True)
                    thumbnail_path = str(tg_thumb)
                    task.thumbnail_path = thumbnail_path
                    logger.info(
                        f"Thumbnail: task_id={task.task_id} готово, resized -> {thumbnail_path} "
                        f"({os.path.getsize(thumbnail_path)} байт)"
                    )
                except Exception as resize_e:
                    logger.warning(f"Thumbnail: task_id={task.task_id} ошибка ресайза обложки: {resize_e}")
                    thumbnail_path = str(raw_thumb)
                    task.thumbnail_path = thumbnail_path
                    logger.info(
                        f"Thumbnail: task_id={task.task_id} готово (без ресайза, raw) -> {thumbnail_path} "
                        f"({os.path.getsize(thumbnail_path)} байт)"
                    )
    except Exception as e:
        logger.warning(f"Thumbnail: task_id={task.task_id} не удалось подготовить: {e}", exc_info=True)

    logger.info(
        f"Thumbnail: task_id={task.task_id} итог после CDN/yt-dlp попытки: thumbnail_path={thumbnail_path!r}"
    )

    if not thumbnail_path:
        frame_thumb = work_dir / "frame_thumb.jpg"
        for offset in ("00:00:01", "00:00:00"):
            try:
                subprocess.run([
                    'ffmpeg', '-y', '-ss', offset, '-i', str(file_path),
                    '-frames:v', '1',
                    '-vf', 'scale=320:320:force_original_aspect_ratio=decrease',
                    '-q:v', '5', str(frame_thumb)
                ], check=True, capture_output=True, timeout=30)
            except Exception as frame_e:
                logger.warning(
                    f"Thumbnail: task_id={task.task_id} не удалось извлечь кадр видео (offset={offset}): {frame_e}"
                )
                continue
            if frame_thumb.exists() and frame_thumb.stat().st_size > 0:
                thumbnail_path = str(frame_thumb)
                task.thumbnail_path = thumbnail_path
                logger.info(
                    f"Thumbnail: task_id={task.task_id} fallback - взят кадр видео (offset={offset}) "
                    f"-> {thumbnail_path} ({os.path.getsize(thumbnail_path)} байт)"
                )
                break
        else:
            logger.warning(f"Thumbnail: task_id={task.task_id} fallback на кадр видео тоже не удался")

    return thumbnail_path
