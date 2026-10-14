from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from aiogram import Bot, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InputRichMessage,
    Message,
    ReplyParameters,
)

import config
from ..core.user_stats import get_stats_manager
from ..utils.ui_manager import get_ui_manager
from ..utils.i18n import i18n

logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool: return user_id in config.ADMIN_IDS

class BroadcastStates(StatesGroup): waiting_for_message = State()

@dataclass
class BroadcastPayload:
    kind: str
    text: str | None = None
    caption: str | None = None
    file_id: str | None = None
    entities: list | None = None
    caption_entities: list | None = None

def _build_admin_buttons_html(chat_id: int) -> str:
    # Кнопки встроены в тело Rich-сообщения через <tg-button-row>
    # (Bot API 10.3+), а не отдельной клавиатурой через reply_markup -
    # см. core.telegram.org/bots/api#inputrichmessage, "Rich HTML style".
    ui_manager = get_ui_manager()
    return (
        ui_manager.format_rich_button_row([
            {"text": i18n.get(chat_id, "admin_btn_stats"), "callback_data": "admin_stats_global", "style": "primary"},
            {"text": i18n.get(chat_id, "admin_btn_bc"), "callback_data": "admin_broadcast", "style": "primary"},
        ])
        + ui_manager.format_rich_button_row([
            {"text": i18n.get(chat_id, "admin_btn_users"), "callback_data": "admin_user_list", "style": "primary"},
            {"text": i18n.get(chat_id, "admin_btn_clear"), "callback_data": "admin_clear_db", "style": "danger"},
        ])
    )

def _build_back_button_html(chat_id: int) -> str:
    ui_manager = get_ui_manager()
    return ui_manager.format_rich_button_row([
        {"text": i18n.get(chat_id, "admin_btn_back"), "callback_data": "admin_back"},
    ])

def _build_broadcast_waiting_button_html(chat_id: int) -> str:
    ui_manager = get_ui_manager()
    return ui_manager.format_rich_button_row([
        {"text": i18n.get(chat_id, "admin_btn_cancel"), "callback_data": "broadcast_cancel", "style": "danger"},
    ])

def _build_admin_panel_text(chat_id: int) -> str:
    ui_manager = get_ui_manager()
    all_stats = get_stats_manager().get_all_stats()
    total_downloads = sum(item.downloads_count for item in all_stats.values())
    total_videos = sum(item.total_videos for item in all_stats.values())
    total_audios = sum(item.total_audios for item in all_stats.values())
    total_other = sum(item.total_other_downloads for item in all_stats.values())
    total_failed = sum(item.failed_downloads for item in all_stats.values())
    total_size = sum(item.total_size_mb for item in all_stats.values())

    table = ui_manager.format_rich_table([
        (i18n.get(chat_id, "admin_stat_active"), str(len(all_stats))),
        (i18n.get(chat_id, "admin_stat_total"), str(total_downloads)),
        (i18n.get(chat_id, "admin_stat_vid"), str(total_videos)),
        (i18n.get(chat_id, "admin_stat_aud"), str(total_audios)),
        (i18n.get(chat_id, "admin_stat_other"), str(total_other)),
        (i18n.get(chat_id, "admin_stat_err"), str(total_failed)),
        (i18n.get(chat_id, "admin_stat_size"), f"{total_size:.1f} MB"),
    ])
    footer = i18n.get(chat_id, "admin_panel_footer")
    return f"<h3>🛠️ {i18n.get(chat_id, 'admin_panel_title')}</h3>{table}<footer>{footer}</footer>{_build_admin_buttons_html(chat_id)}"

