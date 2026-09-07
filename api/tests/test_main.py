from fastapi.testclient import TestClient

from app import main
from app.auth import CurrentUser, get_current_user
from app.jobs import JobStore
from app.models import (
    ClipRenderStatus,
    ClipResult,
    CreateJobRequest,
    JobStatus,
    TranscriptData,
    TranscriptWord,
    VideoInfo,
)


def test_local_frontend_preflight_is_allowed() -> None:
    client = TestClient(main.app)
    response = client.options(
        "/api/jobs",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"

    other_port = client.options(
        "/api/account/openai-key",
        headers={
            "Origin": "http://127.0.0.1:3001",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert other_port.status_code == 200
    assert other_port.headers["access-control-allow-origin"] == "http://127.0.0.1:3001"


def test_starts_clip_render_and_returns_versioned_media(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "store", store)
    user = CurrentUser(id="00000000-0000-0000-0000-000000000001", email=None, access_token="token")
    main.app.dependency_overrides[get_current_user] = lambda: user
    record = store.create(
        CreateJobRequest(
            url="https://youtu.be/example",
            clip_count=3,
            target_duration=45,
        ),
        user_id=user.id,
    )
    clip = ClipResult(
        title="Key idea",
        reason="It stands alone",
        start=10,
        end=55,
        filename="clip-01.mp4",
    )
    transcript = TranscriptData(
        words=[TranscriptWord(start=20, end=20.5, word="Hello")]
    )
    store.update(
        record.id,
        status=JobStatus.COMPLETE,
        progress=100,
        clips=[clip],
        transcript=transcript,
        video=VideoInfo(
            title="Gold interview",
            duration=120,
            source_url="https://youtu.be/example",
        ),
    )
    work_dir = store.directory(record.id)
    work_dir.mkdir(parents=True)
    (work_dir / "source.mp4").touch()
    (work_dir / "clips").mkdir()
    (work_dir / "clips" / clip.filename).touch()

    def fake_render(job_id, filename, edit, target_store, *_) -> None:
        target_store.update_clip(
            job_id,
            filename,
            edit_settings=edit,
            render_status=ClipRenderStatus.READY,
            version=1,
        )

    monkeypatch.setattr(main, "rerender_clip", fake_render)
    client = TestClient(main.app)
    response = client.post(
        f"/api/jobs/{record.id}/clips/{clip.filename}/render",
        json={
            "settings": {
                "trim_start": 12,
                "trim_end": 50,
                "aspect_ratio": "9:16",
                "captions": True,
                "caption_style": "clean",
                "fade_in": 0.25,
                "fade_out": 0.25,
                "zoom": "light",
            }
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "rendering"
    job_response = client.get(f"/api/jobs/{record.id}")
    assert job_response.status_code == 200
    payload = job_response.json()["clips"][0]
    assert payload["editable"] is True
    assert payload["version"] == 1
    assert "?token=" in payload["media_url"]
    assert payload["media_url"].endswith("&v=1")
    assert client.get(payload["media_url"]).status_code == 200

    social_text = "Gold changed the economics of retail…\n\n“Hello”"
    monkeypatch.setattr(
        main,
        "generate_social_post",
        lambda **_: social_text,
    )
    monkeypatch.setattr(main, "_user_openai_settings", lambda _: main.settings)
    monkeypatch.setattr(main.repository, "upsert_clips", lambda *_: None)
    social_response = client.post(
        f"/api/jobs/{record.id}/clips/{clip.filename}/social-post"
    )
    assert social_response.status_code == 200
    assert social_response.json() == {"text": social_text}
    saved = store.get(record.id)
    assert saved is not None
    assert saved.clips[0].social_post == social_text

    other_user = CurrentUser(
        id="00000000-0000-0000-0000-000000000002",
        email=None,
        access_token="other-token",
    )
    main.app.dependency_overrides[get_current_user] = lambda: other_user
    assert client.get(f"/api/jobs/{record.id}").status_code == 404
    main.app.dependency_overrides.clear()


def test_created_jobs_are_owned_by_the_authenticated_user(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "store", store)
    user = CurrentUser(
        id="00000000-0000-0000-0000-000000000003",
        email="owner@example.com",
        access_token="token",
    )
    main.app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(main, "_user_openai_settings", lambda _: main.settings)
    monkeypatch.setattr(main.repository, "create_project", lambda *_: None)
    monkeypatch.setattr(main.repository, "record_event", lambda *_: None)
    monkeypatch.setattr(main, "run_job", lambda *_: None)

    response = TestClient(main.app).post(
        "/api/jobs",
        json={
            "url": "https://youtu.be/example",
            "clip_count": 3,
            "target_duration": 45,
        },
    )

    assert response.status_code == 202
    record = store.get(response.json()["id"])
    assert record is not None
    assert record.user_id == user.id
    main.app.dependency_overrides.clear()
