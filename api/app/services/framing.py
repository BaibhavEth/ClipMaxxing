"""Smart framing: decide how each shot of a clip should fill a vertical frame.

Frames are sampled a few times per second, faces are detected with YuNet, the
timeline is split at scene cuts, and every shot gets a layout:

- ``talking_head``: one on-camera speaker, followed by a smoothed virtual camera
- ``two_shot``: two people side by side, stacked into top and bottom panels
- ``screen_cam``: a screen share with a small webcam overlay in a corner
- ``group``: more than two people, shown whole over a blurred fill
- ``screen``: nobody on camera, shown whole over a blurred fill

All boxes are normalized to the source frame (0-1). All times are seconds on
the source timeline, so a plan analyzed once can be sliced for any trim.
"""

import json
import logging
import math
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median

from app.models import FramingMode
from app.services.errors import PipelineError

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - exercised only without OpenCV
    cv2 = None
    np = None

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "models" / (
    "face_detection_yunet_2023mar.onnx"
)

ANALYSIS_FPS = 4.0
ANALYSIS_MAX_WIDTH = 640
ANALYSIS_MAX_HEIGHT = 960
FACE_SCORE_THRESHOLD = 0.72
# Weak competing detections must not displace a confident real face.
STRONG_FACE_SCORE = 0.90
COMPETING_FACE_SCORE = 0.85
MAX_FACE_HEIGHT = 0.6
SHOT_CUT_THRESHOLD = 0.42
MIN_SHOT_SECONDS = 1.2
MIN_TRACK_PRESENCE = 0.35
MAX_TRACK_GAP_SECONDS = 1.0
MIN_FACE_HEIGHT = 0.035
OVERLAY_MAX_FACE_HEIGHT = 0.17
# Virtual camera: ignore movement inside this share of the crop width and cap
# the pan speed (crop widths per second) so the frame never jitters or whips.
CAMERA_DEADZONE = 0.12
CAMERA_MAX_SPEED = 0.9
MAX_PATH_KEYFRAMES = 40
# Bump when classification changes so cached plans are recomputed.
PLAN_VERSION = 2


class Layout:
    TALKING_HEAD = "talking_head"
    TWO_SHOT = "two_shot"
    SCREEN_CAM = "screen_cam"
    GROUP = "group"
    SCREEN = "screen"

    FITTED = (GROUP, SCREEN)


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass
class FrameSample:
    t: float
    faces: list[Box]
    hist: object = None


@dataclass
class FaceTrack:
    samples: list[tuple[float, Box]] = field(default_factory=list)

    def median_box(self) -> Box:
        return Box(
            median(box.x for _, box in self.samples),
            median(box.y for _, box in self.samples),
            median(box.w for _, box in self.samples),
            median(box.h for _, box in self.samples),
        )


@dataclass
class Shot:
    start: float
    end: float
    layout: str
    # talking_head: keyframes of (t, cx, cy) for the virtual camera
    focus: list[tuple[float, float, float]] = field(default_factory=list)
    # two_shot: left and right person; screen_cam: the webcam face
    people: list[Box] = field(default_factory=list)


@dataclass
class FramingPlan:
    width: int
    height: int
    shots: list[Shot]

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, payload: str) -> "FramingPlan":
        data = json.loads(payload)
        shots = [
            Shot(
                start=item["start"],
                end=item["end"],
                layout=item["layout"],
                focus=[tuple(point) for point in item["focus"]],
                people=[Box(**box) for box in item["people"]],
            )
            for item in data["shots"]
        ]
        return cls(width=data["width"], height=data["height"], shots=shots)

    def layout_at(self, t: float) -> str:
        for shot in self.shots:
            if shot.start <= t < shot.end:
                return shot.layout
        return self.shots[-1].layout if self.shots else Layout.SCREEN

    def slice(self, start: float, end: float) -> "FramingPlan":
        shots = []
        for shot in self.shots:
            if shot.end <= start or shot.start >= end:
                continue
            shots.append(
                Shot(
                    start=max(shot.start, start),
                    end=min(shot.end, end),
                    layout=shot.layout,
                    focus=list(shot.focus),
                    people=list(shot.people),
                )
            )
        if not shots:
            shots = [Shot(start=start, end=end, layout=Layout.SCREEN)]
        shots[0].start, shots[-1].end = start, end
        return FramingPlan(width=self.width, height=self.height, shots=shots)


# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------


def is_corner_overlay(face: Box) -> bool:
    """A small face in a frame corner is almost always a webcam overlay."""
    if face.h > OVERLAY_MAX_FACE_HEIGHT:
        return False
    horizontal = face.cx < 0.3 or face.cx > 0.7
    vertical = face.cy < 0.35 or face.cy > 0.65
    return horizontal and vertical


