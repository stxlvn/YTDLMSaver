import json
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
LANG_FILE = str(_PROJECT_ROOT / "user_langs.json")
LOCALES_FILE = str(_PROJECT_ROOT / "locales.json")

DEFAULT_LOCALES = {
    "ru": {
        "welcome": "Скачиваю видео, аудио, превью и медиа по ссылке.\n\nКак начать:\n1. Отправьте ссылку.\n2. Выберите формат.\n3. Получите файл.",
        "help": "Личные сообщения:\n1. Отправьте ссылку.\n2. Дождитесь меню выбора качества.\n\nПлатформы: YouTube, TikTok, Instagram и др.",
        "stats": "Ваша статистика",
        "lang_changed": "🇷🇺 Язык успешно изменен на Русский!",
        "choose_lang": "🌍 Выберите язык интерфейса:"
    },
    "en": {
        "welcome": "Downloading video, audio, and media via link.\n\nHow to start:\n1. Send a link.\n2. Choose format.\n3. Get your file.",
        "help": "Direct messages:\n1. Send a link.\n2. Wait for the quality menu.\n\nPlatforms: YouTube, TikTok, Instagram, etc.",
        "stats": "Your statistics",
        "lang_changed": "🇬🇧 Language successfully changed to English!",
        "choose_lang": "🌍 Choose interface language:"
    }
}

class I18nManager:
    def __init__(self):
        self.user_langs = {}
        self.locales = {}
        self.load_data()

    def load_data(self):
        if not os.path.exists(LOCALES_FILE):
            with open(LOCALES_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_LOCALES, f, ensure_ascii=False, indent=4)
        with open(LOCALES_FILE, 'r', encoding='utf-8') as f:
            self.locales = json.load(f)

        if os.path.exists(LANG_FILE):
            with open(LANG_FILE, 'r', encoding='utf-8') as f:
                self.user_langs = json.load(f)

    def save_langs(self):
        with open(LANG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.user_langs, f, ensure_ascii=False, indent=4)

    def set_lang(self, user_id, lang_code):
        self.user_langs[str(user_id)] = lang_code
        self.save_langs()

    def get_lang(self, user_id):
        return self.user_langs.get(str(user_id), "ru")

    def get(self, user_id, key, **kwargs):
        lang = self.get_lang(user_id)
        text = self.locales.get(lang, self.locales.get("ru", {})).get(key, key)
        for k, v in kwargs.items():
            text = text.replace(f"{{{k}}}", str(v))
        return text

i18n = I18nManager()
