import base64
import hashlib
import hmac
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI

from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.crypto import decrypt_secret, encrypt_secret
from app.jobs import JobStore, rerender_clip, run_job
from app.models import (
    ApiKeyRequest,
    ApiKeyStatusResponse,
    ClipRenderStatus,
    ClipTranscriptResponse,
    CreateJobRequest,
    CreateJobResponse,
    JobResponse,
    JobStatus,
    ProjectListResponse,
    RenderClipRequest,
    RenderClipResponse,
    SocialPostResponse,
)
from app.repository import RepositoryError, SupabaseRepository
from app.services.errors import PipelineError
from app.services.social import generate_social_post
from app.services.youtube import validate_youtube_url

settings = get_settings()
store = JobStore(settings.data_dir)
repository = SupabaseRepository(settings)
AuthenticatedUser = Annotated[CurrentUser, Depends(get_current_user)]
allowed_origins = {
    settings.web_origin.rstrip("/"),
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.cleanup_expired(settings.job_retention_hours)
    yield


app = FastAPI(title="ClipCraft API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_origin_regex=r"https://([a-z0-9-]+\.)*vercel\.app|https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _repository_error(exc: RepositoryError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


def _owned_job(job_id: str, user: CurrentUser):
    record = store.get(job_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return record


def _find_clip(job_id: str, filename: str, user: CurrentUser):
    record = _owned_job(job_id, user)
    if record.status != JobStatus.COMPLETE:
        raise HTTPException(status_code=404, detail="Clip not found")
    clip = next((item for item in record.clips if item.filename == filename), None)
    if clip is None or Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Clip not found")
    return record, clip


def _user_openai_settings(user: CurrentUser):
    try:
        record = repository.get_api_key_record(user.id, user.access_token)
    except RepositoryError as exc:
        raise _repository_error(exc) from exc
    if not record:
        raise HTTPException(
            status_code=409,
            detail="Add your OpenAI API key in Settings before creating a project.",
        )
    try:
        api_key = decrypt_secret(
            record["encrypted_key"],
            record["nonce"],
            user.id,
            settings.app_encryption_key,
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Your saved OpenAI key could not be decrypted. Add it again.",
        ) from exc
    return settings.model_copy(update={"openai_api_key": api_key})


def _record_event(user: CurrentUser, name: str, properties: dict | None = None) -> None:
    with suppress(RepositoryError):
        repository.record_event(user.id, user.access_token, name, properties)


def _media_signature(record_id: str, filename: str, user_id: str, expires: int) -> str:
    try:
        secret = base64.urlsafe_b64decode(settings.app_encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Media signing is not configured") from exc
    payload = f"{record_id}:{filename}:{user_id}:{expires}".encode()
    digest = hmac.new(secret, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _media_token(record_id: str, filename: str, user_id: str) -> str:
    expires = int(time.time()) + 6 * 60 * 60
    return f"{expires}.{_media_signature(record_id, filename, user_id, expires)}"


def _verify_media_token(job_id: str, filename: str, user_id: str, token: str) -> None:
    try:
        expires_text, signature = token.split(".", 1)
        expires = int(expires_text)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=403, detail="Invalid media link") from exc
    expected = _media_signature(job_id, filename, user_id, expires)
    if expires < int(time.time()) or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Expired or invalid media link")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects", response_model=ProjectListResponse)
def list_projects(user: AuthenticatedUser) -> ProjectListResponse:
    try:
        projects = repository.list_projects(user.id, user.access_token)
    except RepositoryError as exc:
        raise _repository_error(exc) from exc
    return ProjectListResponse(projects=projects)


@app.get("/api/account/openai-key", response_model=ApiKeyStatusResponse)
def get_openai_key_status(
    user: AuthenticatedUser,
) -> ApiKeyStatusResponse:
    try:
        record = repository.get_api_key_record(user.id, user.access_token)
    except RepositoryError as exc:
        raise _repository_error(exc) from exc
    return ApiKeyStatusResponse(
        configured=record is not None,
        last4=record.get("key_last4") if record else None,
    )


@app.put("/api/account/openai-key", response_model=ApiKeyStatusResponse)
def save_openai_key(
    payload: ApiKeyRequest,
    user: AuthenticatedUser,
) -> ApiKeyStatusResponse:
    api_key = payload.api_key.strip()
    if not api_key.startswith("sk-"):
        raise HTTPException(status_code=422, detail="Enter a valid OpenAI API key")
    try:
        OpenAI(api_key=api_key).models.list()
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="OpenAI rejected this key. Check the key and its permissions.",
        ) from exc
    try:
        encrypted, nonce = encrypt_secret(
            api_key,
            user.id,
            settings.app_encryption_key,
        )
        repository.upsert_api_key(
            user.id,
            user.access_token,
            encrypted,
            nonce,
            api_key[-4:],
        )
    except (RepositoryError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Could not save the API key") from exc
    _record_event(user, "openai_key_configured")
    return ApiKeyStatusResponse(configured=True, last4=api_key[-4:])


@app.delete("/api/account/openai-key", status_code=204)
def delete_openai_key(user: AuthenticatedUser) -> None:
    try:
        repository.delete_api_key(user.id, user.access_token)
    except RepositoryError as exc:
        raise _repository_error(exc) from exc


@app.post("/api/jobs", response_model=CreateJobResponse, status_code=202)
def create_job(
    payload: CreateJobRequest,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser,
) -> CreateJobResponse:
    try:
        validate_youtube_url(str(payload.url))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    user_settings = _user_openai_settings(user)
    store.cleanup_expired(settings.job_retention_hours)
    record = store.create(payload, user_id=user.id)
    try:
        repository.create_project(record, user.access_token)
    except RepositoryError as exc:
        (store.records_dir / f"{record.id}.json").unlink(missing_ok=True)
        raise _repository_error(exc) from exc
    _record_event(user, "project_created", {"project_id": record.id})
    background_tasks.add_task(
        run_job,
        record.id,
        store,
        user_settings,
        repository,
        user.access_token,
    )
    return CreateJobResponse(id=record.id, status=record.status)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    request: Request,
    user: AuthenticatedUser,
) -> JobResponse:
    record = _owned_job(job_id, user)
    source_available = store.source_video(job_id) is not None
    clips = []
    for clip in record.clips:
        token = _media_token(record.id, clip.filename, user.id)
        media_url = str(
            request.url_for("get_clip", job_id=job_id, filename=clip.filename)
        )
        clips.append(
            clip.model_copy(
                update={
                    "media_url": f"{media_url}?token={token}&v={clip.version}",
                    "download_url": (
                        f"{media_url}?token={token}&download=true&v={clip.version}"
                    ),
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
def get_clip_transcript(
    job_id: str,
    filename: str,
    user: AuthenticatedUser,
) -> ClipTranscriptResponse:
    record, clip = _find_clip(job_id, filename, user)
    words = record.transcript.words if record.transcript else []
    return ClipTranscriptResponse(
        words=[word for word in words if word.end > clip.start and word.start < clip.end]
    )


@app.post(
    "/api/jobs/{job_id}/clips/{filename}/social-post",
    response_model=SocialPostResponse,
)
def create_social_post(
    job_id: str,
    filename: str,
    user: AuthenticatedUser,
) -> SocialPostResponse:
    record, clip = _find_clip(job_id, filename, user)
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
            settings=_user_openai_settings(user),
        )
    except PipelineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    updated = store.update_clip(job_id, filename, social_post=text)
    with suppress(RepositoryError):
        repository.upsert_clips(updated, user.access_token)
    _record_event(user, "social_post_generated", {"project_id": job_id})
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
    user: AuthenticatedUser,
) -> RenderClipResponse:
    record, clip = _find_clip(job_id, filename, user)
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
    background_tasks.add_task(
        rerender_clip,
        job_id,
        filename,
        edit,
        store,
        settings,
        repository,
        user.access_token,
    )
    return RenderClipResponse(filename=filename, status=ClipRenderStatus.RENDERING)


@app.get("/api/jobs/{job_id}/clips/{filename}", name="get_clip")
def get_clip(
    job_id: str,
    filename: str,
    token: str = Query(...),
    download: bool = Query(default=False),
) -> FileResponse:
    record = store.get(job_id)
    if (
        record is None
        or record.status != JobStatus.COMPLETE
        or not record.user_id
        or Path(filename).name != filename
        or not any(clip.filename == filename for clip in record.clips)
    ):
        raise HTTPException(status_code=404, detail="Clip not found")
    _verify_media_token(job_id, filename, record.user_id, token)
    path = store.directory(job_id) / "clips" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename if download else None,
        content_disposition_type="attachment" if download else "inline",
        headers={"Cache-Control": "private, no-cache"},
    )
