from pathlib import Path
from types import SimpleNamespace

from aiogram.types import FSInputFile

from src.utils.aiogram_bot_adapter import AiogramSyncBotAdapter, ProgressTrackingFSInputFile


def _adapter(*, is_local: bool) -> AiogramSyncBotAdapter:
    bot = SimpleNamespace(
        session=SimpleNamespace(api=SimpleNamespace(is_local=is_local)),
    )
    return AiogramSyncBotAdapter(bot=bot, loop=None)


def test_local_api_always_streams_file(tmp_path):
    # Наш telegram-bot-api - отдельный Docker-контейнер с расшаренным только
    # /tmp; file:// URI на путь вне /tmp (например /root/ReSave/temp_downloads)
    # ловит "invalid file HTTP URL specified: Unsupported URL protocol", потому
    # что внутри контейнера такого пути просто не существует. Поэтому и на
    # локальном Bot API файл всегда стримится через HTTP, как на облачном.
    media_path = tmp_path / "video with spaces.mp4"
    media_path.write_bytes(b"media")

    prepared = _adapter(is_local=True)._prepare_file(media_path)

    assert isinstance(prepared, FSInputFile)
    assert Path(prepared.path) == media_path


def test_cloud_api_uses_streaming_upload(tmp_path):
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"media")

    prepared = _adapter(is_local=False)._prepare_file(media_path)

    assert isinstance(prepared, FSInputFile)
    assert Path(prepared.path) == media_path


def test_progress_tracking_used_when_on_progress_given(tmp_path):
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"media")
    seen = []

    prepared = _adapter(is_local=True)._prepare_file(
        media_path,
        on_progress=lambda sent, total: seen.append((sent, total)),
    )

    assert isinstance(prepared, ProgressTrackingFSInputFile)
