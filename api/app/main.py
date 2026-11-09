import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import get_settings
from app.jobs import JobStore, rerender_clip, run_job
from app.models import (
    ClipRenderStatus,
    ClipTranscriptResponse,
    CreateJobRequest,
    CreateJobResponse,
    JobResponse,
    JobStatus,
    ProjectListResponse,
    ProjectSummary,
    RenderClipRequest,
    RenderClipResponse,
    RenderOptions,
    SocialPostResponse,
    SourceKind,
)
from app.services.errors import PipelineError
from app.services.social import generate_social_post, serialize_social_posts
from app.services.video import clip_window
from app.services.youtube import source_kind_for_url

SOCIAL_CONTEXT_SECONDS = 60
UPLOAD_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024

settings = get_settings()
store = JobStore(settings.data_dir)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.cleanup_expired(settings.job_retention_hours)
    yield


app = FastAPI(title="ClipCraft API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin.rstrip("/")],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def _get_job(job_id: str):
    record = store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return record


def _find_clip(job_id: str, filename: str):
    record = _get_job(job_id)
    if record.status != JobStatus.COMPLETE:
        raise HTTPException(status_code=404, detail="Clip not found")
    clip = next((item for item in record.clips if item.filename == filename), None)
    if clip is None or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Clip not found")
    return record, clip


def _edit_window(record, clip) -> tuple[float, float]:
    """How far the editor may move a clip's cuts: the previewed source around it."""
    if not clip.preview_filename:
        return clip.start, clip.end
    duration = record.video.duration if record.video else clip.end
    return clip_window(clip.start, clip.end, duration)


def _require_openai_key() -> None:
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=409,
            detail="Add OPENAI_API_KEY to the .env file and restart the API.",
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects", response_model=ProjectListResponse)
def list_projects() -> ProjectListResponse:
    projects = [
        ProjectSummary(
            id=record.id,
            source_url=record.request.source_label,
            source_kind=record.request.source_kind,
            title=record.video.title if record.video else None,
            status=record.status,
            progress=record.progress,
            message=record.message,
            error=record.error,
            clip_count=record.request.clip_count,
            target_duration=record.request.target_duration,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record in store.list()
    ]
    return ProjectListResponse(projects=projects)


@app.post("/api/jobs", response_model=CreateJobResponse, status_code=202)
def create_job(
    payload: CreateJobRequest,
    background_tasks: BackgroundTasks,
) -> CreateJobResponse:
    if payload.url is None:
        raise HTTPException(status_code=422, detail="Enter a YouTube or Twitch VOD URL")
    try:
        source_kind = source_kind_for_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _require_openai_key()

    store.cleanup_expired(settings.job_retention_hours)
    record = store.create(payload.model_copy(update={"source_kind": source_kind}))
    background_tasks.add_task(run_job, record.id, store, settings)
    return CreateJobResponse(id=record.id, status=record.status)


@app.post("/api/uploads", response_model=CreateJobResponse, status_code=202)
def create_upload_job(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    clip_count: Annotated[int, Form()] = 5,
    target_duration: Annotated[int, Form()] = 45,
    render: Annotated[str, Form()] = "{}",
) -> CreateJobResponse:
    name = Path(file.filename or "").name
    extension = Path(name).suffix.lower()
    if extension not in UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail="Upload an MP4, MOV, M4V, MKV, WebM, or AVI video",
        )
    try:
        payload = CreateJobRequest(
            source_kind=SourceKind.UPLOAD,
            upload_name=name[:200],
            clip_count=clip_count,
            target_duration=target_duration,
            render=RenderOptions.model_validate(json.loads(render or "{}")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid upload options") from exc
    _require_openai_key()

    store.cleanup_expired(settings.job_retention_hours)
    record = store.create(payload)
    directory = store.directory(record.id)
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / f"source{extension}.uploading"
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with partial.open("wb") as destination:
            while chunk := file.file.read(UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploads are limited to {settings.max_upload_mb} MB",
                    )
                destination.write(chunk)
        if written == 0:
            raise HTTPException(status_code=422, detail="The uploaded file is empty")
        partial.replace(directory / f"source{extension}")
    except HTTPException:
        partial.unlink(missing_ok=True)
        store.update(
            record.id,
            status=JobStatus.FAILED,
            message="Upload failed",
            error="The upload did not complete",
        )
        raise
    background_tasks.add_task(run_job, record.id, store, settings)
    return CreateJobResponse(id=record.id, status=record.status)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request) -> JobResponse:
    record = _get_job(job_id)
    source_available = store.source_video(job_id) is not None
    clips = []
    for clip in record.clips:
        media_url = str(request.url_for("get_clip", job_id=job_id, filename=clip.filename))
        preview_url = (
            str(request.url_for("get_preview", job_id=job_id, filename=clip.preview_filename))
            if clip.preview_filename
            else ""
        )
        clips.append(
            clip.model_copy(
                update={
                    "media_url": f"{media_url}?v={clip.version}",
                    "download_url": f"{media_url}?download=true&v={clip.version}",
                    "preview_url": preview_url,
                    "editable": source_available,
                }
            )
        )
    return JobResponse(
        id=record.id,
        status=record.status,
        progress=record.progress,
        message=record.message,
        video=record.video,
        clips=clips,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@app.get(
    "/api/jobs/{job_id}/clips/{filename}/transcript",
    response_model=ClipTranscriptResponse,
)
def get_clip_transcript(job_id: str, filename: str) -> ClipTranscriptResponse:
    record, clip = _find_clip(job_id, filename)
    words = record.transcript.words if record.transcript else []
    start, end = _edit_window(record, clip)
    return ClipTranscriptResponse(
        words=[word for word in words if word.end > start and word.start < end]
    )


@app.post(
    "/api/jobs/{job_id}/clips/{filename}/social-post",
    response_model=SocialPostResponse,
)
def create_social_post(job_id: str, filename: str) -> SocialPostResponse:
    record, clip = _find_clip(job_id, filename)
    if not record.video:
        raise HTTPException(status_code=409, detail="Video context is unavailable")
    _require_openai_key()
    start = clip.edit_settings.trim_start if clip.edit_settings else clip.start
    end = clip.edit_settings.trim_end if clip.edit_settings else clip.end
    words = record.transcript.words if record.transcript else []
    clip_words = [word for word in words if word.end > start and word.start < end]
    context_words = [
        word for word in words if word.end > start - SOCIAL_CONTEXT_SECONDS and word.end <= start
    ]
    try:
        posts = generate_social_post(
            video_title=record.video.title,
            clip=clip,
            words=clip_words,
            settings=settings,
            channel=record.video.channel,
            context_words=context_words,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    store.update_clip(job_id, filename, social_post=serialize_social_posts(posts))
    return SocialPostResponse(
        text=posts.quote,
        story_text=posts.story,
        breakdown_text=posts.breakdown,
    )


@app.post(
    "/api/jobs/{job_id}/clips/{filename}/render",
    response_model=RenderClipResponse,
    status_code=202,
)
def render_clip(
    job_id: str,
    filename: str,
    payload: RenderClipRequest,
    background_tasks: BackgroundTasks,
) -> RenderClipResponse:
    record, clip = _find_clip(job_id, filename)
    if store.source_video(job_id) is None:
        raise HTTPException(
            status_code=409,
            detail="This project predates editing support. Create it again to enable editing.",
        )
    if clip.render_status == ClipRenderStatus.RENDERING:
        raise HTTPException(status_code=409, detail="This clip is already rendering")

    edit = payload.settings
    window_start, window_end = _edit_window(record, clip)
    if edit.trim_start < window_start - 0.01 or edit.trim_end > window_end + 0.01:
        raise HTTPException(
            status_code=422,
            detail="Trim values must stay within the editable range around this clip",
        )
    if edit.trim_end - edit.trim_start < 2:
        raise HTTPException(status_code=422, detail="Edited clips must be at least 2 seconds")
    if edit.captions and not (record.transcript and record.transcript.words):
        raise HTTPException(status_code=409, detail="Word-level captions are unavailable")

    store.update_clip(
        job_id,
        filename,
        render_status=ClipRenderStatus.RENDERING,
        render_error=None,
    )
    background_tasks.add_task(rerender_clip, job_id, filename, edit, store, settings)
    return RenderClipResponse(filename=filename, status=ClipRenderStatus.RENDERING)


@app.get("/api/jobs/{job_id}/clips/{filename}", name="get_clip")
def get_clip(
    job_id: str,
    filename: str,
    download: bool = Query(default=False),
) -> FileResponse:
    record = store.get(job_id)
    if (
        record is None
        or record.status != JobStatus.COMPLETE
        or Path(filename).name != filename
        or not any(clip.filename == filename for clip in record.clips)
    ):
        raise HTTPException(status_code=404, detail="Clip not found")
    path = store.directory(job_id) / "clips" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename if download else None,
        content_disposition_type="attachment" if download else "inline",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/jobs/{job_id}/previews/{filename}", name="get_preview")
def get_preview(job_id: str, filename: str) -> FileResponse:
    record = store.get(job_id)
    if (
        record is None
        or Path(filename).name != filename
        or not any(clip.preview_filename == filename for clip in record.clips)
    ):
        raise HTTPException(status_code=404, detail="Preview not found")
    path = store.directory(job_id) / "previews" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Preview not found")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-cache"})
