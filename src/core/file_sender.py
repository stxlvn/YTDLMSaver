import logging
import os
from pathlib import Path
from aiogram.types import FSInputFile
import config
from ..utils.retry_manager import get_smart_retry_manager, UPLOAD_RETRY_CONFIG

logger = logging.getLogger(__name__)

def send_file_with_retry(task, file_path: str, title: str, bot, thumbnail_path: str = None) -> bool:
    file_ext = Path(file_path).suffix.lower()
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'}
    if file_ext in video_exts:
        return _send_video_with_retry(task, file_path, title, bot, thumbnail_path)
    else:
        return _send_document_with_retry(task, file_path, title, bot)

def _send_video_with_retry(task, file_path: str, title: str, bot, thumbnail_path: str = None) -> bool:
    retry_manager = get_smart_retry_manager(UPLOAD_RETRY_CONFIG)

    def send():
        video = FSInputFile(file_path)
        kwargs = {
            'chat_id': task.chat_id,
            'video': video,
            'caption': title,
            'supports_streaming': True,
            'disable_notification': False,
            'timeout': config.UPLOAD_TIMEOUT,
        }
        if thumbnail_path and os.path.exists(thumbnail_path):
            # Используем FSInputFile для thumbnail
            kwargs['thumbnail'] = FSInputFile(thumbnail_path)
            logger.info(f"Thumbnail attached: {thumbnail_path}")
        return bot.send_video(**kwargs)

    def on_retry(attempt, delay):
        logger.warning("Повторная отправка видео (попытка %d) через %.1f сек", attempt, delay)

    def on_failure(attempt, exception):
        logger.error("Не удалось отправить видео после %d попыток: %s", attempt, exception)

    result = retry_manager.retry_operation_smart(
        send,
        operation_id=f"upload_video_{task.task_id}",
        on_retry=on_retry,
        on_failure=on_failure,
    )
    return result is not None

def _send_document_with_retry(task, file_path: str, title: str, bot) -> bool:
    retry_manager = get_smart_retry_manager(UPLOAD_RETRY_CONFIG)

    def send():
        # Для документов используем FSInputFile тоже (для единообразия)
        doc = FSInputFile(file_path)
        return bot.send_document(
            chat_id=task.chat_id,
            document=doc,
            caption=title,
            timeout=config.UPLOAD_TIMEOUT,
        )

    def on_retry(attempt, delay):
        logger.warning("Повторная отправка документа (попытка %d) через %.1f сек", attempt, delay)

    def on_failure(attempt, exception):
        logger.error("Не удалось отправить документ после %d попыток: %s", attempt, exception)

    result = retry_manager.retry_operation_smart(
        send,
        operation_id=f"upload_document_{task.task_id}",
        on_retry=on_retry,
        on_failure=on_failure,
    )
    return result is not None
