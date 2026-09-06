from app.jobs import JobStore
from app.models import ClipRenderStatus, ClipResult, CreateJobRequest, JobStatus


def test_job_state_is_persisted_across_transitions(tmp_path) -> None:
    store = JobStore(tmp_path)
    request = CreateJobRequest(
        url="https://www.youtube.com/watch?v=test",
        clip_count=3,
        target_duration=45,
    )

    created = store.create(request)
    assert created.status == JobStatus.QUEUED

    store.update(
        created.id,
        status=JobStatus.TRANSCRIBING,
        progress=40,
        message="Transcribing",
    )
    clip = ClipResult(
        title="A key idea",
        reason="It stands alone",
        start=10,
        end=55,
        filename="clip-01.mp4",
    )
    store.update(
        created.id,
        status=JobStatus.COMPLETE,
        progress=100,
        message="Done",
        clips=[clip],
    )

    loaded = store.get(created.id)
    assert loaded is not None
    assert loaded.status == JobStatus.COMPLETE
    assert loaded.progress == 100
    assert loaded.clips[0].filename == "clip-01.mp4"
    assert store.get("../../etc/passwd") is None

    work_dir = store.directory(created.id)
    work_dir.mkdir()
    source = work_dir / "source.mp4"
    source.touch()
    assert store.source_video(created.id) == source

    store.update_clip(
        created.id,
        "clip-01.mp4",
        render_status=ClipRenderStatus.RENDERING,
    )
    rendering = store.get(created.id)
    assert rendering is not None
    assert rendering.clips[0].render_status == ClipRenderStatus.RENDERING
