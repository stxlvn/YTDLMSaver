from __future__ import annotations

from enum import Enum


class UITheme(Enum):
    MODERN = "modern"
    CLASSIC = "classic"
    MINIMAL = "minimal"


class UIManager:
    def __init__(self, theme=UITheme.MODERN):
        self.theme = theme

    def format_panel(
        self,
        title: str,
        lines: list[str] | None = None,
        *,
        icon: str | None = None,
        footer: str | None = None,
    ) -> str:
        # Заголовок жирным (HTML) вместо строки-разделителя "━━━...":
        # разделитель ничего не сообщает, а жирный текст даёт ту же иерархию
        # компактнее. title и lines должны быть уже экранированы вызывающим
        # кодом (html.escape), если содержат динамические данные - format_panel
        # сам не экранирует, чтобы не портить осознанно вставленные теги.
        header_icon = f"{icon} " if icon else ""
        message_lines = [f"{header_icon}<b>{title}</b>"]

        if lines:
            message_lines.extend(lines)

        if footer:
            message_lines.extend(["", footer])

        return "\n".join(message_lines).strip()

    def format_key_value_list(self, items: list[tuple[str, str]]) -> list[str]:
        lines: list[str] = []
        for label, value in items:
            lines.append(f"• {label}: {value}")
        return lines

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
