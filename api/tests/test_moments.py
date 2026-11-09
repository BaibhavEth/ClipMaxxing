from app.models import Moment, TranscriptSegment
from app.services.moments import (
    MomentCandidate,
    MomentKind,
    normalize_moments,
    rank_candidates,
)


def candidate(title: str, start: float, end: float) -> Moment:
    return Moment(title=title, reason="Strong standalone idea", start=start, end=end)


def scored(
    title: str,
    start: float,
    *,
    kind: MomentKind = MomentKind.STORY,
    hook: int = 7,
    payoff: int = 7,
    standalone: int = 7,
    share: int = 7,
) -> MomentCandidate:
    return MomentCandidate(
        title=title,
        reason="Why it works",
        start=start,
        end=start + 30,
        hook_line="Opening line",
        payoff="The payoff",
        kind=kind,
        hook_score=hook,
        payoff_score=payoff,
        standalone_score=standalone,
        shareability_score=share,
    )


def test_ranks_strongest_hooks_first_and_drops_weak_clips() -> None:
    ranked = rank_candidates(
        [
            scored("Average", 0, hook=6, payoff=6, standalone=7, share=6),
            scored("Gold", 100, hook=10, payoff=9, standalone=9, share=9),
            scored("Needs context", 200, hook=9, payoff=9, standalone=3, share=9),
            scored("Filler", 300, hook=3, payoff=3, standalone=7, share=3),
        ]
    )

    assert [moment.title for moment in ranked] == ["Gold", "Average"]


def test_prefers_variety_when_scores_are_close() -> None:
    ranked = rank_candidates(
        [
            scored("Story one", 0, kind=MomentKind.STORY, hook=9),
            scored("Story two", 100, kind=MomentKind.STORY, hook=9),
            scored("Numbers", 200, kind=MomentKind.NUMBERS, hook=8),
        ]
    )

    assert [moment.title for moment in ranked][:2] == ["Story one", "Numbers"]


def test_keeps_best_few_when_nothing_clears_the_bar() -> None:
    ranked = rank_candidates(
        [
            scored("Weak", 0, hook=4, payoff=4, standalone=5, share=4),
            scored("Weaker", 100, hook=3, payoff=3, standalone=4, share=3),
        ]
    )

    assert [moment.title for moment in ranked] == ["Weak", "Weaker"]


def test_preserves_suggested_ranges_within_video_bounds() -> None:
    moments = normalize_moments(
        [
            candidate("Later", 90, 105),
            candidate("Opening", 2, 12),
            candidate("Finale", 190, 210),
        ],
        video_duration=200,
        target_duration=30,
        clip_count=3,
    )

    assert [(moment.start, moment.end) for moment in moments] == [
        (2.0, 12.0),
        (90.0, 105.0),
        (190.0, 200.0),
    ]


def test_skips_overlapping_candidates_and_respects_limit() -> None:
    moments = normalize_moments(
        [
            candidate("Best", 10, 30),
            candidate("Duplicate", 15, 35),
            candidate("Another", 70, 90),
        ],
        video_duration=120,
        target_duration=30,
        clip_count=2,
    )

    assert [moment.title for moment in moments] == ["Best", "Another"]


def test_extends_clip_until_transcript_reaches_complete_thought() -> None:
    transcript = [
        TranscriptSegment(start=0, end=4, text="Here is the setup."),
        TranscriptSegment(start=4.2, end=8, text="The main idea starts here"),
        TranscriptSegment(start=8.1, end=12, text="and continues with useful evidence"),
        TranscriptSegment(start=12.1, end=16, text="before completing the thought."),
        TranscriptSegment(start=18, end=22, text="A new topic begins."),
    ]

    moments = normalize_moments(
        [candidate("Complete idea", 6, 10)],
        video_duration=30,
        target_duration=15,
        clip_count=1,
        transcript=transcript,
    )

    assert moments[0].start == 3.85
    assert moments[0].end == 16.65


def test_stops_at_pause_even_without_terminal_punctuation() -> None:
    transcript = [
        TranscriptSegment(start=10, end=14, text="A concise observation"),
        TranscriptSegment(start=14.1, end=18, text="with a natural conclusion"),
        TranscriptSegment(start=20, end=24, text="A different subject."),
    ]

    moments = normalize_moments(
        [candidate("Natural pause", 11, 15)],
        video_duration=30,
        target_duration=15,
        clip_count=1,
        transcript=transcript,
    )

    assert moments[0].start == 9.65
    assert moments[0].end == 18.65


def test_snaps_cuts_to_word_boundaries() -> None:
    from app.models import TranscriptWord
    from app.services.moments import snap_to_words

    words = [
        TranscriptWord(start=9.0, end=9.4, word="before"),
        TranscriptWord(start=10.2, end=10.6, word="Start"),
        TranscriptWord(start=19.0, end=19.5, word="end."),
        TranscriptWord(start=19.6, end=20.0, word="after"),
    ]

    assert snap_to_words(10.0, 19.55, words) == (10.08, 19.6)


def test_editorial_review_fixes_cuts_and_reranks() -> None:
    from app.services.moments import ClipReview, ReviewVerdict, apply_reviews

    moments = [candidate("A", 0, 30), candidate("B", 100, 130), candidate("C", 200, 230)]
    reviews = [
        ClipReview(clip=1, verdict=ReviewVerdict.REJECT, start=0, end=30, title="A", score=4,
                   note="Needs context"),
        ClipReview(clip=2, verdict=ReviewVerdict.FIX, start=95, end=128, title="Better B",
                   score=9, note="Include the setup"),
        ClipReview(clip=3, verdict=ReviewVerdict.KEEP, start=200, end=230, title="C", score=7,
                   note="Good"),
    ]

    reviewed = apply_reviews(moments, reviews, clip_count=1)

    assert [(moment.title, moment.start, moment.end) for moment in reviewed] == [
        ("Better B", 95, 128),
        ("C", 200, 230),
        ("A", 0, 30),
    ]
