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


class CreateJobRequest(BaseModel):
    url: HttpUrl
    clip_count: int = Field(default=5, ge=1, le=8)
    target_duration: int = Field(default=45, ge=15, le=180)


class VideoInfo(BaseModel):
    title: str
    duration: float = Field(gt=0)
    source_url: str
    thumbnail_url: str | None = None


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


class AspectRatio(StrEnum):
    ORIGINAL = "original"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class CaptionStyle(StrEnum):
    CLEAN = "clean"
    BOLD = "bold"
    MINIMAL = "minimal"


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


class Moment(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=300)
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class ClipResult(Moment):
    filename: str
    media_url: str = ""
    download_url: str = ""
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
