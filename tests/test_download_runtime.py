import threading
from types import SimpleNamespace

import config

from src.core import download_handler
from src.core.download_handler import (
    DownloadVariant,
    _base_ydl_params,
    _download_with_timeout,
)


def _task():
    return SimpleNamespace(
        cancel_event=threading.Event(),
        progress=0.0,
        speed_bytes_per_sec=0.0,
        stage="download",
        stage_started_at=None,
    )


def test_download_runtime_is_bounded_for_shared_hosting():
    variant = DownloadVariant(
        label="1080p",
        format="bv*[height=1080]+ba/b[height=1080]",
        postprocessors=(),
        output_template="/tmp/media.%(ext)s",
    )

    params = _base_ydl_params(variant)

    assert params["noprogress"] is True
    assert params["buffersize"] == 64 * 1024
    assert params["noresizebuffer"] is True
    if config.DOWNLOAD_RATE_LIMIT_BYTES > 0:
        assert params["ratelimit"] == config.DOWNLOAD_RATE_LIMIT_BYTES


def test_download_stall_timeout_is_shorter_than_total_timeout():
    assert 30 <= config.DOWNLOAD_STALL_TIMEOUT_SECONDS
    assert config.DOWNLOAD_STALL_TIMEOUT_SECONDS < config.DOWNLOAD_TIMEOUT_SECONDS


def test_download_runs_inline_and_reports_progress(monkeypatch):
    observed = {}

    class FakeYoutubeDL:
        def __init__(self, params):
            observed["params"] = params

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, urls):
            observed["urls"] = urls
            hook = observed["params"]["progress_hooks"][0]
            hook({"status": "downloading", "filename": "video.mp4", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "finished", "filename": "video.mp4", "total_bytes": 100})

    monkeypatch.setattr(download_handler.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    task = _task()

    _download_with_timeout("https://example.com/video", {}, 60, task)

    assert observed["urls"] == ["https://example.com/video"]
    assert task.progress == 1.0


def test_combined_progress_across_video_and_audio_streams_is_monotonic(monkeypatch):
    # bestvideo+bestaudio скачивается как два отдельных файла в рамках одного
    # ydl.download(): видео-поток 0->100%, затем аудио-поток заново с 0->100%.
    # Прогресс должен суммироваться по обоим файлам и никогда не откатываться назад.
    class FakeYoutubeDL:
        def __init__(self, params):
            self.params = params

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            hook = self.params["progress_hooks"][0]
            hook({"status": "downloading", "filename": "video.mp4", "downloaded_bytes": 100, "total_bytes": 100})
            hook({"status": "finished", "filename": "video.mp4", "total_bytes": 100})
            observed_ratios.append(task.progress)
            hook({"status": "downloading", "filename": "audio.m4a", "downloaded_bytes": 10, "total_bytes": 100})
            observed_ratios.append(task.progress)

    observed_ratios = []
    monkeypatch.setattr(download_handler.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    task = _task()

    _download_with_timeout("https://example.com/video", {}, 60, task)

    assert all(b >= a for a, b in zip(observed_ratios, observed_ratios[1:]))
    assert task.progress == 1.0


def test_stall_timeout_not_triggered_when_total_bytes_is_unknown(monkeypatch):
    # Некоторые live/fragment-форматы не сообщают total_bytes вообще. Activity
    # должна отслеживаться по изменению downloaded_bytes независимо от того,
    # известен ли total - иначе такая загрузка ловила бы ложный stall-таймаут,
    # даже активно скачиваясь.
    class FakeYoutubeDL:
        def __init__(self, params):
            self.params = params

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            hook = self.params["progress_hooks"][0]
            for downloaded in (10, 20, 30):
                clock["now"] += config.DOWNLOAD_STALL_TIMEOUT_SECONDS - 1
                hook({"status": "downloading", "filename": "live.ts", "downloaded_bytes": downloaded})
            clock["now"] += config.DOWNLOAD_STALL_TIMEOUT_SECONDS - 1
            hook({"status": "finished", "filename": "live.ts"})

    clock = {"now": 1000.0}
    monkeypatch.setattr(download_handler.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(download_handler.time, "monotonic", lambda: clock["now"])
    task = _task()

    _download_with_timeout("https://example.com/live", {}, 10_000, task)


def test_cancelled_inline_download_stops_from_progress_hook(monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, params):
            self.params = params

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            self.params["progress_hooks"][0]({"status": "downloading"})

    monkeypatch.setattr(download_handler.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    task = _task()
    task.cancel_event.set()

    try:
        _download_with_timeout("https://example.com/video", {}, 60, task)
    except RuntimeError as exc:
        assert "отменена" in str(exc)
    else:
        raise AssertionError("cancelled download must stop")
