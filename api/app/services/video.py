import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.models import (
    AspectRatio,
    CaptionStyle,
    ClipEditSettings,
    ClipResult,
    Moment,
    TranscriptWord,
    ZoomPreset,
)
from app.services.errors import PipelineError


@dataclass(frozen=True)
class CaptionCue:
    start: float
    end: float
    text: str
    words: tuple[TranscriptWord, ...]


def _run(command: list[str], timeout: int) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise PipelineError("ffmpeg is not installed or is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError("Video processing timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError("ffmpeg could not process this video's media tracks") from exc


def extract_audio_chunks(
    video_path: Path,
    work_dir: Path,
    settings: Settings,
) -> list[Path]:
    audio_dir = work_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(audio_dir / "chunk-%03d.mp3")
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            "-f",
            "segment",
            "-segment_time",
            str(settings.audio_chunk_seconds),
            "-reset_timestamps",
            "1",
            output_pattern,
        ],
        settings.process_timeout_seconds,
    )
    chunks = sorted(audio_dir.glob("chunk-*.mp3"))
    if not chunks:
        raise PipelineError("No audio track was found in this video")
    return chunks


def build_caption_cues(
    words: list[TranscriptWord],
    clip_start: float,
    clip_end: float,
    words_per_cue: int = 7,
) -> list[CaptionCue]:
    duration = clip_end - clip_start
    local_words = [
        TranscriptWord(
            start=max(0.0, word.start - clip_start),
            end=min(duration, word.end - clip_start),
            word=word.word.strip(),
        )
        for word in words
        if word.end > clip_start and word.start < clip_end and word.word.strip()
    ]
    if not local_words:
        return []

    cues: list[CaptionCue] = []
    group: list[TranscriptWord] = []

    def flush() -> None:
        if not group:
            return
        cues.append(
            CaptionCue(
                start=round(group[0].start, 3),
                end=round(min(duration, group[-1].end + 0.08), 3),
                text=" ".join(word.word for word in group),
                words=tuple(group),
            )
        )
        group.clear()

    for word in local_words:
        next_text = " ".join([*(item.word for item in group), word.word])
        has_pause = bool(group and word.start - group[-1].end >= 0.55)
        too_long = bool(group and word.end - group[0].start > 3.2)
        too_wide = len(next_text) > 40
        if group and (len(group) >= words_per_cue or has_pause or too_long or too_wide):
            flush()
        group.append(word)
        ends_sentence = bool(re.search(r"""[.!?…]["'’”)]*$""", word.word))
        if ends_sentence and len(group) >= 2:
            flush()
    flush()
    return cues


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _escape_ass_text(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _karaoke_text(cue: CaptionCue, uppercase: bool) -> str:
    parts: list[str] = []
    for index, word in enumerate(cue.words):
        next_start = cue.words[index + 1].start if index + 1 < len(cue.words) else word.end
        centiseconds = max(1, round((next_start - word.start) * 100))
        text = _escape_ass_text(word.word.upper() if uppercase else word.word)
        parts.append(f"{{\\kf{centiseconds}}}{text}")
    return " ".join(parts)


def write_ass_captions(
    cues: list[CaptionCue],
    destination: Path,
    style: CaptionStyle,
) -> None:
    style_values = {
        CaptionStyle.CLEAN: "Arial,52,&H00FFFFFF,&H00D8D8D8,&H80000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,2,1,2,80,80,110,1",
        CaptionStyle.BOLD: "Arial,64,&H00FFFFFF,&H00D8D8D8,&H80000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,70,70,120,1",
        CaptionStyle.MINIMAL: "Arial,42,&H00FFFFFF,&H00D8D8D8,&H80000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,1,0,2,90,90,95,1",
    }
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Caption,{style_values[style]}\n\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    events = []
    for cue in cues:
        text = _karaoke_text(cue, uppercase=style == CaptionStyle.BOLD)
        events.append(
            f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},"
            f"Caption,,0,0,0,,{text}"
        )
    destination.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def _escape_filter_path(path: Path) -> str:
    return (
        path.resolve()
        .as_posix()
        .replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )


def build_filter_graph(
    edit: ClipEditSettings,
    duration: float,
    subtitle_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    video_filters: list[str] = []
    audio_filters: list[str] = []

    zoom = {ZoomPreset.OFF: 1.0, ZoomPreset.LIGHT: 1.08, ZoomPreset.MEDIUM: 1.15}[
        edit.zoom
    ]
    if zoom > 1:
        video_filters.append(f"crop=iw/{zoom}:ih/{zoom}")

    if edit.aspect_ratio == AspectRatio.PORTRAIT:
        video_filters.extend(
            [
                "scale=1080:1920:force_original_aspect_ratio=increase",
                "crop=1080:1920",
            ]
        )
    elif edit.aspect_ratio == AspectRatio.SQUARE:
        video_filters.extend(
            [
                "scale=1080:1080:force_original_aspect_ratio=increase",
                "crop=1080:1080",
            ]
        )
    else:
        video_filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    if subtitle_path is not None:
        escaped = _escape_filter_path(subtitle_path)
        video_filters.append(f"subtitles=filename='{escaped}'")

    if edit.fade_in > 0:
        fade = min(edit.fade_in, duration / 2)
        video_filters.append(f"fade=t=in:st=0:d={fade:.3f}")
        audio_filters.append(f"afade=t=in:st=0:d={fade:.3f}")
    if edit.fade_out > 0:
        fade = min(edit.fade_out, duration / 2)
        start = max(0.0, duration - fade)
        video_filters.append(f"fade=t=out:st={start:.3f}:d={fade:.3f}")
        audio_filters.append(f"afade=t=out:st={start:.3f}:d={fade:.3f}")

    return video_filters, audio_filters


def render_edited_clip(
    video_path: Path,
    destination: Path,
    edit: ClipEditSettings,
    words: list[TranscriptWord],
    work_dir: Path,
    settings: Settings,
) -> None:
    duration = edit.trim_end - edit.trim_start
    if duration <= 0:
        raise PipelineError("The clip end must be after its start")

    subtitle_path: Path | None = None
    if edit.captions:
        cues = build_caption_cues(words, edit.trim_start, edit.trim_end)
        if cues:
            subtitle_path = work_dir / f"{destination.stem}.ass"
            write_ass_captions(cues, subtitle_path, edit.caption_style)

    video_filters, audio_filters = build_filter_graph(edit, duration, subtitle_path)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{edit.trim_start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]
    if video_filters:
        command.extend(["-vf", ",".join(video_filters)])
    if audio_filters:
        command.extend(["-af", ",".join(audio_filters)])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )
    try:
        _run(command, settings.process_timeout_seconds)
    finally:
        if subtitle_path is not None:
            subtitle_path.unlink(missing_ok=True)
    if not destination.exists():
        raise PipelineError("The edited clip was not created")


def render_clips(
    video_path: Path,
    moments: list[Moment],
    work_dir: Path,
    settings: Settings,
) -> list[ClipResult]:
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    results: list[ClipResult] = []

    for index, moment in enumerate(moments, start=1):
        filename = f"clip-{index:02d}.mp4"
        destination = clips_dir / filename
        edit = ClipEditSettings(
            trim_start=moment.start,
            trim_end=moment.end,
            captions=False,
            fade_in=0,
            fade_out=0,
        )
        render_edited_clip(
            video_path=video_path,
            destination=destination,
            edit=edit,
            words=[],
            work_dir=work_dir,
            settings=settings,
        )
        results.append(ClipResult(**moment.model_dump(), filename=filename))
    return results
