import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings
from app.models import VideoInfo
from app.services.errors import PipelineError

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


def validate_youtube_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"http", "https"}
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Enter a valid youtube.com or youtu.be URL")
    return value


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise PipelineError("A required media tool is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError("YouTube processing timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError(
            "Could not access this video. Make sure it is public and available."
        ) from exc


def fetch_metadata(url: str, settings: Settings) -> VideoInfo:
    validate_youtube_url(url)
    result = _run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--no-playlist",
            "--no-warnings",
            url,
        ],
        min(settings.process_timeout_seconds, 120),
    )
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PipelineError("Could not read video metadata") from exc

    if duration <= 0:
        raise PipelineError("This video has no usable duration")
    if duration > settings.max_video_seconds:
        max_hours = settings.max_video_seconds // 3600
        raise PipelineError(f"Videos longer than {max_hours} hours are not supported")

    return VideoInfo(
        title=str(payload.get("title") or "Untitled video")[:200],
        duration=duration,
        source_url=url,
        thumbnail_url=payload.get("thumbnail"),
    )


def download_video(url: str, work_dir: Path, settings: Settings) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(work_dir / "source.%(ext)s")
    _run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--no-warnings",
            "--restrict-filenames",
            "--merge-output-format",
            "mp4",
            "-f",
            "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "-o",
            output_template,
            url,
        ],
        settings.process_timeout_seconds,
    )
    candidates = [
        path
        for path in work_dir.glob("source.*")
        if path.is_file() and path.suffix not in {".part", ".ytdl"}
    ]
    if not candidates:
        raise PipelineError("The downloaded video file could not be found")
    return max(candidates, key=lambda path: path.stat().st_size)
