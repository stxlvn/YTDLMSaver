import logging
import time
import re
from pathlib import Path
from ..utils.i18n import i18n
from .user_stats import get_stats_manager

logger = logging.getLogger(__name__)

def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', str(text))

def format_file_size(size_bytes):
    if size_bytes is None: return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"

def record_download_success(chat_id, action=None, file_size_mb=None):
    try:
        get_stats_manager().record_download(chat_id, action=action, file_size_mb=file_size_mb)
    except Exception as exc:
        logger.error("Ошибка при записи статистики загрузки: %s", exc)

def record_failed_download(chat_id):
    try:
        get_stats_manager().record_failed_download(chat_id)
    except Exception as exc:
        logger.error("Ошибка при записи неуспешной загрузки: %s", exc)
def describe_work_dir(task): return f"/root/ReSave/temp/{task.chat_id}_{task.message_id}"
def ensure_task_work_dir(task, temp_dir):
    work_dir = Path(temp_dir) / f"{task.chat_id}_{task.message_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir
def find_completed_files(work_dir): return [p for p in work_dir.glob('*') if p.is_file() and not p.name.startswith('.')]

class ProgressHook:
    def __init__(self, task, bot):
        self.task = task
        self.bot = bot
        self.last_update = 0
        self.last_text = ""

    def __call__(self, d):
        if d['status'] == 'downloading':
            now = time.time()
            if now - self.last_update < 4:
                return
            
            downloaded = strip_ansi(d.get('_percent_str', '0%'))
            speed = strip_ansi(d.get('_speed_str', 'N/A'))
            eta = strip_ansi(d.get('_eta_str', 'N/A'))
            
            # Используем i18n для получения текста
            new_text = (
                f"{i18n.get(self.task.chat_id, 'progress_downloading', percent=downloaded)}\n"
                f"{i18n.get(self.task.chat_id, 'progress_speed', speed=speed)}\n"
                f"{i18n.get(self.task.chat_id, 'progress_eta', eta=eta)}"
            )
            
            if new_text == self.last_text:
                return
            
            try:
                self.bot.edit_message_text(
                    chat_id=self.task.chat_id,
                    message_id=self.task.message_id,
                    text=new_text,
                    parse_mode="HTML"
                )
                self.last_update = now
                self.last_text = new_text
            except Exception:
                pass
