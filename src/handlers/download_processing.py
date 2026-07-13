from __future__ import annotations
import logging
import yt_dlp
import config
import re
from ..core.access import build_duration_limit_error
from ..utils.ui_manager import get_ui_manager
from ..utils.i18n import i18n

logger = logging.getLogger(__name__)

# Универсальный фильтр для ЛЮБЫХ ссылок внутри Telegram
def is_telegram_link(url: str) -> bool:
    return bool(re.match(r'^https?://(t\.me|telegram\.me)/', url))

def handle_group_download(url: str, chat_id: int, message_id: int, download_manager):
    # Мгновенно отсекаем ссылки t.me (посты, каналы, файлы)
    if is_telegram_link(url):
        return
        
    bot = download_manager.bot
    s_msg = bot.send_message(chat_id, i18n.get(chat_id, "status_analysis_start"))
    try:
        from ..core.tiktok_photo_handler import is_tiktok_photo_url
        if is_tiktok_photo_url(url):
            download_manager.add_task(url=url, chat_id=chat_id, message_id=message_id, info={"title": "TikTok photo", "duration": None}, action="tiktok_photo", reply_to_id=message_id, silent_mode=True)
            bot.delete_message(chat_id, s_msg.message_id)
            return

        bot.edit_message_text(i18n.get(chat_id, "status_analyzing"), chat_id, s_msg.message_id)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "cookiefile": config.COOKIES_FILE,
            "nocheckcertificate": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        if not info:
            try: bot.delete_message(chat_id, s_msg.message_id)
            except Exception: pass
            return
        
        download_manager.add_task(url=url, chat_id=chat_id, message_id=s_msg.message_id, info=info, action="medium", reply_to_id=message_id, silent_mode=False)
        
    except Exception as exc:
        error_text = str(exc)
        if "Unsupported URL" not in error_text:
            logger.error(f"Group {chat_id}: Ошибка: {error_text}")
            
        try: bot.delete_message(chat_id, s_msg.message_id)
        except Exception: pass

def extract_video_info(bot, chat_id: int, user_message_id: int, url: str, status_message_id: int, cache: dict[int, dict], *, download_manager, build_download_limit_text, build_download_markup):
    ui_manager = get_ui_manager()
    
    # В личных сообщениях тоже блокируем Telegram-ссылки
    if is_telegram_link(url):
        try: bot.delete_message(chat_id, status_message_id)
        except Exception: pass
        return

    try:
        from ..core.video_info import fetch_video_info
        info = fetch_video_info(url)
        if not info:
            bot.edit_message_text(ui_manager.format_panel(i18n.get(chat_id, "status_link_unreadable"), [i18n.get(chat_id, "status_link_unreadable_desc")], icon="❌"), chat_id, status_message_id)
            return
        
        resolutions = {item.get("height"): item for item in info.get("formats", []) if item and item.get("height") and item.get("vcodec") != "none"}
        cache[user_message_id] = {"url": url, "info": info, "resolutions": resolutions, "chat_id": chat_id}
        bot.edit_message_text(ui_manager.format_panel(i18n.get(chat_id, "status_found_title"), [f"🎬 {info.get('title', 'video')}", "", i18n.get(chat_id, "status_found_desc")], icon="✅"), chat_id, status_message_id, reply_markup=build_download_markup(user_message_id, info, resolutions))
    except Exception as exc:
        error_text = str(exc)
        if "Unsupported URL" in error_text:
            try: bot.delete_message(chat_id, status_message_id)
            except Exception: pass
        else:
            bot.edit_message_text(ui_manager.format_panel(i18n.get(chat_id, "status_processing_err"), [error_text], icon="❌"), chat_id, status_message_id)
            logger.error("Ошибка extract_video_info: %s", exc)
