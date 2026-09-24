from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from src.core import download_handler


def _task(**overrides):
    defaults = dict(task_id="t", url="https://www.tiktok.com/@x/video/1", action="best", info={})
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_tiktok_fallback_skipped_for_other_platforms(tmp_path):
    task = _task(url="https://www.youtube.com/watch?v=x")
    exc = RuntimeError("boom")
    with pytest.raises(RuntimeError) as excinfo:
        download_handler._tiktok_fallback_or_raise(task, tmp_path, exc)
    assert excinfo.value is exc


@pytest.mark.parametrize("action", ["audio", "gif", "subtitles", "thumbnail"])
def test_tiktok_fallback_skipped_for_non_video_actions(tmp_path, action):
    task = _task(action=action)
    exc = RuntimeError("boom")
    with pytest.raises(RuntimeError) as excinfo:
        download_handler._tiktok_fallback_or_raise(task, tmp_path, exc)
    assert excinfo.value is exc


def test_tiktok_fallback_downloads_and_fills_info(tmp_path):
    task = _task(info={"title": "", "duration": None})
    fake_path = tmp_path / "tiktok_video.mp4"
    fake_path.write_bytes(b"data")
    meta = {"title": "Real title", "duration": 12, "uploader": "someone"}

    with mock.patch.object(download_handler, "download_tiktok_video", return_value=(fake_path, meta)):
        result = download_handler._tiktok_fallback_or_raise(task, tmp_path, RuntimeError("yt-dlp failed"))

    assert result == fake_path
    assert task.info["title"] == "Real title"
    assert task.info["duration"] == 12
    assert task.info["uploader"] == "someone"


def test_tiktok_fallback_reraises_original_error_if_it_also_fails(tmp_path):
    task = _task()
    original_exc = RuntimeError("yt-dlp failed")

    with mock.patch.object(download_handler, "download_tiktok_video", side_effect=ValueError("tikwm also failed")):
        with pytest.raises(RuntimeError) as excinfo:
            download_handler._tiktok_fallback_or_raise(task, tmp_path, original_exc)

    assert excinfo.value is original_exc
