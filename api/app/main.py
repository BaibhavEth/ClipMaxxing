from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
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
    RenderClipRequest,
    RenderClipResponse,
    SocialPostResponse,
)
from app.services.errors import PipelineError
from app.services.social import generate_social_post
from app.services.youtube import validate_youtube_url

settings = get_settings()
store = JobStore(settings.data_dir)
allowed_origins = {
    settings.web_origin.rstrip("/"),
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.cleanup_expired(settings.job_retention_hours)
    yield


app = FastAPI(title="ClipCraft API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs", response_model=CreateJobResponse, status_code=202)
def create_job(
    payload: CreateJobRequest,
    background_tasks: BackgroundTasks,
) -> CreateJobResponse:
    try:
        validate_youtube_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.cleanup_expired(settings.job_retention_hours)
    record = store.create(payload)
    background_tasks.add_task(run_job, record.id, store, settings)
    return CreateJobResponse(id=record.id, status=record.status)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request) -> JobResponse:
    record = store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")

    source_available = store.source_video(job_id) is not None
    clips = [
        clip.model_copy(
            update={
                "media_url": str(
                    request.url_for("get_clip", job_id=job_id, filename=clip.filename)
                )
                + f"?v={clip.version}",
                "download_url": str(
                    request.url_for("get_clip", job_id=job_id, filename=clip.filename)
                )
                + f"?download=true&v={clip.version}",
                "editable": source_available,
            }
        )
        for clip in record.clips
    ]
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


def _find_clip(job_id: str, filename: str):
    record = store.get(job_id)
    if record is None or record.status != JobStatus.COMPLETE:
        raise HTTPException(status_code=404, detail="Clip not found")
    clip = next((item for item in record.clips if item.filename == filename), None)
    if clip is None or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Clip not found")
    return record, clip


@app.get(
    "/api/jobs/{job_id}/clips/{filename}/transcript",
    response_model=ClipTranscriptResponse,
)
def get_clip_transcript(job_id: str, filename: str) -> ClipTranscriptResponse:
    record, clip = _find_clip(job_id, filename)
    words = record.transcript.words if record.transcript else []
    return ClipTranscriptResponse(
        words=[word for word in words if word.end > clip.start and word.start < clip.end]
    )


@app.post(
    "/api/jobs/{job_id}/clips/{filename}/social-post",
    response_model=SocialPostResponse,
)
def create_social_post(job_id: str, filename: str) -> SocialPostResponse:
    record, clip = _find_clip(job_id, filename)
    if not record.video:
        raise HTTPException(status_code=409, detail="Video context is unavailable")
    start = clip.edit_settings.trim_start if clip.edit_settings else clip.start
    end = clip.edit_settings.trim_end if clip.edit_settings else clip.end
    words = record.transcript.words if record.transcript else []
    clip_words = [word for word in words if word.end > start and word.start < end]
    try:
        text = generate_social_post(
            video_title=record.video.title,
            clip=clip,
            words=clip_words,
            settings=settings,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    store.update_clip(job_id, filename, social_post=text)
    return SocialPostResponse(text=text)


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
    if edit.trim_start < clip.start or edit.trim_end > clip.end:
        raise HTTPException(
            status_code=422,
            detail="Trim values must stay within the original clip",
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
    _find_clip(job_id, filename)

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
