import subprocess
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.config import Settings
from app.models import TranscriptData, TranscriptSegment, TranscriptWord
from app.services.errors import PipelineError


def merge_chunk_segments(
    segments_by_chunk: list[list[TranscriptSegment]],
    chunk_seconds: int,
    chunk_offsets: list[float] | None = None,
) -> list[TranscriptSegment]:
    merged: list[TranscriptSegment] = []
    for chunk_index, segments in enumerate(segments_by_chunk):
        offset = (
            chunk_offsets[chunk_index]
            if chunk_offsets is not None
            else chunk_index * chunk_seconds
        )
        for segment in segments:
            text = segment.text.strip()
            if text:
                merged.append(
                    TranscriptSegment(
                        start=segment.start + offset,
                        end=segment.end + offset,
                        text=text,
                    )
                )
    return merged


def merge_chunk_words(
    words_by_chunk: list[list[TranscriptWord]],
    chunk_seconds: int,
    chunk_offsets: list[float] | None = None,
) -> list[TranscriptWord]:
    merged: list[TranscriptWord] = []
    for chunk_index, words in enumerate(words_by_chunk):
        offset = (
            chunk_offsets[chunk_index]
            if chunk_offsets is not None
            else chunk_index * chunk_seconds
        )
        for word in words:
            text = word.word.strip()
            if text:
                merged.append(
                    TranscriptWord(
                        start=word.start + offset,
                        end=word.end + offset,
                        word=text,
                    )
                )
    return merged


def _segment_value(segment: Any, name: str) -> Any:
    if isinstance(segment, dict):
        return segment.get(name)
    return getattr(segment, name, None)


def measure_chunk_offsets(
    chunk_paths: list[Path],
    fallback_seconds: int,
    timeout: int,
) -> list[float]:
    offsets: list[float] = []
    elapsed = 0.0
    for chunk_path in chunk_paths:
        offsets.append(elapsed)
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(chunk_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=min(timeout, 30),
            )
            duration = float(result.stdout.strip())
            elapsed += duration if duration > 0 else fallback_seconds
        except (FileNotFoundError, ValueError, subprocess.SubprocessError):
            elapsed += fallback_seconds
    return offsets


def transcribe_audio_chunks(
    chunk_paths: list[Path],
    settings: Settings,
) -> TranscriptData:
    if not settings.openai_api_key:
        raise PipelineError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=settings.openai_api_key)
    all_chunks: list[list[TranscriptSegment]] = []
    all_word_chunks: list[list[TranscriptWord]] = []
    chunk_offsets = measure_chunk_offsets(
        chunk_paths,
        fallback_seconds=settings.audio_chunk_seconds,
        timeout=settings.process_timeout_seconds,
    )

    for chunk_path in chunk_paths:
        try:
            with chunk_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    file=audio_file,
                    model=settings.openai_transcription_model,
                    response_format="verbose_json",
                    timestamp_granularities=["segment", "word"],
                )
        except Exception as exc:
            raise PipelineError("OpenAI could not transcribe the video audio") from exc

        parsed: list[TranscriptSegment] = []
        for item in getattr(response, "segments", None) or []:
            start = _segment_value(item, "start")
            end = _segment_value(item, "end")
            text = _segment_value(item, "text")
            if start is None or end is None or not text or float(end) <= float(start):
                continue
            parsed.append(
                TranscriptSegment(start=float(start), end=float(end), text=str(text))
            )
        all_chunks.append(parsed)

        parsed_words: list[TranscriptWord] = []
        for item in getattr(response, "words", None) or []:
            start = _segment_value(item, "start")
            end = _segment_value(item, "end")
            word = _segment_value(item, "word")
            if start is None or end is None or not word or float(end) <= float(start):
                continue
            parsed_words.append(
                TranscriptWord(start=float(start), end=float(end), word=str(word))
            )
        all_word_chunks.append(parsed_words)

    merged_segments = merge_chunk_segments(
        all_chunks,
        settings.audio_chunk_seconds,
        chunk_offsets=chunk_offsets,
    )
    merged_words = merge_chunk_words(
        all_word_chunks,
        settings.audio_chunk_seconds,
        chunk_offsets=chunk_offsets,
    )
    if not merged_segments:
        raise PipelineError("OpenAI returned an empty transcript")
    return TranscriptData(segments=merged_segments, words=merged_words)
