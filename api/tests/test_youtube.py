import json
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.services.errors import PipelineError
from app.services.youtube import (
    classify_ytdlp_error,
    fetch_metadata,
    validate_youtube_url,
    ytdlp_command,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_accepts_supported_youtube_urls(url: str) -> None:
    assert validate_youtube_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com.example.org/watch?v=abc",
        "https://example.com/video",
        "file:///tmp/video.mp4",
        "https://user:pass@youtube.com/watch?v=abc",
    ],
)
def test_rejects_untrusted_urls(url: str) -> None:
    with pytest.raises(ValueError, match="valid"):
        validate_youtube_url(url)


def test_ytdlp_command_enables_cloud_friendly_clients(monkeypatch) -> None:
    monkeypatch.setattr("app.services.youtube.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)
    settings = Settings(ytdlp_proxy="socks5://proxy.example:1080")
    command = ytdlp_command(settings, ["https://youtu.be/test"], "android_vr,web_embedded,tv,web_safari")

    assert "--js-runtimes" in command
    assert "node" in command
    assert "--proxy" in command
    assert "youtube:player_client=android_vr,web_embedded,tv,web_safari" in command


def test_classify_bot_check_as_cloud_block() -> None:
    message = classify_ytdlp_error("ERROR: Sign in to confirm you’re not a bot.")
    assert "cloud server" in message


def test_fetch_metadata_retries_player_clients(monkeypatch) -> None:
    settings = Settings()
    attempts: list[str] = []

    def fake_run(command: list[str], timeout: int):
        del timeout
        extractor = next(
            (item.split("=", 1)[1] for item in command if item.startswith("youtube:player_client=")),
            "default",
        )
        attempts.append(extractor)
        if extractor != "default":
            raise PipelineError("YouTube blocked this download from our cloud server. Wait a minute and try again.")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"title": "Test", "duration": 32, "thumbnail": None}),
            stderr="",
        )

    monkeypatch.setattr("app.services.youtube._run", fake_run)
    monkeypatch.setattr("app.services.youtube.time.sleep", lambda _: None)

    info = fetch_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ", settings)

    assert info.title == "Test"
    assert info.duration == 32
    assert attempts == [
        "android_vr,web_embedded,tv,web_safari",
        "mweb,web",
        "default",
    ]


def test_download_retries_without_format_filter(monkeypatch, tmp_path: Path) -> None:
    from app.services.youtube import download_video

    calls: list[list[str]] = []

    def fake_run_ytdlp(settings: Settings, extra: list[str], timeout: int):
        del settings, timeout
        calls.append(extra)
        if "-f" in extra:
            raise PipelineError("Could not download a compatible video format.")
        (tmp_path / "source.mp4").write_bytes(b"video")

    monkeypatch.setattr("app.services.youtube._run_ytdlp", fake_run_ytdlp)

    path = download_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ", tmp_path, Settings())

    assert path.name == "source.mp4"
    assert len(calls) == 2
    assert "-f" in calls[0]
    assert "-f" not in calls[1]
