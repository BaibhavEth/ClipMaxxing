from app.models import TranscriptSegment, TranscriptWord
from app.services.transcription import merge_chunk_segments, merge_chunk_words


def test_offsets_segments_from_each_audio_chunk() -> None:
    chunks = [
        [TranscriptSegment(start=1, end=3, text=" First ")],
        [TranscriptSegment(start=2, end=5, text="Second")],
    ]

    merged = merge_chunk_segments(chunks, chunk_seconds=600)

    assert [segment.model_dump() for segment in merged] == [
        {"start": 1.0, "end": 3.0, "text": "First"},
        {"start": 602.0, "end": 605.0, "text": "Second"},
    ]


def test_offsets_words_from_each_audio_chunk() -> None:
    chunks = [
        [TranscriptWord(start=1, end=1.4, word=" First ")],
        [TranscriptWord(start=2, end=2.5, word="word")],
    ]

    merged = merge_chunk_words(chunks, chunk_seconds=600)

    assert [word.model_dump() for word in merged] == [
        {"start": 1.0, "end": 1.4, "word": "First"},
        {"start": 602.0, "end": 602.5, "word": "word"},
    ]


def test_uses_measured_offsets_to_avoid_long_video_drift() -> None:
    chunks = [
        [TranscriptWord(start=0, end=0.4, word="First")],
        [TranscriptWord(start=2, end=2.5, word="Second")],
    ]

    merged = merge_chunk_words(
        chunks,
        chunk_seconds=600,
        chunk_offsets=[0, 599.4],
    )

    assert merged[1].start == 601.4
    assert merged[1].end == 601.9
