import logging
import shutil
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.config import Settings
from app.models import (
    ClipEditSettings,
    ClipRenderStatus,
    CreateJobRequest,
    JobRecord,
    JobStatus,
)
from app.services.errors import PipelineError
from app.services.moments import select_key_moments
from app.services.transcription import transcribe_audio_chunks
from app.services.video import extract_audio_chunks, render_clips, render_edited_clip
from app.services.youtube import download_video, fetch_metadata

logger = logging.getLogger(__name__)


class JobStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.records_dir = data_dir / "jobs"
        self.work_dir = data_dir / "work"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _safe_id(job_id: str) -> str:
        parsed = UUID(job_id)
        if str(parsed) != job_id:
            raise ValueError("Invalid job ID")
        return job_id

    def _record_path(self, job_id: str) -> Path:
        return self.records_dir / f"{self._safe_id(job_id)}.json"

    def create(self, request: CreateJobRequest) -> JobRecord:
        record = JobRecord(id=str(uuid4()), request=request)
        self.save(record)
        return record

    def save(self, record: JobRecord) -> None:
        destination = self._record_path(record.id)
        temporary = destination.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(destination)

    def get(self, job_id: str) -> JobRecord | None:
        try:
            path = self._record_path(job_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Could not read job record %s", job_id)
            return None

    def update(self, job_id: str, **changes: Any) -> JobRecord:
        record = self.get(job_id)
        if record is None:
            raise KeyError(job_id)
        changes["updated_at"] = datetime.now(UTC)
        updated = record.model_copy(update=changes)
        self.save(updated)
        return updated

    def update_clip(self, job_id: str, filename: str, **changes: Any) -> JobRecord:
        with self._lock:
            record = self.get(job_id)
            if record is None:
                raise KeyError(job_id)
            clips = [
                clip.model_copy(update=changes) if clip.filename == filename else clip
                for clip in record.clips
            ]
            if not any(clip.filename == filename for clip in record.clips):
                raise KeyError(filename)
            updated = record.model_copy(
                update={"clips": clips, "updated_at": datetime.now(UTC)}
            )
            self.save(updated)
            return updated

    def directory(self, job_id: str) -> Path:
        return self.work_dir / self._safe_id(job_id)

    def source_video(self, job_id: str) -> Path | None:
        candidates = [
            path
            for path in self.directory(job_id).glob("source.*")
            if path.is_file() and path.suffix not in {".part", ".ytdl"}
        ]
        return max(candidates, key=lambda path: path.stat().st_size) if candidates else None

    def cleanup_expired(self, retention_hours: int) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
        for record_path in self.records_dir.glob("*.json"):
            try:
                record = JobRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
                if record.updated_at >= cutoff:
                    continue
                record_path.unlink(missing_ok=True)
                shutil.rmtree(self.directory(record.id), ignore_errors=True)
            except (OSError, ValueError):
                logger.warning("Skipping unreadable job record %s", record_path)


def run_job(job_id: str, store: JobStore, settings: Settings) -> None:
    work_dir = store.directory(job_id)
    try:
        record = store.get(job_id)
        if record is None:
            return
        url = str(record.request.url)

        store.update(
            job_id,
            status=JobStatus.DOWNLOADING,
            progress=5,
            message="Reading video details",
        )
        video_info = fetch_metadata(url, settings)
        store.update(
            job_id,
            video=video_info,
            progress=12,
            message="Downloading video",
        )
        video_path = download_video(url, work_dir, settings)

        store.update(
            job_id,
            status=JobStatus.TRANSCRIBING,
            progress=30,
            message="Preparing audio",
        )
        chunks = extract_audio_chunks(video_path, work_dir, settings)
        store.update(job_id, progress=40, message="Transcribing with OpenAI")
        transcript = transcribe_audio_chunks(chunks, settings)
        store.update(job_id, transcript=transcript)

        store.update(
            job_id,
            status=JobStatus.ANALYZING,
            progress=65,
            message="Finding the strongest moments",
        )
        moments = select_key_moments(
            transcript=transcript.segments,
            video_duration=video_info.duration,
            clip_count=record.request.clip_count,
            target_duration=record.request.target_duration,
            settings=settings,
        )

        store.update(
            job_id,
            status=JobStatus.RENDERING,
            progress=78,
            message="Rendering clips",
        )
        clips = render_clips(video_path, moments, work_dir, settings)
        store.update(
            job_id,
            status=JobStatus.COMPLETE,
            progress=100,
            message=f"Created {len(clips)} clips",
            clips=clips,
        )

        shutil.rmtree(work_dir / "audio", ignore_errors=True)
    except PipelineError as exc:
        logger.warning("Job %s failed: %s", job_id, exc)
        store.update(
            job_id,
            status=JobStatus.FAILED,
            message="Processing failed",
            error=str(exc),
        )
    except Exception:
        logger.exception("Unexpected failure in job %s", job_id)
        store.update(
            job_id,
            status=JobStatus.FAILED,
            message="Processing failed",
            error="An unexpected processing error occurred",
        )


def rerender_clip(
    job_id: str,
    filename: str,
    edit: ClipEditSettings,
    store: JobStore,
    settings: Settings,
) -> None:
    temporary: Path | None = None
    try:
        record = store.get(job_id)
        source = store.source_video(job_id)
        if record is None or source is None:
            raise PipelineError("The source video is no longer available")

        clip = next((item for item in record.clips if item.filename == filename), None)
        if clip is None:
            raise PipelineError("Clip not found")

        clips_dir = store.directory(job_id) / "clips"
        destination = clips_dir / filename
        temporary = clips_dir / f".{destination.stem}.rendering.mp4"
        words = record.transcript.words if record.transcript else []
        render_edited_clip(
            video_path=source,
            destination=temporary,
            edit=edit,
            words=words,
            work_dir=store.directory(job_id),
            settings=settings,
        )
        temporary.replace(destination)
        store.update_clip(
            job_id,
            filename,
            edit_settings=edit,
            render_status=ClipRenderStatus.READY,
            render_error=None,
            version=clip.version + 1,
        )
    except PipelineError as exc:
        logger.warning("Edited clip render failed for %s/%s: %s", job_id, filename, exc)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        store.update_clip(
            job_id,
            filename,
            render_status=ClipRenderStatus.FAILED,
            render_error=str(exc),
        )
    except Exception:
        logger.exception("Unexpected edited clip render failure for %s/%s", job_id, filename)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        store.update_clip(
            job_id,
            filename,
            render_status=ClipRenderStatus.FAILED,
            render_error="An unexpected render error occurred",
        )
