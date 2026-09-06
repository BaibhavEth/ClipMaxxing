import re

from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.models import Moment, TranscriptSegment
from app.services.errors import PipelineError


class MomentSelection(BaseModel):
    moments: list[Moment] = Field(min_length=1, max_length=10)


SENTENCE_END = re.compile(r"""[.!?…]["'’”)\]]*$""")


def _ends_thought(text: str) -> bool:
    return bool(SENTENCE_END.search(text.strip()))


def _align_to_transcript(
    start: float,
    end: float,
    transcript: list[TranscriptSegment],
    target_duration: int,
    video_duration: float,
) -> tuple[float, float]:
    segments = sorted(transcript, key=lambda segment: segment.start)
    if not segments:
        return start, end

    start_index = next(
        (index for index, segment in enumerate(segments) if segment.end >= start),
        len(segments) - 1,
    )
    end_index = next(
        (index for index, segment in enumerate(segments) if segment.end >= end),
        len(segments) - 1,
    )

    # Walk back to the beginning of the sentence containing the suggested start.
    original_start = start
    while start_index > 0:
        previous = segments[start_index - 1]
        current = segments[start_index]
        gap = current.start - previous.end
        if _ends_thought(previous.text) or gap >= 0.8:
            break
        if original_start - previous.start > 15:
            break
        start_index -= 1

    aligned_start = max(0.0, segments[start_index].start - 0.35)
    extension_budget = max(20.0, min(float(target_duration), 60.0))
    maximum_duration = min(float(target_duration) + extension_budget, 240.0)

    # Finish the current sentence, allowing a bounded amount of extra clip time.
    while end_index < len(segments) - 1:
        current = segments[end_index]
        next_segment = segments[end_index + 1]
        at_natural_end = _ends_thought(current.text) or next_segment.start - current.end >= 0.8
        if at_natural_end:
            break
        if next_segment.end - aligned_start > maximum_duration:
            break
        end_index += 1

    aligned_end = min(video_duration, segments[end_index].end + 0.65)
    if aligned_end <= aligned_start:
        return start, end
    return aligned_start, aligned_end


def normalize_moments(
    candidates: list[Moment],
    video_duration: float,
    target_duration: int,
    clip_count: int,
    transcript: list[TranscriptSegment] | None = None,
) -> list[Moment]:
    if video_duration <= 0:
        return []

    selected: list[Moment] = []

    for candidate in candidates:
        raw_start = max(0.0, min(candidate.start, video_duration))
        raw_end = max(0.0, min(candidate.end, video_duration))
        if raw_end <= raw_start:
            continue

        start, end = raw_start, raw_end
        if transcript:
            start, end = _align_to_transcript(
                start,
                end,
                transcript=transcript,
                target_duration=target_duration,
                video_duration=video_duration,
            )

        overlaps = any(
            max(start, existing.start) < min(end, existing.end) for existing in selected
        )
        if overlaps:
            continue

        selected.append(
            Moment(
                title=candidate.title.strip() or "Key moment",
                reason=candidate.reason.strip() or "A strong standalone moment",
                start=round(start, 3),
                end=round(end, 3),
            )
        )
        if len(selected) == clip_count:
            break

    return sorted(selected, key=lambda moment: moment.start)


def select_key_moments(
    transcript: list[TranscriptSegment],
    video_duration: float,
    clip_count: int,
    target_duration: int,
    settings: Settings,
) -> list[Moment]:
    if not settings.openai_api_key:
        raise PipelineError("OPENAI_API_KEY is not configured")

    transcript_text = "\n".join(
        f"[{segment.start:.1f}-{segment.end:.1f}] {segment.text}" for segment in transcript
    )
    requested_candidates = min(10, clip_count + 2)
    instructions = (
        "You are an expert short-form video editor. Select self-contained, compelling "
        "moments from the timestamped transcript. Favor strong insights, surprising claims, "
        "clear stories, useful explanations, or emotional peaks. Avoid intros, sponsor reads, "
        "outros, repetition, and moments that require missing context. Return candidates in "
        "best-first order, with non-overlapping timestamps. Every start must be at the beginning "
        "of a complete sentence or thought, and every end must come after the speaker finishes "
        "the idea. Duration is flexible: never cut a sentence just to hit the requested length. "
        "Titles must be concise and reasons must explain why the moment works standalone."
    )
    prompt = (
        f"Video duration: {video_duration:.1f} seconds.\n"
        f"Return {requested_candidates} candidates near {target_duration} seconds each. "
        "All timestamps must stay within the video.\n\n"
        f"TRANSCRIPT\n{transcript_text}"
    )

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.parse(
            model=settings.openai_moment_model,
            instructions=instructions,
            input=prompt,
            text_format=MomentSelection,
        )
        parsed = response.output_parsed
    except Exception as exc:
        raise PipelineError("OpenAI could not identify key moments") from exc

    if not parsed:
        raise PipelineError("OpenAI returned no key moments")

    moments = normalize_moments(
        parsed.moments,
        video_duration=video_duration,
        target_duration=target_duration,
        clip_count=clip_count,
        transcript=transcript,
    )
    if not moments:
        raise PipelineError("No valid clip ranges were found")
    return moments
