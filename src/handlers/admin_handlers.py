from __future__ import annotations

import logging
from dataclasses import dataclass
from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

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

def _build_admin_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_stats"), callback_data="admin_stats_global"),
         InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_bc"), callback_data="admin_broadcast")],
        [InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_users"), callback_data="admin_user_list"),
         InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_clear"), callback_data="admin_clear_db")]
    ])

def _build_back_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_back"), callback_data="admin_back")]])

def _build_broadcast_waiting_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_cancel"), callback_data="broadcast_cancel")]])

def _build_admin_panel_text(chat_id: int):
    ui_manager = get_ui_manager()
    all_stats = get_stats_manager().get_all_stats()
    total_downloads = sum(item.downloads_count for item in all_stats.values())
    total_videos = sum(item.total_videos for item in all_stats.values())
    total_audios = sum(item.total_audios for item in all_stats.values())
    total_other = sum(item.total_other_downloads for item in all_stats.values())
    total_failed = sum(item.failed_downloads for item in all_stats.values())
    total_size = sum(item.total_size_mb for item in all_stats.values())

    return ui_manager.format_panel(
        i18n.get(chat_id, "admin_panel_title"),
        ui_manager.format_key_value_list([
            (i18n.get(chat_id, "admin_stat_active"), str(len(all_stats))),
            (i18n.get(chat_id, "admin_stat_total"), str(total_downloads)),
            (i18n.get(chat_id, "admin_stat_vid"), str(total_videos)),
            (i18n.get(chat_id, "admin_stat_aud"), str(total_audios)),
            (i18n.get(chat_id, "admin_stat_other"), str(total_other)),
            (i18n.get(chat_id, "admin_stat_err"), str(total_failed)),
            (i18n.get(chat_id, "admin_stat_size"), f"{total_size:.1f} MB"),
        ]), icon="🛠️", footer=i18n.get(chat_id, "admin_panel_footer")
    )

