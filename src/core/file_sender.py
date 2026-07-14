from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

import config
from ..utils.file_utils import sanitize_filename
from ..utils.message_templates import MessageTemplate
from .download_support import record_download_success

logger = logging.getLogger(__name__)


def _parse_ratio(value: str | None) -> float | None:
    if not value or value in {"0:1", "1:0", "0:0"}:
        return None

    try:
        numerator, denominator = value.split(":", 1)
        numerator_int = int(numerator)
        denominator_int = int(denominator)
    except (TypeError, ValueError):
        return None

    if numerator_int <= 0 or denominator_int <= 0:
        return None

    return numerator_int / denominator_int


def _probe_video_metadata(file_path: str) -> dict:
    ffprobe_path = shutil.which("ffprobe")
    if not ffprobe_path:
        return {}

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration,sample_aspect_ratio:stream_tags=rotate:stream_side_data=rotation:format=duration",
        "-of",
        "json",
        file_path,
    ]

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        payload = json.loads(completed.stdout or "{}")
    except Exception as exc:
        logger.debug("Не удалось получить metadata видео через ffprobe: %s", exc)
        return {}

    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    metadata: dict[str, int] = {}

    width = stream.get("width")
    height = stream.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        sar = _parse_ratio(stream.get("sample_aspect_ratio"))
        if sar and sar != 1:
            width = max(1, round(width * sar))

        rotation = 0
        try:
            rotation = int((stream.get("tags") or {}).get("rotate") or 0)
        except (TypeError, ValueError):
            rotation = 0

        for side_data in stream.get("side_data_list") or []:
            try:
                rotation = int(side_data.get("rotation"))
                break
            except (TypeError, ValueError):
                continue

        if abs(rotation) % 180 == 90:
            width, height = height, width

        metadata["width"] = width
        metadata["height"] = height

    duration = stream.get("duration") or (payload.get("format") or {}).get("duration")
    try:
        duration_int = round(float(duration))
    except (TypeError, ValueError):
        duration_int = 0
    if duration_int > 0:
        metadata["duration"] = duration_int

    return metadata


def _video_metadata_from_info(info: dict) -> dict:
    metadata: dict[str, int] = {}

    width = info.get("width")
    height = info.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        metadata["width"] = width
        metadata["height"] = height

    duration = info.get("duration")
    try:
        duration_int = round(float(duration))
    except (TypeError, ValueError):
        duration_int = 0
    if duration_int > 0:
        metadata["duration"] = duration_int

    return metadata


def _is_upload_transport_error(exc: Exception) -> bool:
    error_text = str(exc).lower()
    markers = (
        "clientdecodeerror",
        "failed to decode object",
        "connection reset",
        "server disconnected",
        "clientoserror",
        "request timeout",
        "timeout error",
    )
    return any(marker in error_text for marker in markers)


def _extract_file_id(res, attr: str) -> str | None:
    try:
        if res and hasattr(res, attr) and getattr(res, attr):
            return getattr(res, attr).file_id
        if isinstance(res, dict) and attr in res:
            return res[attr]['file_id']
    except Exception:
        pass
    return None


