import logging
import multiprocessing
import os
import shutil
import subprocess
import sys
import json
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full

import yt_dlp
import config
from ..utils.admin_notifier import notify_admins
from ..utils.file_utils import sanitize_filename
from ..utils.i18n import i18n
from .access import build_file_size_limit_error
from .download_support import (
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

CACHE_FILE = str(Path(__file__).resolve().parents[2] / "telegram_file_cache.json")
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


# --- Изоляция скачивания yt-dlp в отдельном процессе (из origin/main) ---
# Раньше yt-dlp.extract_info(download=True) выполнялся прямо в воркер-треде:
# зависший процесс/сеть вешал воркер навсегда без таймаута. Здесь скачивание
# идёт в дочернем процессе с жёстким дедлайном - зависший процесс просто убивается.

@dataclass(frozen=True)
class DownloadVariant:
    label: str
    format: str
    postprocessors: tuple[dict, ...]
    output_template: str


def _queue_event(event_queue, event: tuple, *, block: bool = False):
    try:
        if block:
            event_queue.put(event, timeout=5)
        else:
            event_queue.put_nowait(event)
    except Full:
        pass


def _yt_dlp_download_worker(url: str, ydl_params: dict, event_queue):
    # bestvideo+bestaudio скачивается как ДВА отдельных файла в рамках одного
    # ydl.download(): видео-поток 0->100%, затем аудио-поток заново с 0->100%.
    # Раньше прогресс брался только с текущего файла, поэтому бар откатывался
    # к нулю на середине и выглядело, будто скачивает то же самое видео дважды.
    # Здесь суммируем downloaded/total по всем виденным файлам, чтобы бар
    # был монотонным и отражал прогресс по всей задаче целиком.
    file_totals: dict[str, int] = {}
    file_downloaded: dict[str, int] = {}
    # Пока не увидим hook для второго (аудио) файла, его размер неизвестен,
    # так что после завершения видео комбинированный total временно равен
    # только размеру видео - и ratio на миг показывает 100%. Как только аудио
    # начинает скачиваться, total увеличивается, и ratio просел бы обратно
    # (например 100% -> 92%). max_ratio_seen не даёт прогрессу идти назад.
    max_ratio_seen = 0.0

    def _emit_combined(speed):
        nonlocal max_ratio_seen
        overall_total = sum(file_totals.values())
        if not overall_total:
            return
        overall_downloaded = sum(file_downloaded.values())
        ratio = overall_downloaded / overall_total
        if ratio < max_ratio_seen:
            overall_downloaded = max_ratio_seen * overall_total
        else:
            max_ratio_seen = ratio
        _queue_event(event_queue, ("progress", overall_downloaded, overall_total, speed))

    def progress_hook(data):
        status = data.get("status")
        filename = data.get("filename") or data.get("tmpfilename") or "unknown"
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)
            speed = data.get("speed") or 0
            if total:
                file_totals[filename] = total
                file_downloaded[filename] = downloaded
                _emit_combined(speed)
        elif status == "finished":
            total = data.get("total_bytes") or file_totals.get(filename)
            if total:
                file_totals[filename] = total
                file_downloaded[filename] = total
                _emit_combined(0)

    try:
        child_params = dict(ydl_params)
        child_params["progress_hooks"] = [progress_hook]
        with yt_dlp.YoutubeDL(child_params) as ydl:
            ydl.download([url])
    except BaseException as exc:
        _queue_event(event_queue, ("error", type(exc).__name__, str(exc)), block=True)
    else:
        _queue_event(event_queue, ("ok", "", ""), block=True)


def _stop_process(process: multiprocessing.Process):
    if not process.is_alive():
        return

    process.terminate()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)


def _drain_download_events(event_queue, task) -> tuple | None:
    result = None

    while True:
        try:
            event = event_queue.get_nowait()
        except Empty:
            return result

        event_type = event[0]
        if event_type == "progress":
            _, downloaded, total, speed = event
            if total:
                task.progress = min(1.0, max(0.0, downloaded / total))
            task.speed_bytes_per_sec = speed or 0
        elif event_type in {"ok", "error"}:
            result = event


def _download_with_timeout(url: str, ydl_params: dict, timeout_seconds: int, task):
    child_params = dict(ydl_params)
    child_params.pop("progress_hooks", None)

    task.progress = 0.0
    task.speed_bytes_per_sec = 0.0
    task.stage = "download"
    task.stage_started_at = time.time()
    event_queue = multiprocessing.Queue(maxsize=100)
    process = multiprocessing.Process(
        target=_yt_dlp_download_worker,
        args=(url, child_params, event_queue),
        daemon=True,
    )
    process.start()

    deadline = time.monotonic() + timeout_seconds
    result = None

    while process.is_alive():
        drained = _drain_download_events(event_queue, task)
        if drained:
            result = drained

        if task.cancel_event.is_set():
            _stop_process(process)
            raise RuntimeError("Загрузка отменена пользователем")

        if time.monotonic() >= deadline:
            _stop_process(process)
            raise TimeoutError(f"Download timed out after {timeout_seconds} seconds")

        process.join(0.25)

    drained = _drain_download_events(event_queue, task)
    if drained:
        result = drained

    if result:
        status, error_type, message = result
        if status == "ok":
            task.progress = 1.0
            return
        raise RuntimeError(f"{error_type}: {message}")

    if process.exitcode:
        if process.exitcode < 0:
            signal_number = abs(process.exitcode)
            raise RuntimeError(
                "yt-dlp download process was killed by server "
                f"(signal {signal_number}, exit code {process.exitcode})"
            )
        raise RuntimeError(f"yt-dlp exited with code {process.exitcode}")