def _build_global_stats_text(chat_id: int):
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

    lines = ui_manager.format_key_value_list([
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
    lines.extend(["", i18n.get(chat_id, "admin_top_users")])

    top_users = sorted(all_stats.items(), key=lambda i: i[1].downloads_count, reverse=True)[:5]
    if not top_users: lines.append(i18n.get(chat_id, "admin_no_users"))
    else:
        for idx, (uid, stats) in enumerate(top_users, 1):
            lines.append(f"{idx}. ID {uid}: {i18n.get(chat_id, 'admin_dl_count', c=stats.downloads_count)}")

    return ui_manager.format_panel(i18n.get(chat_id, "admin_btn_stats").replace('📊 ', ''), lines, icon="📊")

def _build_user_list_text(chat_id: int):
    ui_manager = get_ui_manager()
    all_stats = get_stats_manager().get_all_stats()
    user_list = sorted(all_stats.items(), key=lambda i: i[1].downloads_count, reverse=True)
    lines = []

    if not user_list:
        return ui_manager.format_panel(i18n.get(chat_id, "admin_users_title"), [i18n.get(chat_id, "admin_db_empty")], icon="👥")

    for uid, stats in user_list[:20]:
        lines.extend([
            f"ID: {uid}",
            f"├ {i18n.get(chat_id, 'admin_ul_dl')}: {stats.downloads_count}",
            f"├ {i18n.get(chat_id, 'admin_ul_vid')}: {stats.total_videos} | {i18n.get(chat_id, 'admin_ul_aud')}: {stats.total_audios} | {i18n.get(chat_id, 'admin_ul_other')}: {stats.total_other_downloads}",
            f"└ {i18n.get(chat_id, 'admin_ul_size')}: {stats.total_size_mb:.1f} MB", ""
        ])
    if len(user_list) > 20: lines.append(i18n.get(chat_id, "admin_and_more", c=len(user_list) - 20))
    return ui_manager.format_panel(i18n.get(chat_id, "admin_users_title"), lines, icon="👥")

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

    async def admin_command(message: Message, state: FSMContext):
        if not message.from_user or not is_admin(message.from_user.id): return
        chat_id = message.chat.id
        await state.clear()
        await message.reply(_build_admin_panel_text(chat_id), reply_markup=_build_admin_keyboard(chat_id))

    async def broadcast_command(message: Message, state: FSMContext):
        if not message.from_user or not is_admin(message.from_user.id): return
        chat_id = message.chat.id
        await state.set_state(BroadcastStates.waiting_for_message)
        await message.reply(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_title"), [i18n.get(chat_id, "admin_bc_prompt")], icon="📣"), reply_markup=_build_broadcast_waiting_keyboard(chat_id))

    async def process_broadcast_message(message: Message, state: FSMContext):
        if not message.from_user or not is_admin(message.from_user.id): return
        chat_id = message.chat.id
        payload = _extract_broadcast_payload(message)
        if payload is None:
            return await message.reply(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_err_title"), [i18n.get(chat_id, "admin_bc_err_desc")], icon="⚠️"))

        user_ids = list(get_stats_manager().get_all_stats().keys())
        if not user_ids:
            await state.clear()
            return await message.reply(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_no_users"), [i18n.get(chat_id, "admin_bc_no_users_desc")], icon="📣"))

        broadcast_cache[message.from_user.id] = {"payload": payload, "user_ids": user_ids, "total": len(user_ids)}
        await state.clear()
        
        kbd = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_yes"), callback_data="broadcast_confirm"),
            InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_cancel"), callback_data="broadcast_cancel")
        ]])
        await message.reply(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_confirm"), [i18n.get(chat_id, "admin_bc_receivers", c=len(user_ids)), "", i18n.get(chat_id, "admin_bc_continue")], icon="📣"), reply_markup=kbd)

    async def stats_global_command(message: Message):
        if not message.from_user or not is_admin(message.from_user.id): return
        await message.reply(_build_global_stats_text(message.chat.id))

    async def callback_admin_stats_global(call: CallbackQuery):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await call.answer()
        await call.message.edit_text(_build_global_stats_text(chat_id), reply_markup=_build_back_keyboard(chat_id))

    async def callback_admin_broadcast(call: CallbackQuery, state: FSMContext):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await state.set_state(BroadcastStates.waiting_for_message)
        await call.answer()
        await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_title"), [i18n.get(chat_id, "admin_bc_prompt")], icon="📣"), reply_markup=_build_broadcast_waiting_keyboard(chat_id))

    async def callback_admin_user_list(call: CallbackQuery):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await call.answer()
        await call.message.edit_text(_build_user_list_text(chat_id), reply_markup=_build_back_keyboard(chat_id))

    async def callback_admin_clear_db(call: CallbackQuery):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await call.answer()
        kbd = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_yes_clear"), callback_data="admin_clear_confirm"),
            InlineKeyboardButton(text=i18n.get(chat_id, "admin_btn_cancel"), callback_data="admin_back")
        ]])
        await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "admin_clear_title"), [i18n.get(chat_id, "admin_clear_q1"), i18n.get(chat_id, "admin_clear_q2")], icon="⚠️"), reply_markup=kbd)

    async def callback_admin_clear_confirm(call: CallbackQuery):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        get_stats_manager().clear_all_stats()
        await call.answer(i18n.get(chat_id, "admin_clear_done"))
        await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "admin_clear_done"), [i18n.get(chat_id, "admin_clear_success")], icon="✅"), reply_markup=_build_back_keyboard(chat_id))

    async def callback_broadcast_confirm(call: CallbackQuery, bot: Bot):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        data = broadcast_cache.get(call.from_user.id)
        if not data: return await call.answer(i18n.get(chat_id, "admin_bc_not_found"), show_alert=True)
        await call.answer()

        payload, user_ids, total_users = data["payload"], data["user_ids"], data["total"]
        await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_started"), [i18n.get(chat_id, "admin_bc_sent", s=0, t=total_users), i18n.get(chat_id, "admin_bc_err_count", e=0)], icon="📣"))

        sent = failed = 0
        for index, uid in enumerate(user_ids, start=1):
            try:
                await _send_broadcast_payload(bot, uid, payload)
                sent += 1
            except Exception as exc:
                failed += 1
            if index % 10 == 0 or index == total_users:
                try: await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_progress"), [i18n.get(chat_id, "admin_bc_sent", s=sent, t=total_users), i18n.get(chat_id, "admin_bc_err_count", e=failed)], icon="📣"))
                except Exception: pass

        broadcast_cache.pop(call.from_user.id, None)
        await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_finished"), [i18n.get(chat_id, "admin_bc_success_count", s=sent, t=total_users), i18n.get(chat_id, "admin_bc_err_count", e=failed)], icon="✅"), reply_markup=_build_back_keyboard(chat_id))

    async def callback_broadcast_cancel(call: CallbackQuery, state: FSMContext):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await state.clear()
        broadcast_cache.pop(call.from_user.id, None)
        await call.answer(i18n.get(chat_id, "admin_bc_cancelled"))
        await call.message.edit_text(ui_manager.format_panel(i18n.get(chat_id, "admin_bc_cancelled").replace(".", ""), icon="✕"), reply_markup=_build_back_keyboard(chat_id))

    async def callback_admin_back(call: CallbackQuery, state: FSMContext):
        if not call.from_user or not is_admin(call.from_user.id) or not call.message: return
        chat_id = call.message.chat.id
        await state.clear()
        await call.answer()
        await call.message.edit_text(_build_admin_panel_text(chat_id), reply_markup=_build_admin_keyboard(chat_id))

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
