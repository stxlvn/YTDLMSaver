import logging
from typing import Optional

import config

logger = logging.getLogger(__name__)


def notify_admins(bot, text: Optional[str]) -> None:
    if bot is None or not text:
        return

    html_content = "".join(f"<p>{line}</p>" for line in text.split("\n") if line)
    for admin_id in config.ADMIN_IDS:
        try:
            bot.send_rich_message(admin_id, html_content)
        except Exception as exc:
            logger.error(f"Failed to notify admin {admin_id}: {exc}")