def _build_global_stats_rich(chat_id: int, *, show_back: bool = True) -> str:
    # Пилот Rich Messages (Bot API 10.1+): реальная <table> вместо
    # "• label: value" строк - см. core.telegram.org/bots/api#inputrichmessage.
    ui_manager = get_ui_manager()
    all_stats = get_stats_manager().get_all_stats()

    total_users = len(all_stats)
    total_downloads = sum(item.downloads_count for item in all_stats.values())
    total_videos = sum(item.total_videos for item in all_stats.values())
    total_audios = sum(item.total_audios for item in all_stats.values())
    total_other = sum(item.total_other_downloads for item in all_stats.values())
    total_failed = sum(item.failed_downloads for item in all_stats.values())
    total_size = sum(item.total_size_mb for item in all_stats.values())

    avg_downloads = total_downloads / total_users if total_users else 0
    avg_size = total_size / total_downloads if total_downloads else 0
    active_users = sum(1 for item in all_stats.values() if item.downloads_count > 0)
    attempts = total_downloads + total_failed
    success_rate = (total_downloads / attempts * 100) if attempts else 0

    table = ui_manager.format_rich_table([
        (i18n.get(chat_id, "admin_stat_users"), str(total_users)),
        (i18n.get(chat_id, "admin_stat_active"), str(active_users)),
        (i18n.get(chat_id, "admin_stat_total"), str(total_downloads)),
        (i18n.get(chat_id, "admin_ul_vid"), str(total_videos)),
        (i18n.get(chat_id, "admin_ul_aud"), str(total_audios)),
        (i18n.get(chat_id, "admin_ul_other"), str(total_other)),
        (i18n.get(chat_id, "admin_stat_err"), str(total_failed)),
        (i18n.get(chat_id, "admin_stat_success"), f"{success_rate:.1f}%"),
        (i18n.get(chat_id, "admin_stat_size"), f"{total_size:.1f} MB"),
        (i18n.get(chat_id, "admin_stat_avg_size"), f"{avg_size:.2f} MB"),
        (i18n.get(chat_id, "admin_stat_avg_dl"), f"{avg_downloads:.1f}"),
    ])

    top_users = sorted(all_stats.items(), key=lambda i: i[1].downloads_count, reverse=True)[:5]
    if not top_users:
        top_block = f"<p>{i18n.get(chat_id, 'admin_no_users')}</p>"
    else:
        items = "".join(
            f"<li>ID {uid}: {i18n.get(chat_id, 'admin_dl_count', c=stats.downloads_count)}</li>"
            for uid, stats in top_users
        )
        top_block = f"<ol>{items}</ol>"

    title = i18n.get(chat_id, "admin_btn_stats").replace('📊 ', '')
    return (
        f"<h3>📊 {title}</h3>"
        f"{table}"
        f"<h3>{i18n.get(chat_id, 'admin_top_users')}</h3>"
        f"{top_block}"
        f"{_build_back_button_html(chat_id) if show_back else ''}"
    )

def _build_user_list_text(chat_id: int) -> str:
    ui_manager = get_ui_manager()
    all_stats = get_stats_manager().get_all_stats()
    user_list = sorted(all_stats.items(), key=lambda i: i[1].downloads_count, reverse=True)
    title = i18n.get(chat_id, "admin_users_title")

    if not user_list:
        return ui_manager.format_rich_panel(title, [i18n.get(chat_id, "admin_db_empty")], icon="👥") + _build_back_button_html(chat_id)

    header = ("ID", f"{i18n.get(chat_id, 'admin_ul_dl')} / {i18n.get(chat_id, 'admin_ul_vid')} / {i18n.get(chat_id, 'admin_ul_aud')} / {i18n.get(chat_id, 'admin_ul_other')} / {i18n.get(chat_id, 'admin_ul_size')}")
    rows = [
        (
            str(uid),
            f"{stats.downloads_count} / {stats.total_videos} / {stats.total_audios} / {stats.total_other_downloads} / {stats.total_size_mb:.1f} MB",
        )
        for uid, stats in user_list[:20]
    ]
    table = ui_manager.format_rich_table(rows, header=header)
    html_content = f"<h3>👥 {title}</h3>{table}"
    if len(user_list) > 20:
        html_content += f"<p>{i18n.get(chat_id, 'admin_and_more', c=len(user_list) - 20)}</p>"
    html_content += _build_back_button_html(chat_id)
    return html_content

def _extract_broadcast_payload(message: Message) -> BroadcastPayload | None:
    if message.text:
        return BroadcastPayload(
            kind="text",
            text=message.text,
            entities=list(message.entities or []),
        )

    if message.photo:
        return BroadcastPayload(
            kind="photo",
            file_id=message.photo[-1].file_id,
            caption=message.caption,
            caption_entities=list(message.caption_entities or []),
        )

    if message.video:
        return BroadcastPayload(
            kind="video",
            file_id=message.video.file_id,
            caption=message.caption,
            caption_entities=list(message.caption_entities or []),
        )

    if message.document:
        return BroadcastPayload(
            kind="document",
            file_id=message.document.file_id,
            caption=message.caption,
            caption_entities=list(message.caption_entities or []),
        )

    if message.audio:
        return BroadcastPayload(
            kind="audio",
            file_id=message.audio.file_id,
            caption=message.caption,
            caption_entities=list(message.caption_entities or []),
        )

    return None

async def _send_broadcast_payload(bot: Bot, user_id: int, payload: BroadcastPayload):
    if payload.kind == "text":
        await bot.send_message(user_id, payload.text or "", entities=payload.entities)
        return

    if payload.kind == "photo":
        await bot.send_photo(
            user_id,
            payload.file_id,
            caption=payload.caption,
            caption_entities=payload.caption_entities,
        )
        return

    if payload.kind == "video":
        await bot.send_video(
            user_id,
            payload.file_id,
            caption=payload.caption,
            caption_entities=payload.caption_entities,
        )
        return

    if payload.kind == "document":
        await bot.send_document(
            user_id,
            payload.file_id,
            caption=payload.caption,
            caption_entities=payload.caption_entities,
        )
        return

    if payload.kind == "audio":
        await bot.send_audio(
            user_id,
            payload.file_id,
            caption=payload.caption,
            caption_entities=payload.caption_entities,
        )
        return

    raise ValueError(f"Unsupported broadcast payload kind: {payload.kind}")

