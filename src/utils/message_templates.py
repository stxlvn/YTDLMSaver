from html import escape
from typing import Optional, Tuple
import re
from .i18n import i18n

class MessageTemplate:
    @staticmethod
    def _escape_text(value: Optional[str]) -> str:
        # Экранируем спецсимволы HTML, чтобы они не ломали разметку
        return escape(str(value or ""))

    @staticmethod
    def format_caption(title: str, url: str, action: str = "video", file_size: Optional[float] = None, chat_id: int = 0, description: Optional[str] = None) -> str:
        # Экранируем контент ДО того, как обернем его в теги
        safe_title = MessageTemplate._escape_text(title).strip()
        safe_desc = MessageTemplate._escape_text(description).strip()

        ignore_list = ["short video", "photo post", "video", ""]
        if safe_title.lower() in ignore_list: safe_title = ""
        if safe_desc.lower() in ignore_list: safe_desc = ""

        parts = []
        if safe_title: parts.append(f"🎬 <b>{safe_title}</b>")
        if safe_desc and safe_desc != safe_title: parts.append(f"<blockquote expandable>{safe_desc}</blockquote>")
        
        return "\n\n".join(parts)

    @staticmethod
    def split_caption(text: str, max_len: int = 1000) -> Tuple[str, str]:
        if len(text) <= max_len: return text, ""
        
        # Пытаемся найти точку разрыва
        split_pos = max_len
        
        # Ищем разрыв по знакам препинания, но ТОЛЬКО если это не внутри тега
        search_area = text[:max_len]
        # Простая проверка: если мы внутри тега (количество < больше количества >), отступаем назад
        if search_area.count('<') > search_area.count('>'):
            split_pos = search_area.rfind('<')
        
        # Если разрыв внутри тега не случился, ищем конец предложения
        if split_pos == max_len:
            for i in range(max_len - 1, max_len - 300, -1):
                if text[i] in {'.', '!', '?'}:
                    split_pos = i + 1
                    break
        
        part1 = text[:split_pos].rstrip()
        part2 = text[split_pos:].lstrip()

        # Восстановление тегов
        # Если открыли блок, но не закрыли
        if part1.count('<blockquote') > part1.count('</blockquote>'):
            part1 += "</blockquote>"
            part2 = "<blockquote expandable>" + part2
            
        return part1, part2

class ErrorMessages:
    VIDEO_DURATION_LIMIT = "❌ Видео слишком длинное. Максимальная длительность: {max_duration} мин."
    FILE_SIZE_LIMIT = "❌ Файл слишком большой для отправки."
    PLAYLIST_LIMIT = "❌ Слишком много элементов в плейлисте. Максимум: {max_items}."
    
    @staticmethod
    def get_user_message(error_str: str, chat_id: int = 0) -> str:
        return i18n.get(chat_id, "err_unknown")

    @staticmethod
    def format_error_with_suggestion(error_str: str, chat_id: int = 0, suggestion: str = None) -> str:
        return str(error_str)
