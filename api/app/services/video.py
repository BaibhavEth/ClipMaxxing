import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.models import (
    AspectRatio,
    ClipEditSettings,
    ClipResult,
    Moment,
    RenderOptions,
    RenderReport,
    TranscriptWord,
    ZoomPreset,
)
from app.services.captions import (
    FONTS_DIR,
    CaptionCue,
    build_caption_cues,
    preset_for,
    write_ass_captions,
)
from app.services.errors import PipelineError
from app.services.framing import (
    Box,
    FramingPlan,
    Layout,
    MediaInfo,
    Shot,
    analyze_framing,
    apply_mode,
    estimate_cam_box,
    probe_media,
)
from app.services.pacing import TimeMap, compute_keep_intervals, snap

__all__ = ["CaptionCue", "build_caption_cues", "write_ass_captions"]

logger = logging.getLogger(__name__)

FPS = 30
# Seconds of source kept around each clip so the editor can extend its cuts.
EDIT_PADDING = 10.0
PERSON_FACE_Y = 0.40
PERSON_CROP_FACE_MULT = 3.2
MAX_UPSCALE = 2.5
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"
AUDIO_FORMAT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
PAUSE_LIMITS: dict[str, float | None] = {
    Layout.TALKING_HEAD: 0.7,
    Layout.TWO_SHOT: 0.7,
    Layout.GROUP: 0.7,
    Layout.SCREEN_CAM: 2.0,
    Layout.SCREEN: None,
}


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
        logger.warning("ffmpeg failed: %s", (exc.stderr or "").strip()[-2000:])
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


def clip_window(start: float, end: float, video_duration: float) -> tuple[float, float]:
    """Source range analyzed and previewed for a clip, including edit padding."""
    return max(0.0, start - EDIT_PADDING), min(video_duration, end + EDIT_PADDING)


# ------------------------------------------------------------------
# Geometry (source pixels)
# ------------------------------------------------------------------


def even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def output_size(aspect: AspectRatio, media: MediaInfo) -> tuple[int, int]:
    if aspect == AspectRatio.PORTRAIT:
        return 1080, 1920
    if aspect == AspectRatio.SQUARE:
        return 1080, 1080
    scale = min(1.0, 1920 / max(media.width, media.height))
    return even(media.width * scale), even(media.height * scale)


def piecewise_expr(points: list[tuple[float, float]]) -> str:
    """Piecewise-linear FFmpeg expression of ``t`` through (t, value) points."""
    if not points:
        return "0"
    points = sorted(points)
    expr = f"{points[-1][1]:.1f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(points, points[1:], strict=False))):
        span = max(t1 - t0, 1e-3)
        expr = f"if(lt(t,{t1:.3f}),{v0:.1f}+({v1 - v0:.1f})*(t-{t0:.3f})/{span:.3f},{expr})"
    return expr


def fill_crop(
    shot: Shot, src_w: int, src_h: int, out_w: int, out_h: int, origin: float
) -> tuple[int, int, str, str]:
    """Crop at the output aspect that follows the shot's focus path.

    Returns (w, h, x_expr, y_expr); expressions use window time (source time
    minus ``origin``).
    """
    target = out_w / out_h
    if src_w / src_h > target:
        crop_h, crop_w = even(src_h), even(src_h * target)
    else:
        crop_w, crop_h = even(src_w), even(src_w / target)
    focus = shot.focus or [(shot.start, 0.5, 0.5)]
    xs = [
        (t - origin, _clamp(cx * src_w - crop_w / 2, 0, src_w - crop_w)) for t, cx, _ in focus
    ]
    ys = [
        (t - origin, _clamp(cy * src_h - crop_h * PERSON_FACE_Y, 0, src_h - crop_h))
        for t, _, cy in focus
    ]
    x_expr = piecewise_expr(xs) if crop_w < src_w else "0"
    y_expr = piecewise_expr(ys) if crop_h < src_h else "0"
    return crop_w, crop_h, x_expr, y_expr


