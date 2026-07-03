import logging
import os
import shutil
import subprocess
import json
import yt_dlp
import config
from ..utils.admin_notifier import notify_admins
from ..utils.file_utils import sanitize_filename
from .access import build_file_size_limit_error
from .download_support import (
    ProgressHook,
    describe_work_dir,
    ensure_task_work_dir,
    find_completed_files,
    record_failed_download,
)
from .file_sender import send_file_with_retry
from .media_assets import (
    convert_to_gif_and_send,
    download_and_send_subtitles,
    download_and_send_thumbnail,
    download_and_send_tiktok_photos,
)

logger = logging.getLogger(__name__)

CACHE_FILE = "/root/ReSave/telegram_file_cache.json"

def load_file_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_file_cache(cache_data):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения кеша файлов: {e}")

def _ffmpeg_location() -> str | None:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return None
    return str(os.path.dirname(ffmpeg_path))

def _get_format_size(url, action, format_param=None):
    try:
        fmt = None
        if action == "best":
            fmt = "bestvideo+bestaudio/best"
        elif action == "medium":
            fmt = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        elif action == "low":
            fmt = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
        elif action == "audio":
            fmt = "bestaudio/best"
        elif action == "gif":
            fmt = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
        elif action == "res" and format_param:
            height = int(format_param)
            fmt = f"bestvideo[height={height}]+bestaudio/best[height={height}]/bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
        else:
            return None

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "format": fmt,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            total_size = 0
            if "requested_formats" in info:
                for f in info["requested_formats"]:
                    total_size += f.get("filesize", 0) or f.get("filesize_approx", 0)
            else:
                total_size = info.get("filesize", 0) or info.get("filesize_approx", 0)
            return total_size if total_size > 0 else None
    except Exception as e:
        logger.debug(f"Не удалось определить размер для {action}: {e}")
        return None

def get_available_actions_optimized(url):
    max_size = 2 * 1024 * 1024 * 1024
    default_actions = ["best", "medium", "low", "audio", "gif"]
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "cookiefile": "/root/ReSave/cookies.txt",
        "extractor_args": {"youtube": ["player-client=mweb,default"]},
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get("formats", [])
        if not formats:
            return default_actions, info

        audio_sizes = [
            f.get("filesize") or f.get("filesize_approx") or f.get("clen") or 0
            for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"
        ]
        max_audio_size = max(audio_sizes) if audio_sizes else 0

        has_low = False
        has_medium = False
        has_best = False

        for f in formats:
            if f.get("vcodec") != "none":
                size = f.get("filesize") or f.get("filesize_approx") or f.get("clen")
                if size is None:
                    continue
                total = size + max_audio_size
                if total > max_size:
                    continue
                height = f.get("height") or 0
                if height <= 480:
                    has_low = True
                if height <= 720:
                    has_medium = True
                has_best = True

        available = []
        if has_best:
            available.append("best")
        if has_medium:
            available.append("medium")
        if has_low:
            available.append("low")
        available.extend(["audio", "gif"])
        return available, info
    except Exception as e:
        logger.error(f"Size filter error: {e}")
        return default_actions, None

def handle_download_task(task, bot, temp_dir):
    from ..utils.error_handler import get_error_handler
    from ..utils.retry_manager import DOWNLOAD_RETRY_CONFIG, get_smart_retry_manager

    error_handler = get_error_handler()

    try:
        if task.action == "subtitles":
            download_and_send_subtitles(task, bot, temp_dir)
            return
        if task.action == "thumbnail":
            download_and_send_thumbnail(task, bot, temp_dir)
            return
        if task.action == "tiktok_photo":
            download_and_send_tiktok_photos(task, bot, temp_dir)
            return

        retry_manager = get_smart_retry_manager(DOWNLOAD_RETRY_CONFIG)

        def download_with_retry():
            _download_and_send_video(task, bot, temp_dir)

        def on_retry(attempt, delay):
            if not task.silent_mode:
                try:
                    bot.edit_message_text(
                        f"⚠️ Ошибка загрузки, повторная попытка {attempt}...\\n"
                        f"⏱️ Ожидание {delay:.0f} сек",
                        task.chat_id,
                        task.message_id,
                    )
                except Exception:
                    pass

        def on_failure(attempt, exception):
            if not task.silent_mode and exception:
                error_msg = error_handler.handle_error(exception)
                try:
                    bot.edit_message_text(error_msg.user_message, task.chat_id, task.message_id)
                except Exception:
                    pass
            task.error = str(exception)

        retry_manager.retry_operation_smart(
            download_with_retry,
            operation_id=f"download_{task.task_id}",
            on_retry=on_retry,
            on_failure=on_failure,
        )
    except Exception as exc:
        if not task.cancel_event.is_set():
            record_failed_download(task.chat_id)
            logger.exception("Ошибка при скачивании и отправке файла: %s", exc)

            error_text = str(exc)
            if "ffmpeg" in error_text.lower():
                notify_admins(
                    bot,
                    (
                        "⚠️ [ReSave] FFmpeg issue detected\n"
                        f"Chat ID: {task.chat_id}\n"
                        f"Action: {task.action}\n"
                        f"URL: {task.url}\n"
                        f"Error: {error_text}"
                    ),
                )

            from ..utils.message_templates import ErrorMessages

            if "ffmpeg" in error_text.lower():
                if task.action == "gif":
                    user_message = ErrorMessages.GIF_FFMPEG_MISSING
                else:
                    user_message = "⚠️ FFmpeg не установлен на сервере. Эта функция временно недоступна."
            else:
                user_message = ErrorMessages.format_error_with_suggestion(error_text)

            if not task.silent_mode:
                try:
                    bot.edit_message_text(user_message, task.chat_id, task.message_id)
                except Exception:
                    pass

            task.error = str(exc)
            raise
    finally:
        if task.file_path and os.path.exists(task.file_path):
            try:
                os.remove(task.file_path)
            except Exception:
                pass
        if task.work_dir and os.path.exists(task.work_dir):
            try:
                shutil.rmtree(task.work_dir, ignore_errors=True)
            except Exception as cleanup_error:
                logger.debug("Не удалось очистить раб. директорию %s: %s", task.work_dir, cleanup_error)

