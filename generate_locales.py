import json
import os
from pathlib import Path

LOCALES_FILE = str(Path(__file__).resolve().parent / "locales.json")

LOCALES = {
    "ru": {
        "menu_welcome": "Скачиваю видео, аудио, превью и медиа по ссылке.\n\nКак начать:\n1. Отправьте ссылку на видео.\n2. Выберите качество или формат.\n3. Получите готовый файл.",
        "menu_help": "Личные сообщения\n1. Отправьте ссылку.\n2. Выберите формат.\n3. Дождитесь файла.\n\nПлатформы: YouTube, TikTok, Instagram и др.",
        "menu_stats": "📊 Ваша статистика",
        "menu_lang": "🌍 Выберите язык интерфейса:",
        "lang_changed": "🇷🇺 Язык успешно изменен на Русский!",
        
        "status_cached": "⚡ Найдено в кеше! Отправляю мгновенно...",
        "status_dl_ig": "🖼️ Скачиваю фото из Instagram...",
        "status_dl_vid": "⏬ Скачиваю видео...",
        "status_sending_pic": "📤 Отправляю фотографии...",
        "status_sending_vid": "📤 Готово! Отправляю файл ({size}MB)...",
        "status_queue": "⏳ В очереди",
        "status_calc": "Вычисляется...",
        "status_time_left": "Осталось: {time}",
        "status_no_downloads": "Активных загрузок нет",
        "status_no_downloads_desc": "Отправьте новую ссылку, и я покажу варианты скачивания.",
        "status_nothing_to_cancel": "Отменять нечего",
        "status_cancelled": "Загрузки отменены",
        
        "caption_vid": "🎬 <b>{title}</b>\n\n{hashtag}\n🔗 <a href=\"{url}\">Смотреть оригинал</a>",
        "caption_ig": "📸 <b>Instagram</b>\n\n🔗 <a href=\"{url}\">Перейти к посту</a>",
        "caption_tt_photo": "🖼️ <b>Фото из TikTok</b>\n\n#TikTok #Photo\n🔗 <a href=\"{url}\">Смотреть оригинал</a>",
        "caption_thumb": "🖼️ <b>Превью:</b> {title}\n\n{hashtag} #Thumbnail\n🔗 <a href=\"{url}\">Оригинал</a>",
        "caption_gif": "✨ <b>{title}</b>\n\n{hashtag} #GIF\n🔗 <a href=\"{url}\">Оригинал</a>",
        "caption_subs": "📝 <b>Субтитры:</b> {title}\n🗣️ Языки: {lang}\n\n🔗 <a href=\"{url}\">Оригинал</a>",
        
        "btn_cancel_all": "❌ Отменить все",
        "btn_best": "🎬 Лучшее",
        "btn_medium": "🎬 Среднее (720p)",
        "btn_low": "🎬 Низкое (480p)",
        "btn_audio": "🎵 Аудио (MP3)",
        
        "err_unavail": "❌ Это видео недоступно или было удалено.",
        "err_priv": "❌ Это приватное видео. Доступ запрещён.",
        "err_block": "❌ Видео заблокировано в вашей стране.",
        "err_size": "📦 Файл слишком большой для Telegram.",
        "err_timeout": "⏱️ Время скачивания истекло.",
        "err_network": "🌐 Ошибка подключения к серверу.",
        "err_format": "🎯 Выбранное качество недоступно.",
        "err_unknown": "⚠️ Произошла неизвестная ошибка.",
        "err_ig_blocked": "❌ Instagram заблокировал запрос. Пост удален или закрыт.",
        "err_ffmpeg": "⚠️ FFmpeg не установлен на сервере."
    },
    "en": {
        "menu_welcome": "Downloading video, audio, and media via link.\n\nHow to start:\n1. Send a link.\n2. Choose quality or format.\n3. Get your file.",
        "menu_help": "Direct messages\n1. Send a link.\n2. Choose format.\n3. Wait for the file.\n\nPlatforms: YouTube, TikTok, Instagram, etc.",
        "menu_stats": "📊 Your statistics",
        "menu_lang": "🌍 Choose interface language:",
        "lang_changed": "🇬🇧 Language successfully changed to English!",
        
        "status_cached": "⚡ Found in cache! Sending instantly...",
        "status_dl_ig": "🖼️ Downloading Instagram photos...",
        "status_dl_vid": "⏬ Downloading video...",
        "status_sending_pic": "📤 Sending photos...",
        "status_sending_vid": "📤 Done! Sending file ({size}MB)...",
        "status_queue": "⏳ In queue",
        "status_calc": "Calculating...",
        "status_time_left": "Time left: {time}",
        "status_no_downloads": "No active downloads",
        "status_no_downloads_desc": "Send a new link and I will show download options.",
        "status_nothing_to_cancel": "Nothing to cancel",
        "status_cancelled": "Downloads cancelled",
        
        "caption_vid": "🎬 <b>{title}</b>\n\n{hashtag}\n🔗 <a href=\"{url}\">Watch original</a>",
        "caption_ig": "📸 <b>Instagram</b>\n\n🔗 <a href=\"{url}\">View post</a>",
        "caption_tt_photo": "🖼️ <b>TikTok Photo</b>\n\n#TikTok #Photo\n🔗 <a href=\"{url}\">Watch original</a>",
        "caption_thumb": "🖼️ <b>Thumbnail:</b> {title}\n\n{hashtag} #Thumbnail\n🔗 <a href=\"{url}\">Original</a>",
        "caption_gif": "✨ <b>{title}</b>\n\n{hashtag} #GIF\n🔗 <a href=\"{url}\">Original</a>",
        "caption_subs": "📝 <b>Subtitles:</b> {title}\n🗣️ Languages: {lang}\n\n🔗 <a href=\"{url}\">Original</a>",
        
        "btn_cancel_all": "❌ Cancel all",
        "btn_best": "🎬 Best",
        "btn_medium": "🎬 Medium (720p)",
        "btn_low": "🎬 Low (480p)",
        "btn_audio": "🎵 Audio (MP3)",
        
        "err_unavail": "❌ This video is unavailable or was deleted.",
        "err_priv": "❌ This is a private video. Access denied.",
        "err_block": "❌ Video is blocked in your country.",
        "err_size": "📦 File is too large for Telegram.",
        "err_timeout": "⏱️ Download timeout reached.",
        "err_network": "🌐 Server connection error.",
        "err_format": "🎯 Selected quality is not available.",
        "err_unknown": "⚠️ An unknown error occurred.",
        "err_ig_blocked": "❌ Instagram blocked the request. Post is deleted or private.",
        "err_ffmpeg": "⚠️ FFmpeg is not installed on the server."
    }
}

with open(LOCALES_FILE, 'w', encoding='utf-8') as f:
    json.dump(LOCALES, f, ensure_ascii=False, indent=4)

print("✅ Файл locales.json успешно сгенерирован и содержит все строки!")
