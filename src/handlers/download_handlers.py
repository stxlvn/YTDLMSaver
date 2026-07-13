import asyncio
import logging
import re
from urllib.parse import urlsplit, urlunsplit

import config
from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from .download_processing import extract_video_info as _extract_video_info, handle_group_download as _handle_group_download
from ..utils.message_templates import ErrorMessages
from ..utils.ui_manager import get_ui_manager
from ..utils.i18n import i18n

logger = logging.getLogger(__name__)

HTTP_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
BARE_URL_RE = re.compile(
    r"(?:www\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}"
    r"(?:/[^\s<>\"'`]*)?",
    re.IGNORECASE,
)
SUPPORTED_SCHEMES = {"http", "https"}

_download_manager = None

def set_download_manager(manager):
    global _download_manager
    _download_manager = manager

def get_download_manager(): return _download_manager

def _build_download_limit_text(chat_id: int) -> str:
    active = _download_manager.get_user_task_count(chat_id) if _download_manager else 0
    return get_ui_manager().format_panel(i18n.get(chat_id, "limit_title"), [i18n.get(chat_id, "err_concurrent"), "", i18n.get(chat_id, "limit_active", active=active, max=config.MAX_DOWNLOADS_PER_USER)], icon="⏸️")

def get_markup_builder(chat_id):
    def builder(message_id, info, resolutions):
        url = info.get("webpage_url") or info.get("original_url")
        available_actions = ["best", "medium", "low", "audio", "gif"]
        if url:
            try:
                from src.core.download_handler import get_available_actions_optimized
                available_actions, info = get_available_actions_optimized(url)
            except Exception: pass

        formats = info.get("formats", []) if info else []
        if any(f and f.get("height", 0) >= 2160 for f in formats if f and f.get("vcodec") != "none") and "best" in available_actions:
            available_actions.remove("best")

        filtered_res = {h: d for h, d in resolutions.items() if not (h > 720 and "best" not in available_actions) and not (h > 480 and h <= 720 and "medium" not in available_actions) and not (h <= 480 and "low" not in available_actions)}

        rows = []
        is_yt = "youtube" in str(info.get("extractor_key") or "").lower() or "youtu" in str(url).lower()
        if is_yt and filtered_res:
            pref = [4320, 2160, 1440, 1080, 720, 480, 360]
            av = [h for h in pref if h in filtered_res]
            ex = [h for h in sorted(filtered_res.keys(), reverse=True) if h not in av]
            btns = [InlineKeyboardButton(text=i18n.get(chat_id, "btn_res", height=h), callback_data=f"dl_res_{h}_{message_id}") for h in (av + ex)[:6]]
            rows.extend([btns[i:i+2] for i in range(0, len(btns), 2)])
        else:
            fb = []
            if "best" in available_actions: fb.append([InlineKeyboardButton(text=i18n.get(chat_id, "btn_max"), callback_data=f"dl_best_{message_id}")])
            ml = []
            if "medium" in available_actions: ml.append(InlineKeyboardButton(text=i18n.get(chat_id, "btn_720"), callback_data=f"dl_medium_{message_id}"))
            if "low" in available_actions: ml.append(InlineKeyboardButton(text=i18n.get(chat_id, "btn_480"), callback_data=f"dl_low_{message_id}"))
            if ml: fb.append(ml)
            rows.extend(fb)

        if "audio" in available_actions: rows.append([InlineKeyboardButton(text=i18n.get(chat_id, "btn_audio"), callback_data=f"dl_audio_{message_id}", style="primary")])
        if info.get("duration", 999) <= 30 and "gif" in available_actions: rows.append([InlineKeyboardButton(text=i18n.get(chat_id, "btn_gif"), callback_data=f"dl_gif_{message_id}")])
        if info.get("subtitles") or info.get("automatic_captions"): rows.append([InlineKeyboardButton(text=i18n.get(chat_id, "btn_subs"), callback_data=f"dl_subtitles_{message_id}", style="primary")])
        if info.get("thumbnail"): rows.append([InlineKeyboardButton(text=i18n.get(chat_id, "btn_thumb"), callback_data=f"dl_thumbnail_{message_id}", style="success")])
        rows.append([InlineKeyboardButton(text=i18n.get(chat_id, "btn_cancel"), callback_data=f"cancel_{message_id}", style="danger")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    return builder


# --- Извлечение и нормализация URL из сообщения (из origin/main) ---
# Умеет доставать голые ссылки без http://, чистит мусор по краям и
# нормализует mobile.twitter.com/m.x.com в twitter.com для консистентности.

def _extract_url_from_entities(text: str, entities) -> str | None:
    for entity in entities or []:
        entity_url = getattr(entity, "url", None)
        if entity_url:
            return entity_url

        if getattr(entity, "type", None) != "url":
            continue

        extract_from = getattr(entity, "extract_from", None)
        if callable(extract_from):
            return extract_from(text)

    return None


def _clean_download_target(value: str) -> str:
    target = value.strip().rstrip(".,;:!?)»”’]")

    if "://" not in target and "." in target.split("/", 1)[0]:
        target = f"https://{target}"

    try:
        parsed = urlsplit(target)
    except ValueError:
        return target

    host = (parsed.hostname or "").lower()
    twitter_hosts = {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "m.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
        "m.twitter.com",
    }
    if host in twitter_hosts:
        path_parts = [part for part in parsed.path.split("/") if part]
        if (
            len(path_parts) >= 3
            and path_parts[1] in {"status", "statuses"}
            and path_parts[2].isdigit()
        ):
            return urlunsplit(
                (
                    parsed.scheme,
                    "twitter.com",
                    f"/{path_parts[0]}/status/{path_parts[2]}",
                    "",
                    "",
                )
            )

    return target


def _is_probably_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False

    if parsed.scheme and parsed.scheme.lower() not in SUPPORTED_SCHEMES:
        return False

    host = parsed.hostname or ""
    if not parsed.scheme and not host:
        return False

    if host == "localhost":
        return True

    if "." not in host:
        return False

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if ascii_host != host.lower():
        return False

    labels = ascii_host.split(".")
    tld = labels[-1]
    if len(tld) < 2 or len(tld) > 24:
        return False

    return all(
        label
        and len(label) <= 63
        and re.fullmatch(r"[a-z0-9-]+", label, re.IGNORECASE)
        and not label.startswith("-")
        and not label.endswith("-")
        for label in labels
    )


def _extract_download_target(text: str, entities, caption_entities) -> str | None:
    entity_url = (
        _extract_url_from_entities(text, entities)
        or _extract_url_from_entities(text, caption_entities)
    )
    if entity_url:
        target = _clean_download_target(entity_url)
        return target if _is_probably_url(target) else None

    match = HTTP_URL_RE.search(text) or BARE_URL_RE.search(text)
    if match:
        target = _clean_download_target(match.group(0))
        return target if _is_probably_url(target) else None

    if (
        not any(char.isspace() for char in text)
        and ("://" in text or text.lower().startswith("www."))
    ):
        target = _clean_download_target(text)
        return target if _is_probably_url(target) else None

    return None


def _run_background_thread(func, *args, label: str, **kwargs):
    # asyncio.create_task без ссылки/done-callback молча теряет исключения
    # из фоновой задачи - здесь они хотя бы попадут в лог.
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))

    def _consume_result(done_task: asyncio.Task):
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.debug("Фоновая задача отменена: %s", label)
        except Exception:
            logger.exception("Ошибка в фоновой задаче: %s", label)

    task.add_done_callback(_consume_result)
    return task


