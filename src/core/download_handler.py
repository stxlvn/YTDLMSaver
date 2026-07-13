import logging
import os
import shutil
import subprocess
import json
import tempfile
import threading
import yt_dlp
import config
from ..utils.admin_notifier import notify_admins
from ..utils.file_utils import sanitize_filename
from ..utils.i18n import i18n
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
# RLock (не Lock): update_file_cache_entry держит блокировку на весь
# read-modify-write, и при этом дергает _read_cache_locked/_write_cache_locked
# из того же треда - обычный Lock тут заклинил бы поток сам на себя.
_cache_lock = threading.RLock()

def _read_cache_locked():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _write_cache_locked(cache_data):
    # Атомарная запись через temp-файл + os.replace: конкурентный читатель
    # никогда не увидит частично записанный JSON.
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(CACHE_FILE), suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, CACHE_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

def load_file_cache():
    with _cache_lock:
        return _read_cache_locked()

def save_file_cache(cache_data):
    with _cache_lock:
        try:
            _write_cache_locked(cache_data)
        except Exception as e:
            logger.error(f"Ошибка сохранения кеша файлов: {e}")

def update_file_cache_entry(cache_key, entry):
    # Держит lock на весь read-modify-write, иначе два параллельных
    # воркера, сохраняющих разные cache_key почти одновременно, теряют
    # запись друг друга (оба прочитали кеш до того, как другой его записал).
    with _cache_lock:
        cache = _read_cache_locked()
        cache[cache_key] = entry
        try:
            _write_cache_locked(cache)
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
        "cookiefile": config.COOKIES_FILE,
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
        if task.action == "instagram_photo":
            _download_and_send_instagram_photos(task, bot, temp_dir)
            return

        retry_manager = get_smart_retry_manager(DOWNLOAD_RETRY_CONFIG)

        def download_with_retry():
            _download_and_send_video(task, bot, temp_dir)

        def on_retry(attempt, delay):
            if not task.silent_mode:
                try:
                    bot.edit_message_text(i18n.get(task.chat_id, "status_retry", attempt=attempt, delay=int(delay)), task.chat_id, task.message_id)
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

        download_with_retry()
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
                    user_message = i18n.get(task.chat_id, "err_gif_ffmpeg")
                else:
                    user_message = i18n.get(task.chat_id, "err_ffmpeg_missing")
            else:
                user_message = ErrorMessages.format_error_with_suggestion(error_text, task.chat_id)

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


def _download_and_send_instagram_photos(task, bot, temp_dir):
    part2 = ''
    from aiogram.types import InputMediaPhoto, InputMediaVideo, BufferedInputFile

    work_dir = ensure_task_work_dir(task, temp_dir)

    if not task.silent_mode:
        try:
            bot.edit_message_text(i18n.get(task.chat_id, "status_ig"), task.chat_id, task.message_id)
        except Exception:
            pass

    clean_url = task.url.split('?')[0]
    cookie_file = config.COOKIES_FILE

    def run_gdl(use_cookies):
        cmd = [
            "/root/ReSave/venv/bin/gallery-dl",
            "--directory", str(work_dir)
        ]
        if use_cookies and os.path.exists(cookie_file):
            cmd.extend(["--cookies", cookie_file])
        cmd.append(clean_url)
        try:
            return subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
        except subprocess.TimeoutExpired:
            logger.error("gallery-dl завис и был принудительно убит по таймауту (45 сек)!")
            class DummyProcess:
                returncode = 1
                stderr = "Таймаут ожидания ответа от Instagram (45 сек)."
            return DummyProcess()

    logger.info(f"Пробуем gallery-dl с куками: {clean_url}")
    proc = run_gdl(use_cookies=True)

    if proc.returncode != 0:
        logger.warning(f"gallery-dl (с куками) не справился. Пробуем без куков...")
        proc = run_gdl(use_cookies=False)
        if proc.returncode != 0:
            logger.error(f"gallery-dl упал окончательно: {proc.stderr}")
            raise RuntimeError(i18n.get(task.chat_id, "err_ig_blocked"))

    image_files = []
    for root, dirs, files in os.walk(work_dir):
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov', '.webm')):
                image_files.append(os.path.join(root, file))

    if not image_files:
        raise FileNotFoundError(i18n.get(task.chat_id, "err_ig_not_found"))

    image_files.sort()

    if not task.silent_mode:
        try:
            bot.edit_message_text(i18n.get(task.chat_id, "status_send_pic"), task.chat_id, task.message_id)
        except Exception:
            pass

    from ..utils.message_templates import MessageTemplate
    caption = MessageTemplate.format_caption(task.info.get("title", ""), clean_url, "instagram_photo", chat_id=task.chat_id, description=task.info.get("description"))

    try:
        part1, part2 = MessageTemplate.split_caption(caption, 1024)
        if len(image_files) == 1:
            with open(image_files[0], 'rb') as f:
                ext = image_files[0].lower().split('.')[-1]
                if ext in ['mp4', 'mov', 'webm']:
                    bot.send_video(task.chat_id, BufferedInputFile(f.read(), filename=f"video.{ext}"), caption=part1, parse_mode="HTML", supports_streaming=True)
                else:
                    bot.send_photo(task.chat_id, BufferedInputFile(f.read(), filename="photo.jpg"), caption=part1, parse_mode="HTML")
        else:
            for offset in range(0, len(image_files), 10):
                chunk = image_files[offset:offset+10]
                if len(chunk) == 1:
                    with open(chunk[0], 'rb') as f:
                        bot.send_photo(task.chat_id, BufferedInputFile(f.read(), filename="photo.jpg"), caption=part1 if offset == 0 else None, parse_mode="HTML")
                else:
                    media = []
                    for idx, path in enumerate(chunk):
                        with open(path, 'rb') as f:
                            ext = path.lower().split('.')[-1]
                            is_vid = ext in ['mp4', 'mov', 'webm']
                            media_class = InputMediaVideo if is_vid else InputMediaPhoto
                            media.append(
                                media_class(
                                    media=BufferedInputFile(f.read(), filename=f"media_{idx}.{ext}"),
                                    caption=part1 if offset == 0 and idx == 0 else None,
                                    parse_mode="HTML" if offset == 0 and idx == 0 else None
                                )
                            )
                    bot.send_media_group(task.chat_id, media)
    except Exception as e:
        logger.error(f"Ошибка при отправке фото: {e}")
        raise

    if part2:
        try: bot.send_message(task.chat_id, text=part2, parse_mode='HTML')
        except Exception: pass

    if not task.silent_mode:
        try:
            bot.delete_message(task.chat_id, task.message_id)
        except Exception:
            pass


