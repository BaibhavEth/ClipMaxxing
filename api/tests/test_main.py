from fastapi.testclient import TestClient

from app import main
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
from app.services.social import SocialPosts, serialize_social_posts


def test_local_frontend_preflight_is_allowed() -> None:
    client = TestClient(main.app)
    for origin in ("http://127.0.0.1:3000", "http://localhost:3001"):
        response = client.options(
            "/api/jobs",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_starts_clip_render_and_returns_versioned_media(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "store", store)
    record = store.create(
        CreateJobRequest(
            url="https://youtu.be/example",
            clip_count=3,
            target_duration=45,
        )
    )
    clip = ClipResult(
        title="Key idea",
        reason="It stands alone",
        start=10,
        end=55,
        filename="clip-01.mp4",
    )
    store.update(
        record.id,
        status=JobStatus.COMPLETE,
        progress=100,
        clips=[clip],
        transcript=TranscriptData(words=[TranscriptWord(start=20, end=20.5, word="Hello")]),
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
    assert payload["media_url"].endswith("/clips/clip-01.mp4?v=1")
    assert client.get(payload["media_url"]).status_code == 200

    social_posts = SocialPosts(
        quote="Gold changed the economics of retail…\n\n“Hello”",
        story="Brian built Coinbase at night\n\nhe never used the work laptop\n\nworth it",
        breakdown="Brian built Coinbase at night\n\n18 months of Sundays\n\nWould you?",
    )
    monkeypatch.setattr(main, "generate_social_post", lambda **_: social_posts)
    monkeypatch.setattr(main.settings, "openai_api_key", "sk-test")
    social_response = client.post(f"/api/jobs/{record.id}/clips/{clip.filename}/social-post")
    assert social_response.status_code == 200
    assert social_response.json() == {
        "text": social_posts.quote,
        "story_text": social_posts.story,
        "breakdown_text": social_posts.breakdown,
    }
    saved = store.get(record.id)
    assert saved is not None
    assert saved.clips[0].social_post == serialize_social_posts(social_posts)


def test_creates_job_and_lists_it_in_history(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(main, "run_job", lambda *_: None)
    client = TestClient(main.app)

    response = client.post(
        "/api/jobs",
        json={"url": "https://youtu.be/example", "clip_count": 3, "target_duration": 45},
    )

    assert response.status_code == 202
    projects = client.get("/api/projects").json()["projects"]
    assert [project["id"] for project in projects] == [response.json()["id"]]
    assert projects[0]["clip_count"] == 3


def test_upload_creates_a_job_with_render_options(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(main, "run_job", lambda *_: None)
    client = TestClient(main.app)

    response = client.post(
        "/api/uploads",
        files={"file": ("My Podcast.mov", b"fake video bytes", "video/quicktime")},
        data={
            "clip_count": "4",
            "target_duration": "60",
            "render": '{"caption_style": "impact", "speed": 1.25}',
        },
    )

    assert response.status_code == 202
    record = store.get(response.json()["id"])
    assert record is not None
    assert record.request.source_kind == "upload"
    assert record.request.render.caption_style == "impact"
    assert record.request.render.speed == 1.25
    assert store.source_video(record.id).name == "source.mov"
    projects = client.get("/api/projects").json()["projects"]
    assert projects[0]["source_url"] == "My Podcast.mov"


def test_upload_rejects_unsupported_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(main.settings, "openai_api_key", "sk-test")

    response = TestClient(main.app).post(
        "/api/uploads", files={"file": ("notes.txt", b"hello", "text/plain")}
    )

    assert response.status_code == 422


def test_accepts_twitch_vods(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(main, "run_job", lambda *_: None)

    response = TestClient(main.app).post(
        "/api/jobs", json={"url": "https://www.twitch.tv/videos/123456789"}
    )

    assert response.status_code == 202
    assert store.get(response.json()["id"]).request.source_kind == "twitch"


def test_editor_can_extend_cuts_into_the_preview_window(monkeypatch, tmp_path) -> None:
    store = JobStore(tmp_path)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "rerender_clip", lambda *_: None)
    record = store.create(CreateJobRequest(url="https://youtu.be/example"))
    clip = ClipResult(
        title="Key idea",
        reason="It stands alone",
        start=20,
        end=50,
        filename="clip-01.mp4",
        preview_filename="preview-01.mp4",
        preview_start=10,
    )
    store.update(
        record.id,
        status=JobStatus.COMPLETE,
        clips=[clip],
        video=VideoInfo(title="Talk", duration=100, source_url="https://youtu.be/example"),
    )
    work_dir = store.directory(record.id)
    (work_dir / "previews").mkdir(parents=True)
    (work_dir / "source.mp4").touch()
    (work_dir / "previews" / "preview-01.mp4").touch()
    client = TestClient(main.app)

    def render(start: float, end: float) -> int:
        return client.post(
            f"/api/jobs/{record.id}/clips/{clip.filename}/render",
            json={"settings": {"trim_start": start, "trim_end": end, "captions": False}},
        ).status_code

    assert render(12, 58) == 202
    store.update_clip(record.id, clip.filename, render_status=ClipRenderStatus.READY)
    assert render(5, 58) == 422
    payload = client.get(f"/api/jobs/{record.id}").json()["clips"][0]
    assert payload["preview_url"].endswith("/previews/preview-01.mp4")
    assert client.get(payload["preview_url"]).status_code == 200


def test_create_job_requires_server_openai_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(main, "store", JobStore(tmp_path))
    monkeypatch.setattr(main.settings, "openai_api_key", "")

    response = TestClient(main.app).post(
        "/api/jobs",
        json={"url": "https://youtu.be/example", "clip_count": 3, "target_duration": 45},
    )

    assert response.status_code == 409
    assert "OPENAI_API_KEY" in response.json()["detail"]
