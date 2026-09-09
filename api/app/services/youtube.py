import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings
from app.models import VideoInfo
from app.services.errors import PipelineError

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

# Prefer clients that still work from cloud IPs without a PO token, then
# fall back to web clients that need a JS runtime for signature solving.
PLAYER_CLIENTS = (
    "android_vr,web_embedded,tv,web_safari",
    "mweb,web",
    "default",
)


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


def _js_runtime_args() -> list[str]:
    args: list[str] = []
    if shutil.which("deno"):
        args.extend(["--js-runtimes", "deno"])
    if shutil.which("node"):
        args.extend(["--js-runtimes", "node"])
    return args


def _network_args(settings: Settings) -> list[str]:
    args: list[str] = []
    proxy = settings.ytdlp_proxy.strip()
    if proxy:
        args.extend(["--proxy", proxy])
    cookies = settings.youtube_cookies_file.strip()
    if cookies:
        cookie_path = Path(cookies)
        if cookie_path.is_file():
            args.extend(["--cookies", str(cookie_path)])
    return args


def ytdlp_command(settings: Settings, extra: list[str], player_client: str) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        *_js_runtime_args(),
        *_network_args(settings),
    ]
    if player_client != "default":
        command.extend(["--extractor-args", f"youtube:player_client={player_client}"])
    command.extend(extra)
    return command


def classify_ytdlp_error(stderr: str) -> str:
    text = (stderr or "").lower()
    if any(
        marker in text
        for marker in (
            "sign in to confirm",
            "not a bot",
            "confirm you’re not a bot",
            "confirm you're not a bot",
        )
    ):
        return (
            "YouTube blocked this download from our cloud server. "
            "Wait a minute and try again."
        )
    if "requested format is not available" in text:
        return "Could not download a compatible video format."
    return "Could not access this video. Make sure it is public and available."


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
        stderr = exc.stderr or ""
        logger.warning("yt-dlp failed: %s", stderr.strip()[-2000:])
        raise PipelineError(classify_ytdlp_error(stderr)) from exc


def _run_ytdlp(
    settings: Settings,
    extra: list[str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    last_error: PipelineError | None = None
    for index, player_client in enumerate(PLAYER_CLIENTS):
        try:
            return _run(ytdlp_command(settings, extra, player_client), timeout)
        except PipelineError as exc:
            last_error = exc
            logger.warning(
                "yt-dlp player client %s failed: %s",
                player_client,
                exc,
            )
            if index + 1 < len(PLAYER_CLIENTS):
                time.sleep(min(8, 2 ** index))
    assert last_error is not None
    raise last_error


def fetch_metadata(url: str, settings: Settings) -> VideoInfo:
    validate_youtube_url(url)
    result = _run_ytdlp(
        settings,
        ["--dump-single-json", "--no-warnings", url],
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
    extra = [
        "--restrict-filenames",
        "--merge-output-format",
        "mp4",
        "-S",
        "res:1080,ext:mp4:m4a",
        "-f",
        "bv*+ba/b",
        "-o",
        output_template,
        url,
    ]
    try:
        _run_ytdlp(settings, extra, settings.process_timeout_seconds)
    except PipelineError as exc:
        if "compatible video format" not in str(exc):
            raise
        logger.warning("Retrying YouTube download without a format filter")
        _run_ytdlp(
            settings,
            [
                "--restrict-filenames",
                "--merge-output-format",
                "mp4",
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
