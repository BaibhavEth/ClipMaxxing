from app.models import Moment, TranscriptSegment
from app.services.moments import normalize_moments


def candidate(title: str, start: float, end: float) -> Moment:
    return Moment(title=title, reason="Strong standalone idea", start=start, end=end)


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