def register_download_handlers(router: Router, sync_bot):
    ui_manager = get_ui_manager()
    video_info_cache = {}

    async def process_url_message(message: Message, state: FSMContext):
        if message.from_user and message.from_user.is_bot: return
        # Не перехватываем ссылку, если пользователь сейчас в другом FSM-сценарии
        # (иначе тут раньше падал TypeError и бот молча переставал отвечать).
        if await state.get_state(): return
        text = (message.text or message.caption or "").strip()
        if not text or text.startswith("/"): return

        url = _extract_download_target(text, message.entities, message.caption_entities)
        chat_id = message.chat.id
        if not url:
            if message.chat.type == "private":
                await message.reply(ui_manager.format_panel(i18n.get(chat_id, "err_url_title"), [i18n.get(chat_id, "err_url_desc")], icon="🔗"))
            return

        is_ig = "instagram.com/p/" in url.lower()
        from ..core.tiktok_photo_handler import is_tiktok_photo_url
        is_tt = is_tiktok_photo_url(url) or ('tiktok.com' in url.lower() and '/photo/' in url.lower())

        if message.chat.type in {"group", "supergroup"} and not is_tt and not is_ig:
            logger.info("Получена ссылка в группе %s: %s", chat_id, url)
            _run_background_thread(_handle_group_download, url, chat_id, message.message_id, _download_manager, label=f"group_download:{chat_id}:{message.message_id}")
            return

        if is_tt or is_ig:
            if is_tt and '/photo/' in url.lower(): url = re.sub(r'/photo/', '/video/', url, flags=re.IGNORECASE)
            s_msg = await message.reply(ui_manager.format_panel(i18n.get(chat_id, "status_photo_title"), [i18n.get(chat_id, "status_photo_desc")], icon="🖼️"))

            # Фоновый сбор оригинального текста для картинок перед стартом загрузки
            def _bg_photo_task():
                from src.core.video_info import fetch_video_info
                info = fetch_video_info(url) or {}
                try:
                    _download_manager.add_task(
                        url=url,
                        chat_id=chat_id,
                        message_id=s_msg.message_id,
                        info={"title": info.get("title", ""), "description": info.get("description", ""), "duration": None},
                        action="tiktok_photo" if is_tt else "instagram_photo",
                        reply_to_id=message.message_id
                    )
                except ValueError:
                    try: sync_bot.edit_message_text(_build_download_limit_text(chat_id), chat_id, s_msg.message_id)
                    except Exception: pass

            _run_background_thread(_bg_photo_task, label=f"bg_photo:{chat_id}:{message.message_id}")
            return

        if any(x in url.lower() for x in ['tiktok.com', 'instagram.com/reel', 'youtube.com/shorts', 'youtu.be/shorts']):
            s_msg = await message.reply(ui_manager.format_panel(i18n.get(chat_id, "status_fast_title"), [i18n.get(chat_id, "status_fast_desc")], icon="⚡"))
            try: _download_manager.add_task(url=url, chat_id=chat_id, message_id=s_msg.message_id, info={"title": "", "duration": None}, action="best", reply_to_id=message.message_id)
            except ValueError: await s_msg.edit_text(_build_download_limit_text(chat_id))
            return

        s_msg = await message.reply(ui_manager.format_panel(i18n.get(chat_id, "status_search_title"), [i18n.get(chat_id, "status_search_desc")], icon="🔍"))
        _run_background_thread(_extract_video_info, sync_bot, chat_id, message.message_id, url, s_msg.message_id, video_info_cache, label=f"video_info:{chat_id}:{message.message_id}", download_manager=_download_manager, build_download_limit_text=_build_download_limit_text, build_download_markup=get_markup_builder(chat_id))

    async def handle_download(call: CallbackQuery):
        parts = call.data.split("_")
        action, orig_id = parts[1], int(parts[-1])
        chat_id = call.message.chat.id
        if orig_id not in video_info_cache: return await call.answer(i18n.get(chat_id, "err_expired"))
        dl_info = video_info_cache[orig_id]
        if not _download_manager.can_add_task(chat_id):
            await call.answer(i18n.get(chat_id, "err_limit_alert"), show_alert=True)
            return await call.message.edit_text(_build_download_limit_text(chat_id))
        await call.answer(i18n.get(chat_id, "status_add_queue_alert"))
        await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "status_add_queue_title"), [i18n.get(chat_id, "status_add_queue_desc")], icon="📥"))
        try: _download_manager.add_task(url=dl_info["url"], chat_id=chat_id, message_id=call.message.message_id, info=dl_info["info"], action=action, format_param=int(parts[2]) if action == "res" else None)
        except ValueError: return await call.message.edit_text(_build_download_limit_text(chat_id))
        video_info_cache.pop(orig_id, None)

    async def handle_cancel_all(call: CallbackQuery):
        chat_id = call.message.chat.id
        with _download_manager.lock:
            user_tasks = {tid: t for tid, t in _download_manager.tasks.items() if t.chat_id == chat_id and t.status in {"downloading", "pending"}}
        if not user_tasks: return await call.answer(i18n.get(chat_id, "status_no_active"))
        cc = sum(1 for tid in user_tasks if _download_manager.cancel_task(tid))
        await call.answer(i18n.get(chat_id, "status_cancelled_count", count=cc))
        await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "status_cancelled"), [i18n.get(chat_id, "status_cancelled_count", count=cc), i18n.get(chat_id, "status_can_start_new")], icon="✅ "))

    async def handle_cancel(call: CallbackQuery):
        await call.answer()
        try: await call.message.delete()
        except Exception: await call.message.edit_text(ui_manager.format_panel("Отменено", icon="✕"))

    router.message.register(process_url_message, StateFilter(None), lambda m: bool((m.text or m.caption) and not (m.text or m.caption or "").strip().startswith("/")))
    router.callback_query.register(handle_download, lambda c: bool(c.data and c.data.startswith("dl_")))
    router.callback_query.register(handle_cancel_all, lambda c: c.data == "cancel_all_downloads")
    router.callback_query.register(handle_cancel, lambda c: bool(c.data and c.data.startswith("cancel_")))
