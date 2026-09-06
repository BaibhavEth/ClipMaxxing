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


def test_builds_crop_zoom_caption_and_fade_filters(tmp_path: Path) -> None:
    edit = ClipEditSettings(
        trim_start=10,
        trim_end=30,
        aspect_ratio=AspectRatio.PORTRAIT,
        captions=True,
        caption_style=CaptionStyle.BOLD,
        fade_in=0.5,
        fade_out=1,
        zoom=ZoomPreset.LIGHT,
    )

    video_filters, audio_filters = video.build_filter_graph(
        edit,
        duration=20,
        subtitle_path=tmp_path / "captions.ass",
    )

    assert video_filters[0] == "crop=iw/1.08:ih/1.08"
    assert "crop=1080:1920" in video_filters
    assert any(item.startswith("subtitles=") for item in video_filters)
    assert "fade=t=out:st=19.000:d=1.000" in video_filters
    assert audio_filters == [
        "afade=t=in:st=0:d=0.500",
        "afade=t=out:st=19.000:d=1.000",
    ]


def test_render_uses_temp_output_command(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.touch()
    destination = tmp_path / "edited.mp4"
    commands: list[list[str]] = []

    def fake_run(command: list[str], _: int) -> None:
        commands.append(command)
        Path(command[-1]).touch()

    monkeypatch.setattr(video, "_run", fake_run)
    edit = ClipEditSettings(
        trim_start=4,
        trim_end=12,
        captions=False,
        fade_in=0,
        fade_out=0,
    )

    video.render_edited_clip(
        video_path=source,
        destination=destination,
        edit=edit,
        words=[],
        work_dir=tmp_path,
        settings=Settings(openai_api_key="test"),
    )

    assert destination.exists()
    assert commands[0][commands[0].index("-ss") + 1] == "4.000"
    assert commands[0][commands[0].index("-t") + 1] == "8.000"
