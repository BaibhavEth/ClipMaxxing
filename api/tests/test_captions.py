from pathlib import Path

import pytest

from app.models import CaptionStyle, TranscriptWord
from app.services.captions import FONTS_DIR, PRESETS, build_caption_cues, write_ass_captions

WORDS = [
    TranscriptWord(start=0.0, end=0.3, word="Make"),
    TranscriptWord(start=0.35, end=0.7, word="every"),
    TranscriptWord(start=0.75, end=1.1, word="word"),
    TranscriptWord(start=1.15, end=1.5, word="count."),
]


@pytest.mark.parametrize("style", list(CaptionStyle))
def test_every_preset_writes_valid_events(style: CaptionStyle, tmp_path: Path) -> None:
    preset = PRESETS[style]
    cues = build_caption_cues(WORDS, 0, 2, words_per_cue=preset.max_words)
    destination = tmp_path / "captions.ass"

    write_ass_captions(cues, destination, style, position=lambda _t: (540, 1344))

    content = destination.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content
    assert "\\pos(540,1344)" in content
    assert content.count("Dialogue:") >= len(cues)


def test_highlight_presets_emphasize_one_word_per_event(tmp_path: Path) -> None:
    cues = build_caption_cues(WORDS, 0, 2, words_per_cue=3)
    destination = tmp_path / "captions.ass"

    write_ass_captions(cues, destination, CaptionStyle.POP)

    events = [line for line in destination.read_text().splitlines() if line.startswith("Dialogue")]
    assert len(events) == 4
    assert all(event.count("\\c&H34E2FF&") == 1 for event in events)
    assert "\\t(0,90,\\fscx112\\fscy112)" in events[0]


def test_back_to_back_cues_never_overlap() -> None:
    words = [
        TranscriptWord(start=index * 0.2, end=(index + 1) * 0.2, word=f"w{index}")
        for index in range(9)
    ]

    cues = build_caption_cues(words, 0, 2, words_per_cue=3)

    assert len(cues) == 3
    assert all(cue.end <= following.start for cue, following in zip(cues, cues[1:], strict=False))


def test_bundled_fonts_cover_the_presets() -> None:
    bundled = {path.stem.split("-")[0].lower() for path in FONTS_DIR.glob("*.ttf")}
    for preset in PRESETS.values():
        compact = preset.font.replace(" ", "").lower()
        assert compact == "arial" or any(compact.startswith(stem) for stem in bundled)
