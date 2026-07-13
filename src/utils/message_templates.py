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
    # chat_id принимается для совместимости с вызовами из download_handler.py
    # (i18n-ориентированный код), но пока не используется для локализации
    # ниже - подробная классификация ошибок ниже унаследована из форка и
    # хардкодит русский текст, как было и там.
    # Ошибки, связанные с платформой/видео
    UNAVAILABLE_VIDEO = "❌ Это видео недоступно или было удалено с платформы."
    PRIVATE_VIDEO = "❌ Это приватное видео. Доступ запрещён."
    BLOCKED_VIDEO = "❌ Это видео заблокировано в вашей стране или недоступно."
    RESTRICTED_VIDEO = "❌ Это видео ограничено в доступе. Требуется авторизация."
    REMOVED_VIDEO = "❌ Это видео было удалено или больше недоступно."
    
    # Ошибки со скачиванием
    DOWNLOAD_FAILED = "❌ Не удалось скачать видео. Попробуйте позже."
    DOWNLOAD_TIMEOUT = "⏱️ Время скачивания истекло. Ссылка может быть неправильной или видео слишком большое."
    DOWNLOAD_RESOURCE_LIMIT = "⚠️ Сервер не вытянул загрузку или склейку этого видео."
    DOWNLOAD_ERROR = "❌ Ошибка при скачивании видео. Проверьте ссылку и попробуйте снова."
    NETWORK_ERROR = "🌐 Ошибка подключения. Проверьте интернет и повторите попытку."
    
    # Ошибки с отправкой
    UPLOAD_FAILED = "📤 Не удалось отправить файл. Попробуйте позже."
    UPLOAD_TIMEOUT = "⏱️ Время отправки истекло. Попробуйте файл меньшего размера."
    FILE_TOO_LARGE = "📦 Файл слишком большой для отправки через текущий Bot API."
    
    # Ошибки с форматом
    UNSUPPORTED_FORMAT = "🎯 Этот формат не поддерживается."
    CONVERSION_ERROR = "⚙️ Ошибка при конвертации файла. Попробуйте другое качество."
    QUALITY_NOT_AVAILABLE = "🎯 Для этого видео нет выбранного качества. Попробуйте другое качество."
    
    # Ошибки с лимитами
    FILE_SIZE_LIMIT = "📦 Файл слишком большой. Попробуйте скачать в более низком качестве (480p, MP3)."
    VIDEO_DURATION_LIMIT = "⏱️ Видео слишком длинное. Максимум {max_duration} минут для free-пользователей."
    PLAYLIST_LIMIT = "🎶 Плейлист слишком большой. Максимум {max_items} видео для free-пользователей."
    CONCURRENT_LIMIT = "⏸️ Слишком много одновременных загрузок. Подождите завершения текущих."
    RATE_LIMIT = "⚠️ Слишком много запросов. Пожалуйста, подождите немного и попробуйте снова."
    
    # Ошибки с субтитрами
    SUBTITLES_NOT_FOUND = "📝 Для этого видео нет доступных субтитров."
    SUBTITLES_DOWNLOAD_FAILED = "📝 Не удалось скачать субтитры. Возможно, сервер их заблокировал."
    
    # Ошибки с превью
    THUMBNAIL_NOT_FOUND = "🖼️ Превью для этого видео недоступно."
    THUMBNAIL_DOWNLOAD_FAILED = "🖼️ Не удалось скачать превью видео."
    
    # Ошибки с GIF
    GIF_CONVERSION_FAILED = "✨ Не удалось создать GIF. Видео может быть повреждено."
    GIF_FFMPEG_MISSING = "✨ FFmpeg не установлен. GIF недоступен."
    
    # Ошибки с URL/ссылкой
    INVALID_URL = "🔗 Загрузчик не смог обработать эту ссылку."
    MALFORMED_URL = "🔗 Ссылка повреждена или неправильного формата."
    UNSUPPORTED_PLATFORM = "🌐 Эта платформа не поддерживается. Попробуйте другой сервис."
    
    # Общие ошибки
    UNKNOWN_ERROR = "⚠️ Неизвестная ошибка при обработке. Попробуйте позже."
    INTERNAL_ERROR = "⚠️ Ошибка на сервере бота. Пожалуйста, попробуйте позже."
    
    @staticmethod
    def get_user_message(error_str: str, chat_id: int = 0) -> str:
        error_lower = error_str.lower()
        
        checks = [
            ("unavailable", ErrorMessages.UNAVAILABLE_VIDEO),
            ("private", ErrorMessages.PRIVATE_VIDEO),
            ("blocked", ErrorMessages.BLOCKED_VIDEO),
            ("restricted", ErrorMessages.RESTRICTED_VIDEO),
            ("removed", ErrorMessages.REMOVED_VIDEO),
            ("404", ErrorMessages.UNAVAILABLE_VIDEO),
            ("file not found", ErrorMessages.UNAVAILABLE_VIDEO),
            
            ("timeout", ErrorMessages.DOWNLOAD_TIMEOUT),
            ("сервер убил", ErrorMessages.DOWNLOAD_RESOURCE_LIMIT),
            ("killed by server", ErrorMessages.DOWNLOAD_RESOURCE_LIMIT),
            ("exit code -9", ErrorMessages.DOWNLOAD_RESOURCE_LIMIT),
            ("signal 9", ErrorMessages.DOWNLOAD_RESOURCE_LIMIT),
            ("429", ErrorMessages.RATE_LIMIT),
            ("too many requests", ErrorMessages.RATE_LIMIT),
            ("connection", ErrorMessages.NETWORK_ERROR),
            ("network", ErrorMessages.NETWORK_ERROR),
            ("refused", ErrorMessages.NETWORK_ERROR),
            ("failed to establish a new connection", ErrorMessages.NETWORK_ERROR),
            ("winerror 10061", ErrorMessages.NETWORK_ERROR),
            ("timed out", ErrorMessages.DOWNLOAD_TIMEOUT),
            ("failed to decode object", ErrorMessages.UPLOAD_FAILED),
            ("clientdecodeerror", ErrorMessages.UPLOAD_FAILED),
            
            ("subtitles", ErrorMessages.SUBTITLES_NOT_FOUND),
            ("thumbnail", ErrorMessages.THUMBNAIL_NOT_FOUND),
            ("превью", ErrorMessages.THUMBNAIL_DOWNLOAD_FAILED),
            
            ("gif", ErrorMessages.GIF_CONVERSION_FAILED),
            
            ("invalid", ErrorMessages.INVALID_URL),
            ("malformed", ErrorMessages.MALFORMED_URL),
            
            ("file too large", ErrorMessages.FILE_TOO_LARGE),
            ("request entity too large", ErrorMessages.FILE_TOO_LARGE),
            ("entity too large", ErrorMessages.FILE_TOO_LARGE),
            ("file is too big", ErrorMessages.FILE_TOO_LARGE),
            ("requested format is not available", ErrorMessages.QUALITY_NOT_AVAILABLE),
            ("requested format not available", ErrorMessages.QUALITY_NOT_AVAILABLE),
            ("no video formats found", ErrorMessages.QUALITY_NOT_AVAILABLE),
            ("ffmpeg is not installed", ErrorMessages.CONVERSION_ERROR),
        ]
        
        for keyword, message in checks:
            if keyword in error_lower:
                return message
        
        return ErrorMessages.UNKNOWN_ERROR
    
    @staticmethod
    def format_error_with_suggestion(error_str: str, chat_id: int = 0, suggestion: str = None) -> str:
        message = ErrorMessages.get_user_message(error_str, chat_id)
        
        if suggestion:
            message += f"\n\n💡 {suggestion}"
        else:
            if "timeout" in error_str.lower():
                message += "\n\n💡 Попробуйте позже или выберите более низкое качество."
            elif (
                "сервер убил" in error_str.lower()
                or "killed by server" in error_str.lower()
                or "exit code -9" in error_str.lower()
                or "signal 9" in error_str.lower()
            ):
                message += "\n\n💡 Бот уже попробовал качество ниже. Если не прошло, отправьте MP3 или 480p."
            elif "too many requests" in error_str.lower():
                message += "\n\n💡 Подождите 1-2 минуты и повторите попытку."
            elif "invalid" in error_str.lower():
                message += "\n\n💡 Если это видео, попробуйте открыть его в браузере и отправить ссылку из адресной строки."
            elif "requested format is not available" in error_str.lower():
                message += "\n\n💡 Откройте кнопки качества и выберите другой вариант."
            elif "entity too large" in error_str.lower() or "file is too big" in error_str.lower():
                message += "\n\n💡 Выберите более низкое качество (480p или MP3), чтобы уложиться в лимит Telegram."
        
        return message