def register_admin_handlers(router: Router):
    ui_manager = get_ui_manager()
    broadcast_cache: dict[int, dict] = {}

    async def _reply_rich(message: Message, html_content: str, **kwargs):
        rich = InputRichMessage(html=html_content)
        return await message.bot.send_rich_message(
            message.chat.id, rich, reply_parameters=ReplyParameters(message_id=message.message_id), **kwargs
        )

    async def admin_command(message: Message, state: FSMContext):
        if not message.from_user or not is_admin(message.from_user.id): return
        chat_id = message.chat.id
        await state.clear()
        await _reply_rich(message, _build_admin_panel_text(chat_id))

    async def broadcast_command(message: Message, state: FSMContext):
        if not message.from_user or not is_admin(message.from_user.id): return
        chat_id = message.chat.id
        await state.set_state(BroadcastStates.waiting_for_message)
        await state.update_data(from_panel=False)
        await _reply_rich(message, ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_title"), [i18n.get(chat_id, "admin_bc_prompt")], icon="📣") + _build_broadcast_waiting_button_html(chat_id))

    async def process_broadcast_message(message: Message, state: FSMContext):
        if not message.from_user or not is_admin(message.from_user.id): return
        chat_id = message.chat.id
        from_panel = (await state.get_data()).get("from_panel", False)
        payload = _extract_broadcast_payload(message)
        if payload is None:
            return await _reply_rich(message, ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_err_title"), [i18n.get(chat_id, "admin_bc_err_desc")], icon="⚠️"))

        user_ids = list(get_stats_manager().get_all_stats().keys())
        if not user_ids:
            await state.clear()
            return await _reply_rich(message, ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_no_users"), [i18n.get(chat_id, "admin_bc_no_users_desc")], icon="📣"))

        broadcast_cache[message.from_user.id] = {"payload": payload, "user_ids": user_ids, "total": len(user_ids), "from_panel": from_panel}
        await state.clear()

        buttons_html = ui_manager.format_rich_button_row([
            {"text": i18n.get(chat_id, "admin_btn_yes"), "callback_data": "broadcast_confirm", "style": "success"},
            {"text": i18n.get(chat_id, "admin_btn_cancel"), "callback_data": "broadcast_cancel", "style": "danger"},
        ])
        await _reply_rich(message, ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_confirm"), [i18n.get(chat_id, "admin_bc_receivers", c=len(user_ids)), i18n.get(chat_id, "admin_bc_continue")], icon="📣") + buttons_html)

    async def stats_global_command(message: Message):
        if not message.from_user or not is_admin(message.from_user.id): return
        # Прямая команда - открыта не из /admin, возвращаться в панель некуда.
        rich = InputRichMessage(html=_build_global_stats_rich(message.chat.id, show_back=False))
        await message.bot.send_rich_message(
            message.chat.id, rich, reply_parameters=ReplyParameters(message_id=message.message_id)
        )

    async def callback_admin_stats_global(call: CallbackQuery):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await call.answer()
        rich = InputRichMessage(html=_build_global_stats_rich(chat_id))
        await call.message.edit_text(rich_message=rich)

    async def callback_admin_broadcast(call: CallbackQuery, state: FSMContext):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await state.set_state(BroadcastStates.waiting_for_message)
        await state.update_data(from_panel=True)
        await call.answer()
        html_content = ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_title"), [i18n.get(chat_id, "admin_bc_prompt")], icon="📣") + _build_broadcast_waiting_button_html(chat_id)
        await call.message.edit_text(rich_message=InputRichMessage(html=html_content))

    async def callback_admin_user_list(call: CallbackQuery):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await call.answer()
        await call.message.edit_text(rich_message=InputRichMessage(html=_build_user_list_text(chat_id)))

    async def callback_admin_clear_db(call: CallbackQuery):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await call.answer()
        buttons_html = ui_manager.format_rich_button_row([
            {"text": i18n.get(chat_id, "admin_btn_yes_clear"), "callback_data": "admin_clear_confirm", "style": "danger"},
            {"text": i18n.get(chat_id, "admin_btn_cancel"), "callback_data": "admin_back"},
        ])
        html_content = ui_manager.format_rich_panel(i18n.get(chat_id, "admin_clear_title"), [i18n.get(chat_id, "admin_clear_q1"), i18n.get(chat_id, "admin_clear_q2")], icon="⚠️") + buttons_html
        await call.message.edit_text(rich_message=InputRichMessage(html=html_content))

    async def callback_admin_clear_confirm(call: CallbackQuery):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        get_stats_manager().clear_all_stats()
        await call.answer(i18n.get(chat_id, "admin_clear_done"))
        html_content = ui_manager.format_rich_panel(i18n.get(chat_id, "admin_clear_done"), [i18n.get(chat_id, "admin_clear_success")], icon="✅") + _build_back_button_html(chat_id)
        await call.message.edit_text(rich_message=InputRichMessage(html=html_content))

    async def callback_broadcast_confirm(call: CallbackQuery, bot: Bot):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        data = broadcast_cache.get(call.from_user.id)
        if not data: return await call.answer(i18n.get(chat_id, "admin_bc_not_found"), show_alert=True)
        await call.answer()

        payload, user_ids, total_users = data["payload"], data["user_ids"], data["total"]
        from_panel = data.get("from_panel", False)
        await call.message.edit_text(rich_message=InputRichMessage(html=ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_started"), [i18n.get(chat_id, "admin_bc_sent", s=0, t=total_users), i18n.get(chat_id, "admin_bc_err_count", e=0)], icon="📣")))

        sent = failed = 0
        for index, uid in enumerate(user_ids, start=1):
            try:
                await _send_broadcast_payload(bot, uid, payload)
                sent += 1
            except TelegramRetryAfter as exc:
                # Telegram's own flood-control backoff, not a real failure -
                # wait it out and retry this user once before giving up.
                await asyncio.sleep(exc.retry_after)
                try:
                    await _send_broadcast_payload(bot, uid, payload)
                    sent += 1
                except Exception as retry_exc:
                    failed += 1
                    logger.warning("Рассылка: не удалось отправить %s после retry_after: %s", uid, retry_exc)
            except TelegramForbiddenError:
                failed += 1  # пользователь заблокировал бота - ожидаемо, не логируем
            except Exception as exc:
                failed += 1
                logger.warning("Рассылка: не удалось отправить %s: %s", uid, exc)
            else:
                # ~20 msg/s держит нас ниже общего лимита Bot API (30/s) и не
                # долбит один и тот же чат чаще раза в секунду.
                await asyncio.sleep(0.05)
            if index % 10 == 0 or index == total_users:
                try: await call.message.edit_text(rich_message=InputRichMessage(html=ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_progress"), [i18n.get(chat_id, "admin_bc_sent", s=sent, t=total_users), i18n.get(chat_id, "admin_bc_err_count", e=failed)], icon="📣")))
                except Exception: pass

        broadcast_cache.pop(call.from_user.id, None)
        html_content = ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_finished"), [i18n.get(chat_id, "admin_bc_success_count", s=sent, t=total_users), i18n.get(chat_id, "admin_bc_err_count", e=failed)], icon="✅")
        if from_panel:
            html_content += _build_back_button_html(chat_id)
        await call.message.edit_text(rich_message=InputRichMessage(html=html_content))

    async def callback_broadcast_cancel(call: CallbackQuery, state: FSMContext):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await state.clear()
        broadcast_cache.pop(call.from_user.id, None)
        await call.answer(i18n.get(chat_id, "admin_bc_cancelled"))
        # Отмена - тупиковое действие, не навигация: сообщение удаляется
        # вместо показа экрана "отменено" с кнопкой "Назад" в никуда.
        try:
            await call.message.delete()
        except Exception:
            html_content = ui_manager.format_rich_panel(i18n.get(chat_id, "admin_bc_cancelled").replace(".", ""), icon="✕")
            await call.message.edit_text(rich_message=InputRichMessage(html=html_content))

    async def callback_admin_back(call: CallbackQuery, state: FSMContext):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await state.clear()
        await call.answer()
        await call.message.edit_text(rich_message=InputRichMessage(html=_build_admin_panel_text(chat_id)))

    router.message.register(admin_command, Command("admin"))
    router.message.register(broadcast_command, Command("broadcast"))
    router.message.register(stats_global_command, Command("stats_global"))
    router.message.register(process_broadcast_message, BroadcastStates.waiting_for_message)
    router.callback_query.register(callback_admin_stats_global, lambda c: c.data == "admin_stats_global")
    router.callback_query.register(callback_admin_broadcast, lambda c: c.data == "admin_broadcast")
    router.callback_query.register(callback_admin_user_list, lambda c: c.data == "admin_user_list")
    router.callback_query.register(callback_admin_clear_db, lambda c: c.data == "admin_clear_db")
    router.callback_query.register(callback_admin_clear_confirm, lambda c: c.data == "admin_clear_confirm")
    router.callback_query.register(callback_broadcast_confirm, lambda c: c.data == "broadcast_confirm")
    router.callback_query.register(callback_broadcast_cancel, lambda c: c.data == "broadcast_cancel")
    router.callback_query.register(callback_admin_back, lambda c: c.data == "admin_back")