def _base_ydl_params(variant: "DownloadVariant") -> dict:
    ydl_params = {
        "format": variant.format,
        "outtmpl": variant.output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "http_chunk_size": 5 * 1024 * 1024,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 1,
        "max_filesize": config.MAX_FILE_SIZE,
        "continuedl": True,
        "overwrites": True,
        "trim_file_name": 180,
        "cookiefile": config.COOKIES_FILE,
        "nocheckcertificate": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
        },
        "extractor_args": {"youtube": ["player-client=mweb,default"]},
    }

    if variant.postprocessors:
        ydl_params["postprocessors"] = list(variant.postprocessors)

    if config.DOWNLOAD_RATE_LIMIT_BYTES > 0:
        ydl_params["ratelimit"] = config.DOWNLOAD_RATE_LIMIT_BYTES

    ffmpeg_location = _ffmpeg_location()
    if ffmpeg_location:
        ydl_params["ffmpeg_location"] = ffmpeg_location

    return ydl_params


def _clear_work_dir(work_dir):
    for path in work_dir.iterdir():
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("Не удалось очистить временный файл %s: %s", path, exc)


def _can_try_next_variant(exc: Exception) -> bool:
    error_text = str(exc).lower()
    permanent_markers = (
        "private",
        "unsupported url",
        "not a valid url",
        "copyright",
        "sign in to confirm",
        "login required",
        "video unavailable",
        "this video is unavailable",
        "403",
        "404",
    )
    return not any(marker in error_text for marker in permanent_markers)


def _format_download_failure(errors: list[str]) -> str:
    if not errors:
        return "Не удалось скачать видео"

    last_error = errors[-1]
    if any("killed by server" in error.lower() or "exit code -9" in error.lower() for error in errors):
        return (
            "Не удалось скачать видео: сервер убил процесс загрузки/склейки. "
            "Я уже попробовал качество ниже, но загрузка всё равно не прошла. "
            f"Последняя ошибка: {last_error}"
        )

    return f"Не удалось скачать видео. Последняя ошибка: {last_error}"


def _download_first_available_variant(task, bot, work_dir, variants: list["DownloadVariant"]):
    errors: list[str] = []

    for index, variant in enumerate(variants, start=1):
        if task.cancel_event.is_set():
            raise RuntimeError("Загрузка отменена пользователем")

        _clear_work_dir(work_dir)
        if not task.silent_mode:
            status_text = i18n.get(task.chat_id, "status_dl")
            if index > 1:
                status_text = f"⏬ Высокое качество не прошло, пробую {variant.label}..."
            try:
                bot.edit_message_text(status_text, task.chat_id, task.message_id)
            except Exception:
                pass

        logger.info(
            "Download format selected: task_id=%s action=%s format_param=%s variant=%s format=%s",
            task.task_id,
            task.action,
            task.format_param,
            variant.label,
            variant.format,
        )

        try:
            _download_with_timeout(
                task.url,
                _base_ydl_params(variant),
                config.DOWNLOAD_TIMEOUT_SECONDS,
                task,
            )
        except Exception as exc:
            message = str(exc)
            errors.append(f"{variant.label}: {message}")
            logger.warning(
                "Download variant failed: task_id=%s variant=%s error=%s",
                task.task_id,
                variant.label,
                message,
            )
            if index == len(variants) or not _can_try_next_variant(exc):
                raise RuntimeError(_format_download_failure(errors)) from exc
            continue

        downloaded_files = find_completed_files(work_dir)
        if downloaded_files:
            return max(downloaded_files, key=lambda path: path.stat().st_mtime)

        contents = describe_work_dir(work_dir)
        errors.append(f"{variant.label}: file not found after download ({contents})")
        logger.error(
            "Файл не найден после скачивания. task_id=%s, action=%s, work_dir=%s, contents=%s",
            task.task_id,
            task.action,
            work_dir,
            contents,
        )

    raise FileNotFoundError(_format_download_failure(errors) or "Файл не найден после скачивания")


def _height_format(height: int, *, exact_first: bool = False) -> str:
    if exact_first:
        return (
            f"best[height={height}][ext=mp4]/"
            f"bv*[height={height}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height={height}]+ba/"
            f"best[height<={height}][ext=mp4]/"
            f"best[height<={height}]/"
            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={height}]+ba/best"
        )

    return (
        f"best[height<={height}][ext=mp4]/"
        f"best[height<={height}]/"
        f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"bv*[height<={height}]+ba/best"
    )


