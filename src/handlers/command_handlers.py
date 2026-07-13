import logging
import time
from datetime import datetime
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from ..core.user_stats import get_stats_manager
from ..utils.ui_manager import get_ui_manager
from ..utils.i18n import i18n

logger = logging.getLogger(__name__)

def register_command_handlers(router: Router):
    ui_manager = get_ui_manager()

    async def safe_reply(m: Message, text: str, **kwargs):
        try:
            return await m.reply(text, **kwargs)
        except Exception:
            return None

    async def send_welcome(m: Message):
        chat_id = m.chat.id
        text_lines = i18n.get(chat_id, "menu_welcome").split("\n")
        footer_text = i18n.get(chat_id, "menu_footer")
        await safe_reply(m, ui_manager.format_panel("ReSave", text_lines, icon="⚡", footer=footer_text))

    async def help_command(m: Message):
        chat_id = m.chat.id
        text_lines = i18n.get(chat_id, "menu_help").split("\n")
        faq_title = i18n.get(chat_id, "menu_faq")
        await safe_reply(m, ui_manager.format_panel(faq_title, text_lines, icon="📖"))

    async def lang_command(m: Message):
        chat_id = m.chat.id
        buttons = []
        for lang_code, strings in i18n.locales.items():
            lang_name = strings.get("_lang_name", f"🌍 {lang_code.upper()}")
            buttons.append([InlineKeyboardButton(text=lang_name, callback_data=f"setlang_{lang_code}")])
        kbd = InlineKeyboardMarkup(inline_keyboard=buttons)
        await safe_reply(m, i18n.get(chat_id, "menu_lang"), reply_markup=kbd)

    async def lang_callback(c: CallbackQuery):
        uid = c.from_user.id
        chat_id = c.message.chat.id
        lang = c.data.split("_")[1]
        i18n.set_lang(uid, lang)
        if uid != chat_id:
            i18n.set_lang(chat_id, lang)
        await c.message.edit_text(i18n.get(chat_id, "lang_changed"))
        await c.answer()

    async def status_command(m: Message):
        from .download_handlers import get_download_manager
        manager = get_download_manager()
        chat_id = m.chat.id
        if not manager:
            return await safe_reply(m, i18n.get(chat_id, "status_manager_starting"))
        with manager.lock:
            user_tasks = {tid: t for tid, t in manager.tasks.items() if t.chat_id == chat_id and t.status in {"downloading", "pending"}}
        if not user_tasks:
            return await safe_reply(m, ui_manager.format_panel(i18n.get(chat_id, "status_no_downloads"), [i18n.get(chat_id, "status_no_downloads_desc")], icon="✅"))
        lines = []
        for t in user_tasks.values():
            lines.append(f"🎬 {t.info.get('title', 'Video')}")
            if t.status == "downloading":
                lines.append(f"⬇️ {ui_manager.create_progress_bar(t.progress)}")
                if t.started_at and t.progress > 0.05:
                    elapsed = time.time() - t.started_at
                    remaining = (elapsed / t.progress) - elapsed
                    lines.append(f"⏱️ {i18n.get(chat_id, 'status_time_left', time=manager._format_time(remaining, chat_id)) if remaining > 0 else i18n.get(chat_id, 'status_finishing')}")
                else:
                    lines.append(f"⏱️ {i18n.get(chat_id, 'status_calc')}")
            else:
                lines.append(f"⏳ {i18n.get(chat_id, 'status_queue')}")
            lines.append("")
        kbd = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=i18n.get(chat_id, "btn_cancel_all"), callback_data="cancel_all_downloads")]])
        await safe_reply(m, ui_manager.format_panel(i18n.get(chat_id, "status_your_dl"), lines, icon="📦"), reply_markup=kbd)

    async def cancel_download(m: Message):
        from .download_handlers import get_download_manager
        manager = get_download_manager()
        chat_id = m.chat.id
        if not manager:
            return await safe_reply(m, i18n.get(chat_id, "status_manager_starting"))
        with manager.lock:
            user_tasks = {tid: t for tid, t in manager.tasks.items() if t.chat_id == chat_id and t.status in {"downloading", "pending"}}
        if not user_tasks:
            return await safe_reply(m, ui_manager.format_panel(i18n.get(chat_id, "status_nothing_to_cancel"), [i18n.get(chat_id, "status_no_active")], icon="⏳"))
        cc = sum(1 for tid in user_tasks if manager.cancel_task(tid))
        await safe_reply(m, ui_manager.format_panel(i18n.get(chat_id, "status_cancelled"), [i18n.get(chat_id, "status_cancelled_count", count=cc), i18n.get(chat_id, "status_can_start_new")], icon="✅"))

    async def stats_command(m: Message):
        chat_id = m.chat.id
        stats = get_stats_manager().get_user_stats(chat_id)
        lines = []
        if stats.downloads_count == 0:
            lines.append(i18n.get(chat_id, "stats_no_dl"))
        else:
            lines.extend(ui_manager.format_key_value_list([
                (i18n.get(chat_id, "stats_dl_count"), str(stats.downloads_count)),
                (i18n.get(chat_id, "stats_videos"), str(stats.total_videos)),
                (i18n.get(chat_id, "stats_size"), f"{stats.total_size_mb:.1f} MB")
            ]))
        await safe_reply(m, ui_manager.format_panel(i18n.get(chat_id, "menu_stats"), lines, icon="📊"))

    router.message.register(send_welcome, CommandStart())
    router.message.register(help_command, Command("help"))
    router.message.register(lang_command, Command("lang"))
    router.message.register(status_command, Command("status"))
    router.message.register(cancel_download, Command("cancel"))
    router.message.register(stats_command, Command("stats"))
    router.callback_query.register(lang_callback, F.data.startswith("setlang_"))