def person_crop(
    face: Box,
    src_w: int,
    src_h: int,
    panel_w: int,
    panel_h: int,
    x_bounds: tuple[float, float] | None = None,
) -> tuple[int, int, int, int]:
    """Head-and-shoulders crop (w, h, x, y) for one person at the panel's aspect."""
    aspect = panel_w / panel_h
    x0, x1 = x_bounds or (0.0, float(src_w))
    min_h = min(src_h, panel_h / MAX_UPSCALE)
    crop_h = _clamp(face.h * src_h * PERSON_CROP_FACE_MULT, min_h, src_h)
    crop_h = min(crop_h, max((x1 - x0) / aspect, min_h))
    crop_w = crop_h * aspect
    if crop_w > src_w:
        crop_w, crop_h = src_w, src_w / aspect
    bounds = (x0, x1) if crop_w <= x1 - x0 else (0.0, float(src_w))
    cx = face.cx * src_w
    cy = face.cy * src_h + crop_h * (0.5 - PERSON_FACE_Y)
    x = _clamp(cx - crop_w / 2, bounds[0], bounds[1] - crop_w)
    y = _clamp(cy - crop_h / 2, 0, src_h - crop_h)
    return even(crop_w), even(crop_h), max(0, int(x) // 2 * 2), max(0, int(y) // 2 * 2)


def cam_crop(
    face: Box, src_w: int, src_h: int, panel_w: int, panel_h: int
) -> tuple[int, int, int, int]:
    """Crop inside the estimated webcam overlay at the panel's aspect, centered on the face."""
    cam = estimate_cam_box(face, src_w / src_h)
    left, top = cam.x * src_w, cam.y * src_h
    cam_w, cam_h = cam.w * src_w, cam.h * src_h
    aspect = panel_w / panel_h
    crop_h = min(cam_h, cam_w / aspect)
    crop_w = crop_h * aspect
    x = _clamp(face.cx * src_w - crop_w / 2, left, left + cam_w - crop_w)
    y = _clamp(face.cy * src_h - crop_h * PERSON_FACE_Y, top, top + cam_h - crop_h)
    return even(crop_w), even(crop_h), max(0, int(x) // 2 * 2), max(0, int(y) // 2 * 2)


def screen_cam_heights(src_w: int, src_h: int, out_w: int, out_h: int) -> tuple[int, int]:
    top = min(even(out_w * src_h / src_w), even(out_h * 0.55))
    return top, out_h - top


def fitted_height(src_w: int, src_h: int, out_w: int, out_h: int) -> int:
    return min(out_h, even(out_w * src_h / src_w))


def _blur_fill(source: str, target: str, out_w: int, out_h: int, prefix: str) -> str:
    """Whole frame over a blurred, darkened fill of itself."""
    small_w, small_h = even(out_w / 4), even(out_h / 4)
    return (
        f"[{source}]split=2[{prefix}b][{prefix}f];"
        f"[{prefix}b]scale={small_w}:{small_h}:force_original_aspect_ratio=increase,"
        f"crop={small_w}:{small_h},gblur=sigma=10,lutyuv=y=val*0.75,"
        f"scale={out_w}:{out_h}[{prefix}bg];"
        f"[{prefix}f]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos"
        f"[{prefix}fg];"
        f"[{prefix}bg][{prefix}fg]overlay=(W-w)/2:(H-h)/2,setsar=1[{target}]"
    )


def shot_chain(
    source: str,
    target: str,
    shot: Shot,
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
    origin: float,
    prefix: str,
) -> str:
    """Filters that frame one trimmed piece from [source] into [target]."""
    scale = "flags=lanczos"
    if shot.layout == "original":
        return f"[{source}]scale={out_w}:{out_h}:{scale},setsar=1[{target}]"
    if shot.layout == Layout.TALKING_HEAD:
        w, h, x_expr, y_expr = fill_crop(shot, src_w, src_h, out_w, out_h, origin)
        return (
            f"[{source}]crop=w={w}:h={h}:x='{x_expr}':y='{y_expr}',"
            f"scale={out_w}:{out_h}:{scale},setsar=1[{target}]"
        )
    if shot.layout == Layout.TWO_SHOT and len(shot.people) >= 2:
        left, right = shot.people[0], shot.people[1]
        top_h = even(out_h / 2)
        bottom_h = out_h - top_h
        middle = (left.cx + right.cx) / 2 * src_w
        lw, lh, lx, ly = person_crop(left, src_w, src_h, out_w, top_h, (0, middle))
        rw, rh, rx, ry = person_crop(right, src_w, src_h, out_w, bottom_h, (middle, src_w))
        return (
            f"[{source}]split=2[{prefix}a][{prefix}b];"
            f"[{prefix}a]crop={lw}:{lh}:{lx}:{ly},scale={out_w}:{top_h}:{scale}[{prefix}top];"
            f"[{prefix}b]crop={rw}:{rh}:{rx}:{ry},scale={out_w}:{bottom_h}:{scale}[{prefix}bot];"
            f"[{prefix}top][{prefix}bot]vstack=inputs=2,setsar=1[{target}]"
        )
    if shot.layout == Layout.SCREEN_CAM and shot.people:
        top_h, bottom_h = screen_cam_heights(src_w, src_h, out_w, out_h)
        cw, ch, cx, cy = cam_crop(shot.people[0], src_w, src_h, out_w, bottom_h)
        return (
            f"[{source}]split=2[{prefix}s][{prefix}c];"
            f"[{prefix}s]scale={out_w}:{top_h}:force_original_aspect_ratio=increase:{scale},"
            f"crop={out_w}:{top_h}[{prefix}top];"
            f"[{prefix}c]crop={cw}:{ch}:{cx}:{cy},scale={out_w}:{bottom_h}:{scale}[{prefix}bot];"
            f"[{prefix}top][{prefix}bot]vstack=inputs=2,setsar=1[{target}]"
        )
    return _blur_fill(source, target, out_w, out_h, prefix)


def caption_y(layout: str, src_w: int, src_h: int, out_w: int, out_h: int) -> int:
    """Vertical center for captions over a layout, clear of faces and platform UI."""
    portrait = out_h > out_w * 1.2
    if layout == "original":
        return round(out_h * 0.84)
    if layout == Layout.TALKING_HEAD:
        return round(out_h * (0.70 if portrait else 0.80))
    if layout == Layout.TWO_SHOT:
        return even(out_h / 2)
    if layout == Layout.SCREEN_CAM:
        return screen_cam_heights(src_w, src_h, out_w, out_h)[0]
    picture = fitted_height(src_w, src_h, out_w, out_h)
    below = (out_h + picture) / 2
    if out_h - below > out_h * 0.12:
        return round(below + (out_h - below) * 0.4)
    return round(out_h * 0.8)


# ------------------------------------------------------------------
# Timeline
# ------------------------------------------------------------------


def timeline_pieces(
    plan: FramingPlan, keeps: list[tuple[float, float]], origin: float
) -> list[tuple[int, float, float]]:
    """(shot index, start, end) in window time for each kept piece of each shot."""
    pieces = []
    for keep_start, keep_end in keeps:
        for index, shot in enumerate(plan.shots):
            start = snap(max(keep_start, shot.start - origin))
            end = snap(min(keep_end, shot.end - origin))
            if end - start >= 1 / FPS:
                pieces.append((index, start, end))
    return pieces


def pause_limiter(plan: FramingPlan, origin: float) -> Callable[[float, float], float | None]:
    def limit(start: float, end: float) -> float | None:
        overlapping = [
            shot.layout
            for shot in plan.shots
            if shot.start - origin < end and shot.end - origin > start
        ]
        limits = [PAUSE_LIMITS.get(layout, 2.0) for layout in overlapping] or [2.0]
        return None if None in limits else max(limits)

    return limit


@dataclass
class RenderGraph:
    filter_complex: str
    has_audio: bool
    duration: float


def build_render_graph(
    edit: ClipEditSettings,
    plan: FramingPlan,
    keeps: list[tuple[float, float]],
    out_size: tuple[int, int],
    has_audio: bool,
    subtitle_path: Path | None = None,
) -> RenderGraph:
    """One filter graph from [0:v]/[0:a] (input seeked to trim_start) to [vout]/[aout]."""
    out_w, out_h = out_size
    origin = edit.trim_start
    src_w, src_h = plan.width, plan.height
    pieces = timeline_pieces(plan, keeps, origin)
    kept = sum(end - start for start, end in keeps)
    duration = kept / edit.speed

    parts: list[str] = []
    count = len(pieces)
    splits = "".join(f"[s{k}]" for k in range(count))
    parts.append(
        f"[0:v]fps={FPS},setpts=PTS-STARTPTS"
        + (f",split={count}{splits}" if count > 1 else "[s0]")
    )
    for k, (index, start, end) in enumerate(pieces):
        parts.append(f"[s{k}]trim=start={start:.4f}:end={end:.4f}[t{k}]")
        parts.append(
            shot_chain(
                f"t{k}", f"c{k}", plan.shots[index], src_w, src_h, out_w, out_h, origin, f"p{k}"
            )
        )
        parts.append(f"[c{k}]setpts=PTS-STARTPTS[v{k}]")
    inputs = "".join(f"[v{k}]" for k in range(count))
    video = [f"{inputs}concat=n={count}:v=1:a=0"]
    if edit.speed != 1:
        video.append(f"setpts=PTS/{edit.speed:.6g},fps={FPS}")
    zoom = {ZoomPreset.OFF: 1.0, ZoomPreset.LIGHT: 1.08, ZoomPreset.MEDIUM: 1.15}[edit.zoom]
    if zoom > 1:
        video.append(f"crop=iw/{zoom}:ih/{zoom},scale={out_w}:{out_h}:flags=lanczos")
    if subtitle_path is not None:
        video.append(
            f"subtitles=filename='{_escape_filter_path(subtitle_path)}'"
            f":fontsdir='{_escape_filter_path(FONTS_DIR)}'"
        )
    fades: list[str] = []
    audio_fades: list[str] = []
    if edit.fade_in > 0:
        fade = min(edit.fade_in, duration / 2)
        fades.append(f"fade=t=in:st=0:d={fade:.3f}")
        audio_fades.append(f"afade=t=in:st=0:d={fade:.3f}")
    if edit.fade_out > 0:
        fade = min(edit.fade_out, duration / 2)
        start = max(0.0, duration - fade)
        fades.append(f"fade=t=out:st={start:.3f}:d={fade:.3f}")
        audio_fades.append(f"afade=t=out:st={start:.3f}:d={fade:.3f}")
    video.extend(fades)
    video.append("format=yuv420p[vout]")
    parts.append(",".join(video))

    if has_audio:
        audio_count = len(keeps)
        audio_splits = "".join(f"[as{k}]" for k in range(audio_count))
        parts.append(
            f"[0:a]asetpts=PTS-STARTPTS,aresample=48000,{AUDIO_FORMAT}"
            + (f",asplit={audio_count}{audio_splits}" if audio_count > 1 else "[as0]")
        )
        for k, (start, end) in enumerate(keeps):
            piece = [f"[as{k}]atrim=start={start:.4f}:end={end:.4f}", "asetpts=PTS-STARTPTS"]
            if audio_count > 1:
                # Tiny fades stop jump cuts from clicking.
                piece.append("afade=t=in:d=0.012")
                piece.append(f"afade=t=out:st={max(0.0, end - start - 0.012):.4f}:d=0.012")
            parts.append(",".join(piece) + f"[a{k}]")
        audio = [
            "".join(f"[a{k}]" for k in range(audio_count))
            + f"concat=n={audio_count}:v=0:a=1",
            LOUDNESS,
        ]
        if edit.speed != 1:
            audio.append(f"atempo={edit.speed:.6g}")
        audio.extend(audio_fades)
        parts.append(",".join(audio) + "[aout]")

    return RenderGraph(filter_complex=";".join(parts), has_audio=has_audio, duration=duration)


def _escape_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def _caption_positioner(
    plan: FramingPlan,
    pieces: list[tuple[int, float, float]],
    speed: float,
    out_size: tuple[int, int],
) -> Callable[[float], tuple[int, int]]:
    out_w, out_h = out_size
    spans = []
    elapsed = 0.0
    for index, start, end in pieces:
        length = (end - start) / speed
        layout = plan.shots[index].layout
        spans.append((elapsed, elapsed + length, layout))
        elapsed += length

    def position(t: float) -> tuple[int, int]:
        layout = next((name for a, b, name in spans if a <= t < b), spans[-1][2])
        return out_w // 2, caption_y(layout, plan.width, plan.height, out_w, out_h)

    return position


def _encode_args() -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-r",
        str(FPS),
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
    ]


def render_edited_clip(
    video_path: Path,
    destination: Path,
    edit: ClipEditSettings,
    words: list[TranscriptWord],
    work_dir: Path,
    settings: Settings,
    analysis_window: tuple[float, float] | None = None,
) -> RenderReport:
    window = edit.trim_end - edit.trim_start
    if window <= 0:
        raise PipelineError("The clip end must be after its start")

    media = probe_media(video_path, timeout=min(60, settings.process_timeout_seconds))
    out_size = output_size(edit.aspect_ratio, media)
    analyze_start, analyze_end = analysis_window or (edit.trim_start, edit.trim_end)
    analyze_start = min(analyze_start, edit.trim_start)
    analyze_end = max(analyze_end, edit.trim_end)

    original = FramingPlan(
        media.width, media.height, [Shot(edit.trim_start, edit.trim_end, "original")]
    )
    if edit.aspect_ratio == AspectRatio.ORIGINAL and not edit.remove_dead_air:
        analyzed = original
    else:
        # Dead-air limits depend on what is on screen, so original-format clips
        # are analyzed too when pacing is tightened.
        full_plan = analyze_framing(
            video_path,
            analyze_start,
            analyze_end,
            media,
            target_aspect=out_size[0] / out_size[1],
            cache_dir=work_dir / "framing",
            timeout=settings.process_timeout_seconds,
        )
        analyzed = apply_mode(full_plan, edit.framing).slice(edit.trim_start, edit.trim_end)
    plan = original if edit.aspect_ratio == AspectRatio.ORIGINAL else analyzed

    window_words = [
        TranscriptWord(
            start=max(0.0, word.start - edit.trim_start),
            end=min(window, word.end - edit.trim_start),
            word=word.word.strip(),
        )
        for word in words
        if word.end > edit.trim_start and word.start < edit.trim_end and word.word.strip()
    ]
    if edit.remove_dead_air and window_words:
        keeps = compute_keep_intervals(
            window_words, window, pause_limiter(analyzed, edit.trim_start)
        )
    else:
        keeps = [(0.0, snap(window))]
    time_map = TimeMap(keeps)

    subtitle_path: Path | None = None
    if edit.captions and window_words:
        preset = preset_for(edit.caption_style)
        output_words = [
            TranscriptWord(start=word.start / edit.speed, end=word.end / edit.speed, word=word.word)
            for word in time_map.map_words(window_words)
        ]
        cues = build_caption_cues(
            output_words,
            0,
            time_map.duration / edit.speed,
            words_per_cue=preset.max_words,
            max_chars=preset.max_chars,
        )
        if cues:
            subtitle_path = work_dir / f"{destination.stem}.ass"
            pieces = timeline_pieces(plan, keeps, edit.trim_start)
            write_ass_captions(
                cues,
                subtitle_path,
                edit.caption_style,
                width=out_size[0],
                height=out_size[1],
                position=_caption_positioner(plan, pieces, edit.speed, out_size),
            )

    graph = build_render_graph(edit, plan, keeps, out_size, media.has_audio, subtitle_path)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{edit.trim_start:.3f}",
        "-t",
        f"{window:.3f}",
        "-i",
        str(video_path),
        "-filter_complex",
        graph.filter_complex,
        "-map",
        "[vout]",
    ]
    if graph.has_audio:
        command.extend(["-map", "[aout]"])
    command.extend([*_encode_args(), "-t", f"{graph.duration:.3f}", str(destination)])
    try:
        _run(command, settings.process_timeout_seconds)
    finally:
        if subtitle_path is not None:
            subtitle_path.unlink(missing_ok=True)
    if not destination.exists():
        raise PipelineError("The edited clip was not created")

    totals: dict[str, float] = {}
    for shot in analyzed.shots:
        totals[shot.layout] = totals.get(shot.layout, 0) + shot.end - shot.start
    return RenderReport(
        output_duration=round(graph.duration, 3),
        removed_seconds=round(window - time_map.duration, 3),
        layouts=sorted(totals, key=lambda name: -totals[name]),
    )