def _download_and_send_video(task, bot, temp_dir):
    part2 = ''
    url_lower = task.url.lower()
    is_social_short = any(x in url_lower for x in ['tiktok.com', 'instagram.com/reel', 'youtube.com/shorts', 'youtu.be/shorts'])

    cache_key = f"{task.url}_{task.action}_{task.format_param}"
    file_cache = load_file_cache()

    if cache_key in file_cache:
        cached = file_cache[cache_key]
        file_id = cached.get("file_id")
        media_type = cached.get("type", "video")
        c_width = cached.get("width")
        c_height = cached.get("height")
        c_duration = cached.get("duration")

        if file_id:
            if not task.silent_mode:
                try:
                    bot.edit_message_text(i18n.get(task.chat_id, "status_cache"), task.chat_id, task.message_id)
                except Exception:
                    pass
            try:
                from ..utils.message_templates import MessageTemplate
                c_title = cached.get("title") or getattr(task, "info", {}).get("title") or ""
                c_desc = cached.get("description") or getattr(task, "info", {}).get("description")
                c_caption = MessageTemplate.format_caption(c_title, getattr(task, "url", ""), getattr(task, "action", "video"), chat_id=task.chat_id, description=c_desc)
                part1, part2 = MessageTemplate.split_caption(c_caption, 1024)
                if media_type == "video":
                    kwargs = {'supports_streaming': True, 'caption': part1, 'parse_mode': 'HTML'}
                    if c_width: kwargs['width'] = c_width
                    if c_height: kwargs['height'] = c_height
                    
                    # Читаем duration из кеша или задачи
                    dur = c_duration or getattr(task, "info", {}).get("duration")
                    if dur: kwargs['duration'] = int(dur)
                    
                    bot.send_video(task.chat_id, file_id, **kwargs)
                elif media_type == "audio":
                    bot.send_audio(task.chat_id, file_id, caption=part1, parse_mode='HTML')
                else:
                    bot.send_document(task.chat_id, file_id, caption=part1, parse_mode='HTML')
                if part2:
                    try: bot.send_message(task.chat_id, text=part2, parse_mode='HTML')
                    except Exception: pass
                if not task.silent_mode:
                    try:
                        bot.delete_message(task.chat_id, task.message_id)
                    except Exception:
                        pass
                logger.info(f"Мгновенная отправка из кеша по file_id: {cache_key}")
                return
            except Exception as cache_err:
                logger.warning(f"Кеш устарел или удален: {cache_err}. Качаем заново.")

    thumbnail_path = None

    if not is_social_short:
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
                        except Exception as resize_e:
                            logger.warning(f"Ошибка ресайза обложки: {resize_e}")
                            thumbnail_path = str(raw_thumb)
                            task.thumbnail_path = thumbnail_path
        except Exception as e:
            logger.warning(f"Не удалось подготовить thumbnail: {e}")

    title = sanitize_filename(task.info.get("title") or task.info.get("id") or "video")
    work_dir = ensure_task_work_dir(task, temp_dir)
    output_path = str(work_dir / "media")

    fmt, post, output_template = _get_format_options(task, output_path)
    if not task.silent_mode:
        bot.edit_message_text(i18n.get(task.chat_id, "status_dl"), task.chat_id, task.message_id)

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
        "progress_hooks": [ProgressHook(task, bot)],
        "extractor_args": {
            "youtube": ["player-client=mweb,default"]
        },
        "writethumbnail": not is_social_short,
    }

    postprocessors = list(post) if post else []
    if task.action != "gif" and not is_social_short:
        postprocessors.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})
    ydl_params["postprocessors"] = postprocessors

    cookiefile_path = config.COOKIES_FILE
    if os.path.exists(cookiefile_path):
        ydl_params["cookiefile"] = cookiefile_path

    ffmpeg_location = _ffmpeg_location()
    if ffmpeg_location:
        ydl_params["ffmpeg_location"] = ffmpeg_location

    with yt_dlp.YoutubeDL(ydl_params) as ydl:
        extracted = ydl.extract_info(task.url, download=True)
        if extracted:
            task.info.update(extracted)

    if task.info.get("title"):
        title = task.info.get("title")

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

    video_width = None
    video_height = None
    if task.action != "audio":
        try:
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "json", task.file_path
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            probe_data = json.loads(proc.stdout)
            if 'streams' in probe_data and len(probe_data['streams']) > 0:
                video_width = int(probe_data['streams'][0].get('width', 0))
                video_height = int(probe_data['streams'][0].get('height', 0))
        except Exception as e:
            logger.debug(f"Ошибка получения размеров (ffprobe): {e}")

    # Обновление статуса загрузки с локализацией
    if not task.silent_mode:
        bot.edit_message_text(i18n.get(task.chat_id, "status_uploading"), task.chat_id, task.message_id)

    # Не патчим bot.send_video/send_audio/send_document: bot - общий объект на
    # все воркер-треды DownloadManager, и мутация его методов "на время вызова"
    # гонится с параллельными загрузками (одна задача может откатить патч
    # другой, либо получить чужой file_id в кеш). Вместо этого send_file_with_retry
    # возвращает file_id/type напрямую.
    captured_data = send_file_with_retry(task, file_path, title, bot, thumbnail_path, video_width, video_height) or {}
    if captured_data.get('file_id'):
        update_file_cache_entry(cache_key, {
            "file_id": captured_data['file_id'],
            "type": captured_data['type'],
            "title": title,
            "description": task.info.get("description"),
            "width": video_width,
            "height": video_height,
            "duration": task.info.get("duration") # Сохраняем duration в кеш
        })

    if part2:
        try: bot.send_message(task.chat_id, text=part2, parse_mode='HTML')
        except Exception: pass

    if not task.silent_mode:
        try:
            bot.delete_message(task.chat_id, task.message_id)
        except Exception:
            pass

