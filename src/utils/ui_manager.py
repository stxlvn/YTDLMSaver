from __future__ import annotations

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
