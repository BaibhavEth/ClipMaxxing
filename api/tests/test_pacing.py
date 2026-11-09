from app.models import TranscriptWord
from app.services.pacing import TimeMap, compute_keep_intervals


def word(start: float, end: float, text: str) -> TranscriptWord:
    return TranscriptWord(start=start, end=end, word=text)


def test_cuts_long_pauses_but_keeps_a_breath() -> None:
    words = [word(0.1, 0.5, "First"), word(0.6, 1.0, "idea."), word(3.0, 3.4, "Next")]

    keeps = compute_keep_intervals(words, 4.0)

    assert len(keeps) == 2
    assert keeps[0][1] > 1.0
    assert keeps[1][0] < 3.0
    assert keeps[1][1] - keeps[1][0] < 1.2


def test_short_pauses_are_left_alone() -> None:
    words = [word(0.1, 0.5, "Quick"), word(0.9, 1.3, "pause"), word(1.5, 2.0, "here.")]

    assert compute_keep_intervals(words, 2.2) == [(0.0, 2.2)]


def test_filler_words_are_removed_in_full() -> None:
    words = [word(0.1, 0.5, "So"), word(0.6, 1.0, "um,"), word(1.1, 1.5, "right")]

    keeps = compute_keep_intervals(words, 1.7)

    assert all(not (start < 1.0 and end > 0.6) for start, end in keeps)


def test_never_cuts_where_the_layout_forbids_it() -> None:
    words = [word(0.1, 0.5, "Watch"), word(5.0, 5.4, "this")]

    assert compute_keep_intervals(words, 5.6, lambda _s, _e: None) == [(0.0, 5.6)]


def test_time_map_shifts_words_after_cuts() -> None:
    mapped = TimeMap([(0.0, 1.0), (3.0, 4.0)]).map_words(
        [word(0.2, 0.6, "kept"), word(1.5, 2.0, "cut"), word(3.2, 3.6, "after")]
    )

    assert [(item.word, item.start) for item in mapped] == [("kept", 0.2), ("after", 1.2)]