def _unique_heights(values: list[int]) -> list[int]:
    seen = set()
    result = []
    for value in values:
        if value > 0 and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _video_height_variants(output_path: str, heights: list[int], *, exact_first: bool = False):
    capped_heights = [min(height, config.MAX_DOWNLOAD_HEIGHT) for height in heights]
    return [
        DownloadVariant(
            label=f"{height}p",
            format=_height_format(height, exact_first=exact_first and index == 0),
            postprocessors=(),
            output_template=f"{output_path}.%(ext)s",
        )
        for index, height in enumerate(_unique_heights(capped_heights))
    ]


def _get_download_variants(task, output_path) -> list["DownloadVariant"]:
    if task.action == "best":
        return _video_height_variants(output_path, [config.MAX_DOWNLOAD_HEIGHT, 720, 480, 360])

    if task.action == "medium":
        return _video_height_variants(output_path, [720, 480, 360])

    if task.action == "low":
        return _video_height_variants(output_path, [480, 360])

    if task.action == "audio":
        return [
            DownloadVariant(
                label="MP3",
                format="bestaudio/best",
                postprocessors=(
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    },
                ),
                output_template=f"{output_path}.mp3",
            )
        ]

    if task.action == "gif":
        return _video_height_variants(output_path, [480, 360])

    if task.action == "res" and task.format_param:
        height = min(int(task.format_param), config.MAX_DOWNLOAD_HEIGHT)
        fallback_heights = [candidate for candidate in [1080, 720, 480, 360] if candidate < height]
        return _video_height_variants(
            output_path,
            [height, *fallback_heights],
            exact_first=True,
        )

    return _video_height_variants(output_path, [720, 480, 360])


def handle_download_task(task, bot, temp_dir):
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

        _download_and_send_video(task, bot, temp_dir)
    except Exception as exc:
        if not task.cancel_event.is_set():
            record_failed_download(task.chat_id)
            logger.exception("Ошибка при скачивании и отправке файла: %s", exc)
            error_text = str(exc)

            if "ffmpeg" in error_text.lower():
                notify_admins(
                    bot,
                    (
                        "⚠️ [YTDLMSaver] FFmpeg issue detected\n"
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
        gallery_dl_bin = str(Path(sys.executable).with_name("gallery-dl"))
        cmd = [
            gallery_dl_bin,
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
    work_dir = ensure_task_work_dir(task, temp_dir)

    title = sanitize_filename(task.info.get("title") or task.info.get("id") or "video")
    output_path = str(work_dir / "media")

    if task.action in {"audio", "gif"} and not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is not installed on server")

    variants = _get_download_variants(task, output_path)
    file_path = _download_first_available_variant(task, bot, work_dir, variants)

    # Готовим thumbnail только теперь, ПОСЛЕ скачивания видео: _download_first_available_variant
    # чистит work_dir в начале каждой попытки (_clear_work_dir), так что thumbnail,
    # подготовленный до неё, гарантированно стирался с диска ещё до отправки -
    # send_video потом молча уходил без превью (thumbnail_path указывал на
    # уже несуществующий файл).
    if task.action not in {"audio", "gif"}:
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
                    'cookiefile': config.COOKIES_FILE,
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

    if not thumbnail_path and task.action not in {"audio", "gif"}:
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

    if task.info.get("title"):
        title = task.info.get("title")

    task.file_path = str(file_path)
    file_size_bytes = os.path.getsize(file_path)
    file_size_error = build_file_size_limit_error(task.chat_id, file_size_bytes)
    if file_size_error:
        raise RuntimeError(file_size_error)

    if task.action == "gif":
        convert_to_gif_and_send(task, file_path, bot)
        return

    if not task.silent_mode:
        bot.edit_message_text(i18n.get(task.chat_id, "status_uploading"), task.chat_id, task.message_id)

    # Не патчим bot.send_video/send_audio/send_document: bot - общий объект на
    # все воркер-треды DownloadManager, и мутация его методов "на время вызова"
    # гонится с параллельными загрузками (одна задача может откатить патч
    # другой, либо получить чужой file_id в кеш). Вместо этого send_file_with_retry
    # возвращает file_id/type/width/height напрямую.
    captured_data = send_file_with_retry(task, file_path, title, bot, thumbnail_path) or {}
    if captured_data.get('part2'):
        part2 = captured_data['part2']
    if captured_data.get('file_id'):
        update_file_cache_entry(cache_key, {
            "file_id": captured_data['file_id'],
            "type": captured_data['type'],
            "title": title,
            "description": task.info.get("description"),
            "width": captured_data.get('width'),
            "height": captured_data.get('height'),
            "duration": captured_data.get('duration') or task.info.get("duration"),
        })

    if part2:
        try: bot.send_message(task.chat_id, text=part2, parse_mode='HTML')
        except Exception: pass

    if not task.silent_mode:
        try:
            bot.delete_message(task.chat_id, task.message_id)
        except Exception:
            pass
