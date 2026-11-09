from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    COMPLETE = "complete"
    FAILED = "failed"


class AspectRatio(StrEnum):
    ORIGINAL = "original"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class CaptionStyle(StrEnum):
    CLEAN = "clean"
    BOLD = "bold"
    MINIMAL = "minimal"
    POP = "pop"
    SPOTLIGHT = "spotlight"
    IMPACT = "impact"
    BOXED = "boxed"
    SWEEP = "sweep"
    PUNCH = "punch"
    GLOW = "glow"


class FramingMode(StrEnum):
    AUTO = "auto"
    FILL = "fill"
    FIT = "fit"


class SourceKind(StrEnum):
    YOUTUBE = "youtube"
    TWITCH = "twitch"
    UPLOAD = "upload"


class RenderOptions(BaseModel):
    aspect_ratio: AspectRatio = AspectRatio.PORTRAIT
    framing: FramingMode = FramingMode.AUTO
    captions: bool = True
    caption_style: CaptionStyle = CaptionStyle.POP
    remove_dead_air: bool = True
    speed: float = Field(default=1.0, ge=1, le=2)


class CreateJobRequest(BaseModel):
    url: HttpUrl | None = None
    source_kind: SourceKind = SourceKind.YOUTUBE
    upload_name: str | None = Field(default=None, max_length=200)
    clip_count: int = Field(default=5, ge=1, le=8)
    target_duration: int = Field(default=45, ge=15, le=180)
    render: RenderOptions = Field(default_factory=RenderOptions)

    @property
    def source_label(self) -> str:
        return str(self.url) if self.url else (self.upload_name or "Uploaded video")


class VideoInfo(BaseModel):
    title: str
    duration: float = Field(gt=0)
    source_url: str
    thumbnail_url: str | None = None
    channel: str = ""
    description: str = ""


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str


class TranscriptWord(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    word: str


class TranscriptData(BaseModel):
    segments: list[TranscriptSegment] = Field(default_factory=list)
    words: list[TranscriptWord] = Field(default_factory=list)


class ZoomPreset(StrEnum):
    OFF = "off"
    LIGHT = "light"
    MEDIUM = "medium"


class ClipRenderStatus(StrEnum):
    READY = "ready"
    RENDERING = "rendering"
    FAILED = "failed"


class ClipEditSettings(BaseModel):
    trim_start: float = Field(ge=0)
    trim_end: float = Field(gt=0)
    aspect_ratio: AspectRatio = AspectRatio.ORIGINAL
    captions: bool = True
    caption_style: CaptionStyle = CaptionStyle.CLEAN
    fade_in: float = Field(default=0.25, ge=0, le=2)
    fade_out: float = Field(default=0.25, ge=0, le=2)
    zoom: ZoomPreset = ZoomPreset.OFF
    framing: FramingMode = FramingMode.AUTO
    remove_dead_air: bool = False
    speed: float = Field(default=1.0, ge=1, le=2)


class Moment(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=300)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    score: float | None = Field(default=None, ge=0, le=10)


class RenderReport(BaseModel):
    output_duration: float = 0
    removed_seconds: float = 0
    layouts: list[str] = Field(default_factory=list)


class ClipResult(Moment):
    filename: str
    media_url: str = ""
    download_url: str = ""
    preview_filename: str | None = None
    preview_start: float | None = None
    preview_url: str = ""
    render_report: RenderReport | None = None
    editable: bool = False
    edit_settings: ClipEditSettings | None = None
    render_status: ClipRenderStatus = ClipRenderStatus.READY
    render_error: str | None = None
    version: int = Field(default=0, ge=0)
    social_post: str | None = None


class JobRecord(BaseModel):
    id: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    message: str = "Waiting to start"
    request: CreateJobRequest
    video: VideoInfo | None = None
    clips: list[ClipResult] = Field(default_factory=list)
    transcript: TranscriptData | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreateJobResponse(BaseModel):
    id: str
    status: JobStatus


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    progress: int
    message: str
    video: VideoInfo | None
    clips: list[ClipResult]
    error: str | None
    created_at: datetime
    updated_at: datetime


class RenderClipRequest(BaseModel):
    settings: ClipEditSettings


class RenderClipResponse(BaseModel):
    filename: str
    status: ClipRenderStatus


class ClipTranscriptResponse(BaseModel):
    words: list[TranscriptWord]


class SocialPostResponse(BaseModel):
    text: str
    story_text: str = ""
    breakdown_text: str = ""


class ProjectSummary(BaseModel):
    id: str
    source_url: str
    source_kind: SourceKind = SourceKind.YOUTUBE
    title: str | None
    status: JobStatus
    progress: int
    message: str
    error: str | None
    clip_count: int
    target_duration: int
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary]