def reliable_faces(detections: list[tuple[Box, float]]) -> list[Box]:
    """Drop implausibly large boxes, and weak ones when a confident face is present."""
    plausible = [(box, score) for box, score in detections if box.h <= MAX_FACE_HEIGHT]
    strong = any(score >= STRONG_FACE_SCORE for _, score in plausible)
    return [box for box, score in plausible if not strong or score >= COMPETING_FACE_SCORE]


def estimate_cam_box(face: Box, source_aspect: float) -> Box:
    """Rough 16:9 webcam overlay around a small corner face (head-and-shoulders)."""
    cam_h = min(0.45, face.h / 0.4)
    cam_w = min(0.45, cam_h * (16 / 9) / source_aspect)
    x = min(max(0.0, face.cx - cam_w / 2), 1 - cam_w)
    y = min(max(0.0, face.cy - cam_h * 0.45), 1 - cam_h)
    return Box(x, y, cam_w, cam_h)


def segment_shots(cut_times: list[float], start: float, end: float) -> list[tuple[float, float]]:
    """Split [start, end) at scene cuts, merging shots shorter than MIN_SHOT_SECONDS."""
    bounds = [start, *sorted(t for t in cut_times if start < t < end), end]
    merged: list[tuple[float, float]] = []
    for shot_start, shot_end in zip(bounds, bounds[1:], strict=False):
        if shot_end <= shot_start:
            continue
        if merged and (
            shot_end - shot_start < MIN_SHOT_SECONDS
            or merged[-1][1] - merged[-1][0] < MIN_SHOT_SECONDS
        ):
            merged[-1] = (merged[-1][0], shot_end)
        else:
            merged.append((shot_start, shot_end))
    return merged or [(start, end)]


def track_faces(frames: list[FrameSample]) -> list[FaceTrack]:
    """Associate each frame's faces with the nearest compatible track."""
    tracks: list[FaceTrack] = []
    for frame in frames:
        used: set[int] = set()
        for face in sorted(frame.faces, key=lambda box: -box.area):
            best, best_distance = None, 0.12
            for index, track in enumerate(tracks):
                last_t, last = track.samples[-1]
                if index in used or frame.t - last_t > MAX_TRACK_GAP_SECONDS:
                    continue
                distance = math.hypot(last.cx - face.cx, last.cy - face.cy)
                size_ratio = face.h / max(last.h, 1e-6)
                if distance < best_distance and 0.5 < size_ratio < 2.0:
                    best, best_distance = index, distance
            if best is None:
                tracks.append(FaceTrack(samples=[(frame.t, face)]))
                used.add(len(tracks) - 1)
            else:
                tracks[best].samples.append((frame.t, face))
                used.add(best)
    return tracks


