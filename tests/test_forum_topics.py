import asyncio
import threading
from types import SimpleNamespace

from src.core.download_manager import DownloadManager
from src.core.models import DownloadTask
from src.handlers.download_handlers import _topic_id
from src.utils.aiogram_bot_adapter import AiogramSyncBotAdapter


def test_topic_id_only_for_real_forum_topics():
    assert _topic_id(SimpleNamespace(is_topic_message=True, message_thread_id=555)) == 555
    # General topic / plain group
    assert _topic_id(SimpleNamespace(is_topic_message=None, message_thread_id=None)) is None
    # reply-thread in a non-forum group carries message_thread_id but is not a topic
    assert _topic_id(SimpleNamespace(is_topic_message=None, message_thread_id=123)) is None


def test_task_thread_kwargs():
    assert DownloadTask(message_thread_id=42).thread_kwargs == {"message_thread_id": 42}
    assert DownloadTask().thread_kwargs == {}


def test_add_task_propagates_thread_id():
    manager = DownloadManager()
    task_id = manager.add_task(
        url="u", chat_id=1, message_id=2, info={}, action="best", message_thread_id=99
    )
    assert manager.tasks[task_id].message_thread_id == 99


def test_adapter_forwards_message_thread_id():
    class FakeBot:
        def __init__(self):
            self.calls = []

        async def send_video(self, **kwargs):
            self.calls.append(kwargs)

    fake = FakeBot()
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        adapter = AiogramSyncBotAdapter(bot=fake, loop=loop)
        adapter.send_video(1, b"x", reply_to_message_id=5, message_thread_id=42)
    finally:
        loop.call_soon_threadsafe(loop.stop)

    assert fake.calls[0]["message_thread_id"] == 42
    assert fake.calls[0]["reply_parameters"].message_id == 5