def send_file_with_retry(task, file_path, title, bot, thumbnail_path: str = None) -> dict | None:
    from ..utils.error_handler import get_error_handler
    from ..utils.retry_manager import (
        NonRetryableError,
        UPLOAD_RETRY_CONFIG,
        get_smart_retry_manager,
    )

    error_handler = get_error_handler()
    retry_manager = get_smart_retry_manager(UPLOAD_RETRY_CONFIG)

    file_extension = Path(file_path).suffix.lower()
    audio_extensions = [".mp3", ".m4a", ".aac", ".ogg", ".wav", ".flac"]
    original_title = task.info.get("title") or task.info.get("id") or title or "video"
    file_size_bytes = os.path.getsize(file_path)
    file_size_mb = file_size_bytes / (1024 * 1024)
    video_metadata = _probe_video_metadata(file_path) or _video_metadata_from_info(task.info)

    # result_holder - обычная локальная переменная замыкания, отдельная на
    # каждый вызов send_file_with_retry. В отличие от патчинга методов bot
    # (что было тут раньше), это не разделяемое между параллельными
    # загрузками состояние, так что гонки нет.
    result_holder: dict = {}

    def send_as_document(caption):
        visible_file_name = (
            f"{sanitize_filename(original_title) or 'video'}"
            f"{file_extension or '.mp4'}"
        )
        logger.debug(
            "Sending file as document: task_id=%s size=%.1fMB path=%s",
            task.task_id,
            file_size_mb,
            file_path,
        )
        res = bot.send_document(
            task.chat_id,
            file_path,
            caption=caption,
            parse_mode="HTML",
            timeout=600,
            reply_to_message_id=task.reply_to_id,
            visible_file_name=visible_file_name,
        )
        file_id = _extract_file_id(res, "document")
        if file_id:
            result_holder['file_id'] = file_id
            result_holder['type'] = 'document'

    def send_operation():
        duration = video_metadata.get("duration") or task.info.get("duration")
        safe_duration = int(duration) if isinstance(duration, (int, float)) and duration > 0 else None
        caption = MessageTemplate.format_caption(
            title=original_title,
            url=task.url,
            action="audio" if task.action == "audio" else "video",
            file_size=file_size_mb,
            chat_id=task.chat_id,
            description=task.info.get("description"),
        )

        if task.action == "audio" and file_extension in audio_extensions:
            audio_kwargs = {}
            if safe_duration is not None:
                audio_kwargs["duration"] = safe_duration

            try:
                res = bot.send_audio(
                    task.chat_id,
                    file_path,
                    title=original_title,
                    performer=task.info.get("uploader", "Unknown"),
                    timeout=300,
                    reply_to_message_id=task.reply_to_id,
                    **audio_kwargs,
                )
                file_id = _extract_file_id(res, "audio")
                if file_id:
                    result_holder['file_id'] = file_id
                    result_holder['type'] = 'audio'
            except Exception as exc:
                if not _is_upload_transport_error(exc):
                    raise
                logger.warning(
                    "Audio upload failed, retrying as document: task_id=%s error=%s",
                    task.task_id,
                    exc,
                )
                send_as_document(caption)
            return

        if not config.BOT_API_IS_LOCAL and file_size_bytes > config.SEND_AS_DOC_LIMIT:
            send_as_document(caption)
            return

        logger.debug(
            "Sending file as video: task_id=%s size=%.1fMB path=%s metadata=%s",
            task.task_id,
            file_size_mb,
            file_path,
            video_metadata,
        )
        video_kwargs = {}
        if safe_duration is not None:
            video_kwargs["duration"] = safe_duration
        if video_metadata.get("width") and video_metadata.get("height"):
            video_kwargs["width"] = video_metadata["width"]
            video_kwargs["height"] = video_metadata["height"]
        if thumbnail_path and os.path.exists(thumbnail_path):
            video_kwargs["thumbnail"] = thumbnail_path
            logger.info(
                "Thumbnail: task_id=%s передаю в send_video path=%s (%d байт)",
                task.task_id, thumbnail_path, os.path.getsize(thumbnail_path),
            )
        else:
            logger.info(
                "Thumbnail: task_id=%s send_video БЕЗ thumbnail (thumbnail_path=%r, exists=%s)",
                task.task_id, thumbnail_path,
                os.path.exists(thumbnail_path) if thumbnail_path else None,
            )

        try:
            res = bot.send_video(
                task.chat_id,
                file_path,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
                timeout=600,
                reply_to_message_id=task.reply_to_id,
                **video_kwargs,
            )
            file_id = _extract_file_id(res, "video")
            if file_id:
                result_holder['file_id'] = file_id
                result_holder['type'] = 'video'
                if video_metadata.get("width") and video_metadata.get("height"):
                    result_holder['width'] = video_metadata["width"]
                    result_holder['height'] = video_metadata["height"]
                if safe_duration is not None:
                    result_holder['duration'] = safe_duration
        except Exception as exc:
            if not _is_upload_transport_error(exc):
                raise
            logger.warning(
                "Video upload failed, retrying as document: task_id=%s error=%s",
                task.task_id,
                exc,
            )
            send_as_document(caption)

    def on_retry(attempt, delay):
        if not task.silent_mode:
            try:
                bot.edit_message_text(
                    f"📤 Отправка файла (попытка {attempt})...\n"
                    f"⏱️ Ожидание {delay:.0f} сек",
                    task.chat_id,
                    task.message_id,
                )
            except Exception:
                pass

    def on_failure(attempt, exception):
        if exception and not task.silent_mode:
            error_msg = error_handler.handle_error(exception)
            try:
                bot.edit_message_text(error_msg.user_message, task.chat_id, task.message_id)
            except Exception:
                pass

    try:
        retry_manager.retry_operation_smart(
            send_operation,
            operation_id=f"upload_{task.task_id}",
            on_retry=on_retry,
            on_failure=on_failure,
        )
        stats_action = "audio" if task.action == "audio" else "video"
        record_download_success(task.chat_id, action=stats_action, file_size_mb=file_size_mb)
        return result_holder or None
    except Exception as exc:
        logger.error("Ошибка при отправке файла после всех попыток: %s", exc)
        raise NonRetryableError(f"Upload failed after retries: {exc}") from exc
