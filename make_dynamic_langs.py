import json
import re

# 1. Добавляем названия языков прямо в словари
LOCALES_FILE = "/root/ReSave/locales.json"
with open(LOCALES_FILE, 'r', encoding='utf-8') as f:
    locales = json.load(f)

locales["ru"]["_lang_name"] = "🇷🇺 Русский"
locales["en"]["_lang_name"] = "🇬🇧 English"

with open(LOCALES_FILE, 'w', encoding='utf-8') as f:
    json.dump(locales, f, ensure_ascii=False, indent=4)

# 2. Переписываем обработчик команды /lang
ch_path = "/root/ReSave/src/handlers/command_handlers.py"
with open(ch_path, 'r', encoding='utf-8') as f:
    content = f.read()

new_func = '''    async def lang_command(m: Message):
        chat_id = m.chat.id
        buttons = []
        # Динамически собираем кнопки из locales.json
        for lang_code, strings in i18n.locales.items():
            lang_name = strings.get("_lang_name", f"🌍 {lang_code.upper()}")
            buttons.append([InlineKeyboardButton(text=lang_name, callback_data=f"setlang_{lang_code}")])
        
        kbd = InlineKeyboardMarkup(inline_keyboard=buttons)
        await safe_reply(m, i18n.get(chat_id, "menu_lang"), reply_markup=kbd)'''

# Ищем старую функцию и заменяем на новую
content = re.sub(
    r'async def lang_command\(m: Message\):.*?await safe_reply\(m, i18n\.get\(chat_id, "menu_lang"\), reply_markup=kbd\)',
    new_func,
    content,
    flags=re.DOTALL
)

with open(ch_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Меню выбора языков успешно стало динамическим!")
