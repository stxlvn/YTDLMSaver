import logging
import os
from pathlib import Path
from aiogram.types import FSInputFile
import config
from ..utils.message_templates import MessageTemplate

logger = logging.getLogger(__name__)

def send_file_with_retry(task, file_path: str, title: str, bot, thumbnail_path: str = None, video_width: int = None, video_height: int = None) -> dict | None:
    # Мы оставили название функции старым, чтобы не сломать другие файлы,
    # но внутри никаких ретраев больше нет! Строго одна попытка.
    # Возвращает {"file_id": ..., "type": ...} вместо мутации bot-объекта,
    # чтобы избежать гонки при параллельных загрузках (см. download_handler.py).
    if Path(file_path).suffix.lower() in {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'}:
        return _send_video(task, file_path, title, bot, thumbnail_path, video_width, video_height)
    return _send_document(task, file_path, title, bot)

def _get_best_caption(task, original_title):
    info = getattr(task, 'info', {})
    title = info.get('title') or original_title
    desc = info.get('description')
    return MessageTemplate.format_caption(title, getattr(task, 'url', ''), getattr(task, 'action', 'video'), chat_id=task.chat_id, description=desc)

def _extract_file_id(res, attr: str) -> str | None:
    try:
        if res and hasattr(res, attr) and getattr(res, attr):
            return getattr(res, attr).file_id
        if isinstance(res, dict) and attr in res:
            return res[attr]['file_id']
    except Exception:
        pass
    return None

def _send_video(task, file_path: str, title: str, bot, thumbnail_path: str = None, video_width: int = None, video_height: int = None) -> dict | None:
    full_caption = _get_best_caption(task, title)
    part1, part2 = MessageTemplate.split_caption(full_caption, 1024)

    # Устанавливаем жесткий таймаут 5 минут (300 сек) на один запрос
    kwargs = {'chat_id': task.chat_id, 'video': FSInputFile(file_path), 'caption': part1, 'parse_mode': 'HTML', 'supports_streaming': True, 'request_timeout': 300}
    if thumbnail_path and os.path.exists(thumbnail_path): kwargs['thumbnail'] = FSInputFile(thumbnail_path)
    if video_width: kwargs['width'] = video_width
    if video_height: kwargs['height'] = video_height
    duration = getattr(task, 'info', {}).get('duration')
    if duration:
        try:
            kwargs['duration'] = int(duration)
        except Exception:
            pass

    try:
        res = bot.send_video(**kwargs)
        if part2:
            try: bot.send_message(chat_id=task.chat_id, text=part2, parse_mode='HTML')
            except Exception: pass
        if res is None:
            return None
        return {"file_id": _extract_file_id(res, "video"), "type": "video"}
    except Exception as e:
        logger.error(f"Ошибка отправки видео: {e}")
        raise e

def _send_document(task, file_path: str, title: str, bot) -> dict | None:
    full_caption = _get_best_caption(task, title)
    part1, part2 = MessageTemplate.split_caption(full_caption, 1024)

    try:
        res = bot.send_document(chat_id=task.chat_id, document=FSInputFile(file_path), caption=part1, parse_mode='HTML', request_timeout=300)
        if part2:
            try: bot.send_message(chat_id=task.chat_id, text=part2, parse_mode='HTML')
            except Exception: pass
        if res is None:
            return None
        return {"file_id": _extract_file_id(res, "document"), "type": "document"}
    except Exception as e:
        logger.error(f"Ошибка отправки документа: {e}")
        raise e