def _get_format_options(task, output_path):
    url_lower = task.url.lower() if hasattr(task, 'url') else ""
    is_social_short = any(x in url_lower for x in ['tiktok.com', 'instagram.com/reel', 'youtube.com/shorts', 'youtu.be/shorts'])
    SAFE_FALLBACK = "bestvideo+bestaudio/best"
    if task.action == "best":
        if is_social_short:
            fmt = f"bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/{SAFE_FALLBACK}"
            return (fmt, [], f"{output_path}.%(ext)s")
        return (SAFE_FALLBACK, [], f"{output_path}.%(ext)s")
    if task.action == "medium":
        fmt = f"bestvideo[height<=720]+bestaudio/best[height<=720]/{SAFE_FALLBACK}"
        return (fmt, [], f"{output_path}.%(ext)s")
    if task.action == "low":
        fmt = f"bestvideo[height<=480]+bestaudio/best[height<=480]/{SAFE_FALLBACK}"
        return (fmt, [], f"{output_path}.%(ext)s")
    if task.action == "audio":
        return ("bestaudio/best", [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}], f"{output_path}.mp3")
    if task.action == "gif":
        fmt = f"bestvideo[height<=480]+bestaudio/best[height<=480]/{SAFE_FALLBACK}"
        return (fmt, [], f"{output_path}.%(ext)s")
    if task.action == "res" and task.format_param:
        height = int(task.format_param)
        fmt = f"bestvideo[height={height}]+bestaudio/best[height={height}]/bestvideo[height<={height}]+bestaudio/best[height<={height}]/{SAFE_FALLBACK}"
        return (fmt, [], f"{output_path}.%(ext)s")
    return (SAFE_FALLBACK, [], f"{output_path}.%(ext)s")
