from __future__ import annotations

import html as _html
from enum import Enum


class UITheme(Enum):
    MODERN = "modern"
    CLASSIC = "classic"
    MINIMAL = "minimal"


class UIManager:
    def __init__(self, theme=UITheme.MODERN):
        self.theme = theme

    def format_rich_panel(
        self,
        title: str,
        lines: list[str] | None = None,
        *,
        icon: str | None = None,
        footer: str | None = None,
    ) -> str:
        # HTML для Rich Messages (Bot API 10.1+, sendRichMessage /
        # editMessageText(rich_message=...)) - заголовок становится настоящим
        # <h3> блоком, а не жирным текстом поверх обычного sendMessage.
        # Не экранирует - вызывающий код должен сам экранировать динамические
        # данные (html.escape), если они есть.
        header = f"{icon} {title}" if icon else title
        parts = [f"<h3>{header}</h3>"]
        for line in lines or []:
            if line == "":
                continue
            parts.append(f"<p>{line}</p>")
        if footer:
            parts.append(f"<footer>{footer}</footer>")
        return "".join(parts)

    def format_rich_table(
        self,
        items: list[tuple[str, str]],
        *,
        header: tuple[str, str] | None = None,
    ) -> str:
        rows = []
        if header:
            rows.append(f"<tr><th>{header[0]}</th><th>{header[1]}</th></tr>")
        for label, value in items:
            rows.append(f"<tr><td>{label}</td><td>{value}</td></tr>")
        return f"<table>{''.join(rows)}</table>"

    def format_rich_button(
        self,
        text: str,
        *,
        callback_data: str | None = None,
        url: str | None = None,
        style: str | None = None,
    ) -> str:
        # <tg-button> (Bot API 10.3+, см. core.telegram.org/bots/api#inputrichmessage,
        # раздел "Rich HTML style"): кнопки живут прямо в теле сообщения, а не
        # отдельной клавиатурой через reply_markup. callback_data уходит в
        # атрибут data= (не callback_data=) - так его парсит сервер.
        if callback_data is not None:
            attrs = f'type="callback_data" data="{_html.escape(callback_data, quote=True)}"'
        elif url is not None:
            attrs = f'type="url" url="{_html.escape(url, quote=True)}"'
        else:
            raise ValueError("format_rich_button: нужен callback_data или url")
        if style:
            attrs += f' style="{style}"'
        return f"<tg-button {attrs}>{_html.escape(text)}</tg-button>"

    def format_rich_button_row(self, buttons: list[dict], *, align: str | None = None) -> str:
        """buttons: [{'text':..., 'callback_data' или 'url':..., 'style':...}, ...] - одна строка кнопок (до 8)."""
        attrs = f' align="{align}"' if align else ""
        inner = "".join(self.format_rich_button(**b) for b in buttons)
        return f"<tg-button-row{attrs}>{inner}</tg-button-row>"

    def create_progress_bar(
        self,
        progress: float,
        length: int = 12,
        filled_char: str = "█",
        empty_char: str = "░",
    ) -> str:
        progress = max(0.0, min(progress, 1.0))
        filled = int(progress * length)
        percentage = int(progress * 100)
        bar = f"{filled_char * filled}{empty_char * (length - filled)}"
        return f"{bar} {percentage}%"


_ui_manager = None


def get_ui_manager(theme=UITheme.MODERN) -> UIManager:
    global _ui_manager
    if _ui_manager is None:
        _ui_manager = UIManager(theme)
    return _ui_manager