def simplify_path(path: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """Fewest keyframes that reproduce the path within 0.2% of the frame."""
    if len(path) <= 2:
        return path
    keep = [0, len(path) - 1]
    while len(keep) < MAX_PATH_KEYFRAMES:
        worst_error, worst_index = 0.002, None
        for a, b in zip(keep, keep[1:], strict=False):
            t0, x0, y0 = path[a]
            t1, x1, y1 = path[b]
            for index in range(a + 1, b):
                t, x, y = path[index]
                fraction = (t - t0) / max(t1 - t0, 1e-6)
                error = max(
                    abs(x - (x0 + (x1 - x0) * fraction)), abs(y - (y0 + (y1 - y0) * fraction))
                )
                if error > worst_error:
                    worst_error, worst_index = error, index
        if worst_index is None:
            break
        keep.append(worst_index)
        keep.sort()
    return [path[index] for index in keep]


def smooth_focus_path(
    samples: list[tuple[float, Box]],
    start: float,
    end: float,
    crop_width_fraction: float,
) -> list[tuple[float, float, float]]:
    """Turn noisy face centers into a calm virtual-camera path.

    The camera holds still while the subject stays inside a dead zone, then
    eases toward them at a capped speed.
    """
    if not samples:
        return [(start, 0.5, 0.5), (end, 0.5, 0.5)]
    samples = sorted(samples, key=lambda item: item[0])
    step = 1 / ANALYSIS_FPS

    grid: list[tuple[float, float, float]] = []
    index = 0
    steps = max(1, math.ceil((end - start) / step))
    for n in range(steps + 1):
        t = min(end, start + n * step)
        while index + 1 < len(samples) and abs(samples[index + 1][0] - t) <= abs(
            samples[index][0] - t
        ):
            index += 1
        grid.append((t, samples[index][1].cx, samples[index][1].cy))

    # A median filter rejects single-frame detector jumps.
    xs = [point[1] for point in grid]
    ys = [point[2] for point in grid]
    fx = [median(xs[max(0, i - 2) : i + 3]) for i in range(len(xs))]
    fy = [median(ys[max(0, i - 2) : i + 3]) for i in range(len(ys))]

    deadzone = CAMERA_DEADZONE * crop_width_fraction
    max_step = CAMERA_MAX_SPEED * crop_width_fraction * step
    opening = max(1, int(ANALYSIS_FPS))
    camera_x, camera_y = median(fx[:opening]), median(fy[:opening])
    path = [(grid[0][0], camera_x, camera_y)]
    for (t, _, _), x, y in zip(grid[1:], fx[1:], fy[1:], strict=False):
        dx = x - camera_x
        if abs(dx) > deadzone:
            overshoot = dx - math.copysign(deadzone, dx)
            camera_x += max(-max_step, min(max_step, overshoot * 0.5))
        camera_y += (y - camera_y) * 0.2
        path.append((t, camera_x, camera_y))
    return simplify_path(path)


def classify_shot(
    tracks: list[FaceTrack],
    frame_count: int,
    start: float,
    end: float,
    crop_width_fraction: float,
) -> Shot:
    present = [
        track
        for track in tracks
        if len(track.samples) >= max(1, MIN_TRACK_PRESENCE * frame_count)
        and track.median_box().h >= MIN_FACE_HEIGHT
    ]
    present.sort(key=lambda track: -track.median_box().area)
    overlays = [track for track in present if is_corner_overlay(track.median_box())]
    if len(overlays) >= 2:
        # Several small faces in different corners are a wide shot of people,
        # not a webcam overlay.
        overlays = []
    on_camera = [track for track in present if track not in overlays]

    if len(on_camera) > 2:
        return Shot(start, end, Layout.GROUP)
    if len(on_camera) == 2:
        a, b = on_camera[0].median_box(), on_camera[1].median_box()
        similar = min(a.h, b.h) / max(a.h, b.h) >= 0.5
        separated = abs(a.cx - b.cx) >= 0.22
        # Both people must be on screen for most of the shot, not just glimpsed.
        steady = min(len(on_camera[0].samples), len(on_camera[1].samples)) >= 0.5 * frame_count
        if similar and separated and steady:
            return Shot(start, end, Layout.TWO_SHOT, people=sorted([a, b], key=lambda box: box.cx))
    if on_camera:
        main = on_camera[0]
        focus = smooth_focus_path(main.samples, start, end, crop_width_fraction)
        return Shot(start, end, Layout.TALKING_HEAD, focus=focus, people=[main.median_box()])
    if overlays:
        return Shot(start, end, Layout.SCREEN_CAM, people=[overlays[0].median_box()])
    return Shot(start, end, Layout.SCREEN)


def merge_shots(shots: list[Shot]) -> list[Shot]:
    """Join neighbours that render identically so the filter graph stays small."""
    merged: list[Shot] = []
    for shot in shots:
        previous = merged[-1] if merged else None
        if previous and previous.layout == shot.layout:
            same_people = len(previous.people) == len(shot.people) and all(
                abs(a.cx - b.cx) < 0.08 and abs(a.cy - b.cy) < 0.08
                for a, b in zip(previous.people, shot.people, strict=False)
            )
            if shot.layout in Layout.FITTED or (
                shot.layout != Layout.TALKING_HEAD and same_people
            ):
                previous.end = shot.end
                continue
        merged.append(shot)
    return merged


def apply_mode(plan: FramingPlan, mode: FramingMode) -> FramingPlan:
    """Override the detected layouts with the user's framing choice."""
    if mode == FramingMode.AUTO:
        return plan
    shots = []
    for shot in plan.shots:
        if mode == FramingMode.FIT:
            shots.append(Shot(shot.start, shot.end, Layout.SCREEN))
        elif shot.layout == Layout.TALKING_HEAD:
            shots.append(shot)
        else:
            focus_box = shot.people[0] if shot.people and shot.layout == Layout.TWO_SHOT else None
            cx, cy = (focus_box.cx, focus_box.cy) if focus_box else (0.5, 0.5)
            shots.append(
                Shot(
                    shot.start,
                    shot.end,
                    Layout.TALKING_HEAD,
                    focus=[(shot.start, cx, cy), (shot.end, cx, cy)],
                    people=[focus_box] if focus_box else [],
                )
            )
    return FramingPlan(width=plan.width, height=plan.height, shots=merge_shots(shots))


def centered_plan(width: int, height: int, start: float, end: float) -> FramingPlan:
    return FramingPlan(
        width=width,
        height=height,
        shots=[
            Shot(start, end, Layout.TALKING_HEAD, focus=[(start, 0.5, 0.5), (end, 0.5, 0.5)])
        ],
    )


# ------------------------------------------------------------------
# Media analysis
# ------------------------------------------------------------------


@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    duration: float
    has_audio: bool


def probe_media(video_path: Path, timeout: int = 60) -> MediaInfo:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,width,height:stream_side_data=rotation:format=duration",
                "-of",
                "json",
                str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        payload = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise PipelineError("ffprobe is not installed or is not on PATH") from exc
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise PipelineError("Could not read this video's media details") from exc

    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video or not video.get("width") or not video.get("height"):
        raise PipelineError("No video track was found in this file")
    width, height = int(video["width"]), int(video["height"])
    rotation = next(
        (
            int(item.get("rotation", 0))
            for item in video.get("side_data_list", [])
            if "rotation" in item
        ),
        0,
    )
    if abs(rotation) % 180 == 90:
        width, height = height, width
    try:
        duration = float(payload.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0.0
    return MediaInfo(
        width=width,
        height=height,
        duration=duration,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def _analysis_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, ANALYSIS_MAX_WIDTH / width, ANALYSIS_MAX_HEIGHT / height)
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def _sample_frames(
    video_path: Path,
    start: float,
    end: float,
    width: int,
    height: int,
    timeout: int,
) -> list[FrameSample]:
    analysis_w, analysis_h = _analysis_size(width, height)
    detector = cv2.FaceDetectorYN.create(
        str(MODEL_PATH), "", (analysis_w, analysis_h), FACE_SCORE_THRESHOLD, 0.3, 50
    )
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{end - start:.3f}",
        "-i",
        str(video_path),
        "-an",
        "-vf",
        f"fps={ANALYSIS_FPS},scale={analysis_w}:{analysis_h}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "pipe:1",
    ]
    frame_bytes = analysis_w * analysis_h * 3
    frames: list[FrameSample] = []
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        assert process.stdout is not None
        index = 0
        while True:
            buffer = process.stdout.read(frame_bytes)
            if len(buffer) < frame_bytes:
                break
            image = np.frombuffer(buffer, dtype=np.uint8).reshape(analysis_h, analysis_w, 3)
            _, detections = detector.detect(image)
            found: list[tuple[Box, float]] = []
            for row in detections if detections is not None else []:
                x, y, w, h = (float(value) for value in row[:4])
                if w <= 0 or h <= 0 or not 0.5 <= w / h <= 1.6:
                    continue
                box = Box(
                    max(0.0, x / analysis_w),
                    max(0.0, y / analysis_h),
                    min(1.0, w / analysis_w),
                    min(1.0, h / analysis_h),
                )
                found.append((box, float(row[14])))
            faces = reliable_faces(found)
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            frames.append(FrameSample(t=start + index / ANALYSIS_FPS, faces=faces, hist=hist))
            index += 1
        process.wait(timeout=timeout)
    finally:
        if process.poll() is None:
            process.kill()
    return frames


def build_plan(
    frames: list[FrameSample],
    width: int,
    height: int,
    start: float,
    end: float,
    target_aspect: float,
) -> FramingPlan:
    cuts = []
    for previous, current in zip(frames, frames[1:], strict=False):
        if previous.hist is None or current.hist is None:
            continue
        distance = cv2.compareHist(previous.hist, current.hist, cv2.HISTCMP_BHATTACHARYYA)
        if distance > SHOT_CUT_THRESHOLD:
            cuts.append((previous.t + current.t) / 2)

    crop_width_fraction = min(1.0, height * target_aspect / width)
    shots = []
    for shot_start, shot_end in segment_shots(cuts, start, end):
        shot_frames = [frame for frame in frames if shot_start <= frame.t < shot_end]
        tracks = track_faces(shot_frames)
        shots.append(
            classify_shot(tracks, len(shot_frames), shot_start, shot_end, crop_width_fraction)
        )
    return FramingPlan(width=width, height=height, shots=merge_shots(shots))


def analyze_framing(
    video_path: Path,
    start: float,
    end: float,
    media: MediaInfo,
    target_aspect: float,
    cache_dir: Path | None = None,
    timeout: int = 600,
) -> FramingPlan:
    """Framing plan for [start, end) of the source, cached on disk when possible."""
    cache_path = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = (
            f"v{PLAN_VERSION}-{round(start * 1000)}-{round(end * 1000)}"
            f"-{round(target_aspect * 1000)}"
        )
        cache_path = cache_dir / f"{key}.json"
        if cache_path.is_file():
            try:
                return FramingPlan.from_json(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("Ignoring unreadable framing cache %s", cache_path)

    if cv2 is None or not MODEL_PATH.is_file():
        logger.warning("OpenCV or the face model is unavailable; using a centered crop")
        return centered_plan(media.width, media.height, start, end)
    try:
        frames = _sample_frames(video_path, start, end, media.width, media.height, timeout)
        plan = build_plan(frames, media.width, media.height, start, end, target_aspect)
    except Exception:
        logger.exception("Framing analysis failed; using a centered crop")
        return centered_plan(media.width, media.height, start, end)

    if cache_path is not None:
        cache_path.write_text(plan.to_json(), encoding="utf-8")
    return plan
