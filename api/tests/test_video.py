from pathlib import Path

from app.config import Settings
from app.models import (
    AspectRatio,
    CaptionStyle,
    ClipEditSettings,
    TranscriptWord,
    ZoomPreset,
)
from app.services import video
from app.services.framing import Box, FramingPlan, Layout, MediaInfo, Shot


def test_builds_readable_caption_groups() -> None:
    words = [
        TranscriptWord(start=10, end=10.3, word="A"),
        TranscriptWord(start=10.35, end=10.7, word="complete"),
        TranscriptWord(start=10.75, end=11.1, word="thought."),
        TranscriptWord(start=12, end=12.3, word="Next"),
    ]

    cues = video.build_caption_cues(words, clip_start=10, clip_end=15)

    assert [(cue.start, cue.end, cue.text) for cue in cues] == [
        (0.0, 1.18, "A complete thought."),
        (2.0, 2.38, "Next"),
    ]


def _plan(*shots: Shot) -> FramingPlan:
    return FramingPlan(width=1920, height=1080, shots=list(shots))


def test_talking_head_crop_follows_the_focus_path() -> None:
    shot = Shot(10, 20, Layout.TALKING_HEAD, focus=[(10, 0.3, 0.4), (20, 0.7, 0.4)])

    width, height, x_expr, y_expr = video.fill_crop(shot, 1920, 1080, 1080, 1920, origin=10)

    assert (width, height) == (606, 1080)
    assert x_expr.startswith("if(lt(t,10.000),273.0+")
    assert y_expr == "0"


def test_builds_framed_graph_with_cuts_speed_captions_and_fades(tmp_path: Path) -> None:
    edit = ClipEditSettings(
        trim_start=10,
        trim_end=30,
        aspect_ratio=AspectRatio.PORTRAIT,
        caption_style=CaptionStyle.POP,
        fade_in=0.5,
        fade_out=1,
        zoom=ZoomPreset.LIGHT,
        speed=1.25,
    )
    plan = _plan(
        Shot(10, 18, Layout.TALKING_HEAD, focus=[(10, 0.5, 0.4), (18, 0.5, 0.4)]),
        Shot(
            18,
            30,
            Layout.TWO_SHOT,
            people=[Box(0.2, 0.2, 0.1, 0.2), Box(0.7, 0.2, 0.1, 0.2)],
        ),
    )
    keeps = [(0.0, 5.0), (6.0, 20.0)]

    graph = video.build_render_graph(
        edit, plan, keeps, (1080, 1920), True, subtitle_path=tmp_path / "captions.ass"
    )

    assert graph.duration == 19 / 1.25
    assert "trim=start=0.0000:end=5.0000" in graph.filter_complex
    assert "trim=start=6.0000:end=8.0000" in graph.filter_complex
    assert "vstack=inputs=2" in graph.filter_complex
    assert "concat=n=3:v=1:a=0" in graph.filter_complex
    assert "concat=n=2:v=0:a=1" in graph.filter_complex
    assert "setpts=PTS/1.25" in graph.filter_complex
    assert "atempo=1.25" in graph.filter_complex
    assert "crop=iw/1.08:ih/1.08" in graph.filter_complex
    assert "subtitles=filename=" in graph.filter_complex
    assert "fontsdir=" in graph.filter_complex
    assert "fade=t=out:st=14.200:d=1.000" in graph.filter_complex
    assert graph.filter_complex.endswith("[aout]")


def test_caption_position_tracks_layout() -> None:
    assert video.caption_y(Layout.TALKING_HEAD, 1920, 1080, 1080, 1920) == 1344
    assert video.caption_y(Layout.TWO_SHOT, 1920, 1080, 1080, 1920) == 960
    assert video.caption_y(Layout.SCREEN, 1920, 1080, 1080, 1920) > 1240


def test_render_seeks_source_and_reports_removed_dead_air(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.touch()
    destination = tmp_path / "edited.mp4"
    commands: list[list[str]] = []

    def fake_run(command: list[str], _: int) -> None:
        commands.append(command)
        Path(command[-1]).touch()

    monkeypatch.setattr(video, "_run", fake_run)
    monkeypatch.setattr(
        video, "probe_media", lambda *_args, **_kwargs: MediaInfo(1920, 1080, 60, True)
    )
    monkeypatch.setattr(
        video,
        "analyze_framing",
        lambda _path, start, end, *_args, **_kwargs: _plan(
            Shot(start, end, Layout.TALKING_HEAD, focus=[(start, 0.5, 0.4)])
        ),
    )
    edit = ClipEditSettings(
        trim_start=4,
        trim_end=12,
        aspect_ratio=AspectRatio.PORTRAIT,
        captions=False,
        fade_in=0,
        fade_out=0,
        remove_dead_air=True,
    )
    words = [
        TranscriptWord(start=4.1, end=4.5, word="First"),
        TranscriptWord(start=4.6, end=5.0, word="point."),
        TranscriptWord(start=8.0, end=8.4, word="Second"),
        TranscriptWord(start=8.5, end=9.0, word="point."),
    ]

    report = video.render_edited_clip(
        video_path=source,
        destination=destination,
        edit=edit,
        words=words,
        work_dir=tmp_path,
        settings=Settings(openai_api_key="test"),
    )

    assert destination.exists()
    assert commands[0][commands[0].index("-ss") + 1] == "4.000"
    assert commands[0][commands[0].index("-t") + 1] == "8.000"
    assert report.removed_seconds > 4
    assert report.layouts == [Layout.TALKING_HEAD]