def render_source_preview(
    video_path: Path,
    destination: Path,
    start: float,
    end: float,
    settings: Settings,
) -> None:
    """Small, fast-to-load copy of the source around a clip for the editor."""
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{end - start:.3f}",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            "scale=-2:'min(540,ih)'",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        settings.process_timeout_seconds,
    )


def default_edit(moment: Moment, options: RenderOptions, has_words: bool) -> ClipEditSettings:
    return ClipEditSettings(
        trim_start=moment.start,
        trim_end=moment.end,
        aspect_ratio=options.aspect_ratio,
        captions=options.captions and has_words,
        caption_style=options.caption_style,
        fade_in=0,
        fade_out=0,
        framing=options.framing,
        remove_dead_air=options.remove_dead_air and has_words,
        speed=options.speed,
    )


def render_clips(
    video_path: Path,
    moments: list[Moment],
    work_dir: Path,
    settings: Settings,
    options: RenderOptions | None = None,
    words: list[TranscriptWord] | None = None,
    video_duration: float | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[ClipResult]:
    options = options or RenderOptions(
        aspect_ratio=AspectRatio.ORIGINAL, captions=False, remove_dead_air=False
    )
    words = words or []
    clips_dir = work_dir / "clips"
    previews_dir = work_dir / "previews"
    clips_dir.mkdir(parents=True, exist_ok=True)
    previews_dir.mkdir(parents=True, exist_ok=True)
    duration = video_duration or max(moment.end for moment in moments)
    results: list[ClipResult] = []

    for index, moment in enumerate(moments, start=1):
        if on_progress:
            on_progress(index, len(moments))
        filename = f"clip-{index:02d}.mp4"
        window = clip_window(moment.start, moment.end, duration)
        edit = default_edit(moment, options, bool(words))
        report = render_edited_clip(
            video_path=video_path,
            destination=clips_dir / filename,
            edit=edit,
            words=words,
            work_dir=work_dir,
            settings=settings,
            analysis_window=window,
        )
        preview_filename: str | None = f"preview-{index:02d}.mp4"
        try:
            render_source_preview(
                video_path, previews_dir / preview_filename, window[0], window[1], settings
            )
        except PipelineError:
            logger.warning("Could not render the editor preview for %s", filename)
            preview_filename = None
        results.append(
            ClipResult(
                **moment.model_dump(),
                filename=filename,
                edit_settings=edit,
                render_report=report,
                preview_filename=preview_filename,
                preview_start=window[0] if preview_filename else None,
            )
        )
    return results
