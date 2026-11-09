"""Tight pacing: cut dead air and hesitation sounds the way a short-form editor would.

Times are seconds from the start of the clip window. The result is a list of
keep intervals, plus a ``TimeMap`` that converts window time to output time so
captions stay in sync after the cuts.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.models import TranscriptWord

# Only pure hesitation sounds: words like "like" or "so" often carry meaning.
FILLER_WORDS = frozenset({"um", "uh", "uhm", "umm", "uhh", "erm", "er", "hmm", "hm", "mm", "mhm"})

FRAME = 1 / 30
# How much of a removed pause survives, split across both sides of the cut, so
# speech keeps a natural breath instead of machine-gun jump cuts.
KEEP_PAUSE = 0.26
LEAD_IN = 0.12
TAIL = 0.38
MIN_CUT = 0.2
MIN_PIECE = 0.4


def is_filler(word: str) -> bool:
    return re.sub(r"[^a-z]", "", word.lower()) in FILLER_WORDS


def snap(t: float) -> float:
    return round(round(t / FRAME) * FRAME, 6)


def compute_keep_intervals(
    words: list[TranscriptWord],
    duration: float,
    pause_limit: Callable[[float, float], float | None] = lambda _start, _end: 0.7,
) -> list[tuple[float, float]]:
    """Intervals of [0, duration) to keep.

    ``words`` are in window time. ``pause_limit(start, end)`` returns the
    longest pause allowed over that gap, or ``None`` when it must never be cut
    (for example a silent screen demo).
    """
    ordered = sorted(
        (word for word in words if word.end > 0 and word.start < duration),
        key=lambda word: word.start,
    )
    spoken = [word for word in ordered if not is_filler(word.word)]
    if not spoken:
        return [(0.0, duration)]

    cuts: list[tuple[float, float]] = []
    first, last = spoken[0], spoken[-1]
    if pause_limit(0, first.start) is not None and first.start > LEAD_IN + MIN_CUT:
        cuts.append((0.0, first.start - LEAD_IN))
    if pause_limit(last.end, duration) is not None and duration - last.end > TAIL + MIN_CUT:
        cuts.append((last.end + TAIL, duration))

    for previous, following in zip(spoken, spoken[1:], strict=False):
        fillers = [
            word
            for word in ordered
            if previous.end <= word.start and word.end <= following.start and is_filler(word.word)
        ]
        limit = pause_limit(previous.end, following.start)
        if limit is None:
            continue
        if fillers:
            limit = 0.0
        gap = following.start - previous.end
        if gap <= max(limit, KEEP_PAUSE):
            continue
        cut_start = previous.end + KEEP_PAUSE / 2
        cut_end = following.start - KEEP_PAUSE / 2
        if fillers:
            # Remove each filler in full, or a syllable survives the jump cut.
            cut_start = min(cut_start, fillers[0].start - FRAME)
            cut_end = max(cut_end, fillers[-1].end + FRAME)
        cuts.append((cut_start, cut_end))

    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for cut_start, cut_end in sorted(cuts):
        cut_start = snap(max(cut_start, cursor))
        cut_end = duration if cut_end >= duration else snap(cut_end)
        if cut_end - cut_start < MIN_CUT:
            continue
        if cut_start > cursor:
            keeps.append((cursor, cut_start))
        cursor = cut_end
    if cursor < duration:
        keeps.append((cursor, duration))

    merged: list[tuple[float, float]] = []
    for piece in keeps:
        if merged and piece[1] - piece[0] < MIN_PIECE:
            merged[-1] = (merged[-1][0], piece[1])
        else:
            merged.append(piece)
    if len(merged) > 1 and merged[0][1] - merged[0][0] < MIN_PIECE:
        merged[:2] = [(merged[0][0], merged[1][1])]
    return merged or [(0.0, duration)]


@dataclass
class TimeMap:
    keeps: list[tuple[float, float]]

    def __post_init__(self) -> None:
        self._offsets = []
        elapsed = 0.0
        for start, end in self.keeps:
            self._offsets.append(elapsed)
            elapsed += end - start
        self.duration = elapsed

    def to_output(self, t: float) -> float:
        """Output time for window time ``t``; times inside a cut land on the cut point."""
        for (start, end), offset in zip(self.keeps, self._offsets, strict=False):
            if t < start:
                return offset
            if t <= end:
                return offset + t - start
        return self.duration

    def map_words(self, words: list[TranscriptWord]) -> list[TranscriptWord]:
        """Words in output time; words that fell entirely inside a cut are dropped."""
        mapped = []
        for word in words:
            inside = any(word.start < end and word.end > start for start, end in self.keeps)
            if not inside:
                continue
            start = round(self.to_output(word.start), 3)
            end = round(self.to_output(word.end), 3)
            if end - start < 0.02:
                continue
            mapped.append(TranscriptWord(start=start, end=end, word=word.word))
        return mapped