def _download_and_send_video(task, bot, temp_dir):
    # 🔥 ПРОВЕРКА КЕША ПЕРЕД СКАЧИВАНИЕМ
    cache_key = f"{task.url}_{task.action}_{task.format_param}"
    file_cache = load_file_cache()
    
    if cache_key in file_cache:
        cached = file_cache[cache_key]
        file_id = cached.get("file_id")
        media_type = cached.get("type", "video")
        
        if file_id:
            if not task.silent_mode:
                try:
                    bot.edit_message_text("⚡ Найдено в кеше! Отправляю мгновенно...", task.chat_id, task.message_id)
                except Exception:
                    pass
            try:
                if media_type == "video":
                    bot.send_video(task.chat_id, file_id)
                elif media_type == "audio":
                    bot.send_audio(task.chat_id, file_id)
                else:
                    bot.send_document(task.chat_id, file_id)
                
                if not task.silent_mode:
                    try:
                        bot.delete_message(task.chat_id, task.message_id)
                    except Exception:
                        pass
                logger.info(f"Мгновенная отправка из кеша по file_id: {cache_key}")
                return # Успешно выгружено из кеша, прерываем скачивание!
            except Exception as cache_err:
                logger.warning(f"Кеш устарел или файл удален из ТГ: {cache_err}. Качаем заново.")

    thumbnail_path = None
    
    # 1. Скачиваем обложку и ужимаем ее под лимиты Telegram API (max 320x320)
    try:
        import requests
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(task.url, download=False)
            thumbnail_url = info.get('thumbnail')
            if thumbnail_url:
                response = requests.get(thumbnail_url, timeout=10)
                if response.status_code == 200:
                    work_dir = ensure_task_work_dir(task, temp_dir)
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
                        logger.info(f"Обложка для Telegram подготовлена: {thumbnail_path}")
                    except Exception as resize_e:
                        logger.warning(f"Ошибка ресайза обложки: {resize_e}")
                        thumbnail_path = str(raw_thumb)
                        task.thumbnail_path = thumbnail_path
    except Exception as e:
        logger.warning(f"Не удалось подготовить thumbnail: {e}")

    # 2. Отправляем красивое превью фото сообщением в сам чат (до скачивания)
    if not task.silent_mode:
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(task.url, download=False)
                thumbnail_url = info.get('thumbnail')
                if thumbnail_url:
                    import requests
                    response = requests.get(thumbnail_url, timeout=10)
                    if response.status_code == 200:
                        title = info.get('title', 'Видео')
                        views = info.get('view_count')
                        caption = f"🎬 <b>{title}</b>"
                        if views:
                            caption += f"\n👁️ {views:,} просмотров"
                        bot.send_photo(
                            chat_id=task.chat_id,
                            photo=response.content,
                            caption=caption,
                            parse_mode='HTML'
                        )
        except Exception as e:
            logger.warning(f"Не удалось отправить превью в чат: {e}")

    # 3. Скачиваем само видео
    title = sanitize_filename(task.info.get("title") or task.info.get("id") or "video")
    work_dir = ensure_task_work_dir(task, temp_dir)
    output_path = str(work_dir / "media")

    fmt, post, output_template = _get_format_options(task, output_path)
    if not task.silent_mode:
        bot.edit_message_text("⏬ Скачиваю видео...", task.chat_id, task.message_id)

    ydl_params = {
        "format": fmt,
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "http_chunk_size": 10485760,
        "nocheckcertificate": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        },
        "progress_hooks": [ProgressHook(task)],
        "extractor_args": {
            "youtube": ["player-client=mweb,default"]
        },
        "writethumbnail": True,
    }

    # 🔥 Просим yt-dlp вшить обложку внутрь файла
    postprocessors = list(post) if post else []
    if task.action != "gif":
        postprocessors.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})
    ydl_params["postprocessors"] = postprocessors

    cookiefile_path = "/root/ReSave/cookies.txt"
    if os.path.exists(cookiefile_path):
        ydl_params["cookiefile"] = cookiefile_path

    ffmpeg_location = _ffmpeg_location()
    if ffmpeg_location:
        ydl_params["ffmpeg_location"] = ffmpeg_location

    with yt_dlp.YoutubeDL(ydl_params) as ydl:
        ydl.download([task.url])

    downloaded_files = find_completed_files(work_dir)
    if not downloaded_files:
        raise FileNotFoundError("Файл не найден после скачивания")

    file_path = max(downloaded_files, key=lambda path: path.stat().st_mtime)
    task.file_path = str(file_path)
    file_size_bytes = os.path.getsize(file_path)
    file_size_error = build_file_size_limit_error(task.chat_id, file_size_bytes)
    if file_size_error:
        raise RuntimeError(file_size_error)

    if task.action == "gif":
        convert_to_gif_and_send(task, file_path, bot)
        return

    if not task.silent_mode:
        size_mb = file_size_bytes / (1024 * 1024)
        bot.edit_message_text(
            f"📤 Готово! Отправляю файл ({size_mb:.1f}MB)...",
            task.chat_id,
            task.message_id,
        )

    # 🔥 ПЕРЕХВАТ FILE_ID ПРИ ОТПРАВКЕ
    captured_data = {}
    orig_send_video = bot.send_video
    orig_send_audio = bot.send_audio
    orig_send_document = bot.send_document

    def patched_send_video(chat_id, video, *args, **kwargs):
        res = orig_send_video(chat_id, video, *args, **kwargs)
        try:
            if res and hasattr(res, 'video') and res.video:
                captured_data['file_id'] = res.video.file_id
                captured_data['type'] = 'video'
            elif isinstance(res, dict) and 'video' in res:
                captured_data['file_id'] = res['video']['file_id']
                captured_data['type'] = 'video'
        except Exception:
            pass
        return res

    def patched_send_audio(chat_id, audio, *args, **kwargs):
        res = orig_send_audio(chat_id, audio, *args, **kwargs)
        try:
            if res and hasattr(res, 'audio') and res.audio:
                captured_data['file_id'] = res.audio.file_id
                captured_data['type'] = 'audio'
        except Exception:
            pass
        return res

    def patched_send_document(chat_id, document, *args, **kwargs):
        res = orig_send_document(chat_id, document, *args, **kwargs)
        try:
            if res and hasattr(res, 'document') and res.document:
                captured_data['file_id'] = res.document.file_id
                captured_data['type'] = 'document'
        except Exception:
            pass
        return res

    bot.send_video = patched_send_video
    bot.send_audio = patched_send_audio
    bot.send_document = patched_send_document

    try:
        # Передаем подготовленную обложку (thumbnail_path) в функцию отправки
        send_file_with_retry(task, file_path, title, bot, thumbnail_path)
        
        # Сохранение в кеш
        if 'file_id' in captured_data:
            current_cache = load_file_cache()
            current_cache[cache_key] = {
                "file_id": captured_data['file_id'],
                "type": captured_data['type'],
                "title": title
            }
            save_file_cache(current_cache)
            logger.info(f"Файл успешно закеширован: {cache_key}")
    finally:
        bot.send_video = orig_send_video
        bot.send_audio = orig_send_audio
        bot.send_document = orig_send_document

    if not task.silent_mode:
        try:
            bot.delete_message(task.chat_id, task.message_id)
        except Exception:
            pass

def _get_format_options(task, output_path):
    if task.action == "best":
        return ("bestvideo+bestaudio/best", [], f"{output_path}.%(ext)s")
    if task.action == "medium":
        return ("bestvideo[height<=720]+bestaudio/best[height<=720]/best", [], f"{output_path}.%(ext)s")
    if task.action == "low":
        return ("bestvideo[height<=480]+bestaudio/best[height<=480]/best", [], f"{output_path}.%(ext)s")
    if task.action == "audio":
        return ("bestaudio/best", [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}], f"{output_path}.mp3")
    if task.action == "gif":
        return ("bestvideo[height<=480]+bestaudio/best[height<=480]/best", [], f"{output_path}.%(ext)s")
    if task.action == "res" and task.format_param:
        height = int(task.format_param)
        return (
            f"bestvideo[height={height}]+bestaudio/best[height={height}]/"
            f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best",
            [],
            f"{output_path}.%(ext)s",
        )
    return ("bestvideo+bestaudio/best", [], f"{output_path}.%(ext)s")
