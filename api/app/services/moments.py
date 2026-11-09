import logging
import re
from enum import StrEnum

from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.models import Moment, TranscriptSegment, TranscriptWord
from app.services.errors import PipelineError

logger = logging.getLogger(__name__)


class MomentKind(StrEnum):
    STORY = "story"
    CONTRARIAN = "contrarian"
    INSIGHT = "insight"
    NUMBERS = "numbers"
    EMOTIONAL = "emotional"
    FUNNY = "funny"
    TACTICAL = "tactical"


class MomentCandidate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=300)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    hook_line: str = Field(min_length=1, max_length=300)
    payoff: str = Field(min_length=1, max_length=300)
    kind: MomentKind
    hook_score: int = Field(ge=1, le=10)
    payoff_score: int = Field(ge=1, le=10)
    standalone_score: int = Field(ge=1, le=10)
    shareability_score: int = Field(ge=1, le=10)


class MomentSelection(BaseModel):
    moments: list[MomentCandidate] = Field(min_length=1, max_length=24)


MIN_STANDALONE_SCORE = 6
MIN_TOTAL_SCORE = 6.0
REPEAT_KIND_PENALTY = 0.6


def candidate_score(candidate: MomentCandidate) -> float:
    return (
        candidate.hook_score * 0.35
        + candidate.payoff_score * 0.25
        + candidate.standalone_score * 0.2
        + candidate.shareability_score * 0.2
    )


def rank_candidates(candidates: list[MomentCandidate]) -> list[Moment]:
    viable = [
        candidate
        for candidate in candidates
        if candidate.standalone_score >= MIN_STANDALONE_SCORE
        and candidate_score(candidate) >= MIN_TOTAL_SCORE
    ]
    if not viable:
        viable = sorted(candidates, key=candidate_score, reverse=True)[:3]

    ranked: list[MomentCandidate] = []
    remaining = sorted(viable, key=candidate_score, reverse=True)
    kind_counts: dict[MomentKind, int] = {}
    while remaining:
        best = max(
            remaining,
            key=lambda item: candidate_score(item)
            - kind_counts.get(item.kind, 0) * REPEAT_KIND_PENALTY,
        )
        ranked.append(best)
        kind_counts[best.kind] = kind_counts.get(best.kind, 0) + 1
        remaining.remove(best)

    return [
        Moment(
            title=candidate.title,
            reason=candidate.reason,
            start=candidate.start,
            end=candidate.end,
            score=round(candidate_score(candidate), 1),
        )
        for candidate in ranked
    ]


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


def snap_to_words(
    start: float, end: float, words: list[TranscriptWord]
) -> tuple[float, float]:
    """Tighten a range to word timestamps without clipping the first or last word."""
    inside = [word for word in words if word.end > start and word.start < end]
    if not inside:
        return start, end
    first, last = inside[0], inside[-1]
    before = [word for word in words if word.end <= first.start]
    after = [word for word in words if word.start >= last.end]
    snapped_start = first.start - 0.12
    if before:
        snapped_start = max(snapped_start, before[-1].end)
    snapped_end = last.end + 0.3
    if after:
        snapped_end = min(snapped_end, after[0].start)
    return max(0.0, snapped_start), max(snapped_end, first.start + 0.5)


def normalize_moments(
    candidates: list[Moment],
    video_duration: float,
    target_duration: int,
    clip_count: int,
    transcript: list[TranscriptSegment] | None = None,
    words: list[TranscriptWord] | None = None,
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
        if words:
            start, end = snap_to_words(start, end, words)
            end = min(end, video_duration)

        overlaps = any(max(start, existing.start) < min(end, existing.end) for existing in selected)
        if overlaps:
            continue

        selected.append(
            Moment(
                title=candidate.title.strip() or "Key moment",
                reason=candidate.reason.strip() or "A strong standalone moment",
                start=round(start, 3),
                end=round(end, 3),
                score=candidate.score,
            )
        )
        if len(selected) == clip_count:
            break

    return sorted(selected, key=lambda moment: moment.start)


class ReviewVerdict(StrEnum):
    KEEP = "keep"
    FIX = "fix"
    REJECT = "reject"


class ClipReview(BaseModel):
    clip: int = Field(ge=1)
    verdict: ReviewVerdict
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=1, le=10)
    note: str = Field(max_length=300)


class ReviewBatch(BaseModel):
    reviews: list[ClipReview]


REVIEW_CONTEXT_SECONDS = 25


def _context_block(
    index: int, moment: Moment, transcript: list[TranscriptSegment]
) -> str:
    lines = [f"CLIP {index}: {moment.title} (currently {moment.start:.1f}-{moment.end:.1f})"]
    for segment in transcript:
        if segment.end < moment.start - REVIEW_CONTEXT_SECONDS:
            continue
        if segment.start > moment.end + REVIEW_CONTEXT_SECONDS:
            break
        inside = segment.end > moment.start and segment.start < moment.end
        marker = ">" if inside else " "
        lines.append(f"{marker} [{segment.start:.1f}-{segment.end:.1f}] {segment.text}")
    return "\n".join(lines)


def apply_reviews(
    moments: list[Moment],
    reviews: list[ClipReview],
    clip_count: int,
) -> list[Moment]:
    """Apply editorial verdicts; keep the best-scored clips, topping up from rejects."""
    by_clip = {review.clip: review for review in reviews}
    kept: list[Moment] = []
    rejected: list[Moment] = []
    for index, moment in enumerate(moments, start=1):
        review = by_clip.get(index)
        if review is None:
            kept.append(moment)
            continue
        reviewed = moment.model_copy(
            update={"title": review.title.strip() or moment.title, "score": review.score}
        )
        if review.verdict == ReviewVerdict.FIX and review.end > review.start:
            reviewed = reviewed.model_copy(update={"start": review.start, "end": review.end})
        (rejected if review.verdict == ReviewVerdict.REJECT else kept).append(reviewed)

    kept.sort(key=lambda moment: moment.score or 0, reverse=True)
    rejected.sort(key=lambda moment: moment.score or 0, reverse=True)
    return (kept + rejected)[: max(clip_count, 1) + 2]


def review_moments(
    moments: list[Moment],
    transcript: list[TranscriptSegment],
    clip_count: int,
    target_duration: int,
    settings: Settings,
) -> list[Moment]:
    """A second editor pass that checks each clip stands alone and ends on its payoff."""
    if not moments:
        return moments
    ordered = sorted(transcript, key=lambda segment: segment.start)
    blocks = "\n\n".join(
        _context_block(index, moment, ordered) for index, moment in enumerate(moments, start=1)
    )
    instructions = (
        "You are the final editor approving short-form clips cut from a long video. Lines "
        "marked '>' are inside the current cut; unmarked lines are surrounding context.\n\n"
        "For each clip decide:\n"
        "- keep: it opens on a hook, needs no earlier context, and ends right after the payoff.\n"
        "- fix: it is strong but the cut is wrong. Return a new start and end taken from the "
        "segment timestamps shown, e.g. start earlier to include the setup a viewer needs, "
        "start later to drop throat-clearing, or end earlier/later so the payoff lands last.\n"
        "- reject: it depends on context outside the clip, has no payoff, is an ad read, or "
        "is generic.\n\n"
        f"Aim for around {target_duration} seconds but never cut a thought to hit it. Give "
        "each clip a punchy title (under 60 characters, no clickbait lies) and an honest 1-10 "
        "score for how likely a stranger is to watch it to the end and share it. Return start "
        "and end for every clip, unchanged when keeping."
    )
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.parse(
            model=settings.openai_moment_model,
            instructions=instructions,
            input=blocks,
            text_format=ReviewBatch,
        )
        parsed = response.output_parsed
    except Exception:
        logger.warning("Editorial review failed; keeping first-pass clips", exc_info=True)
        return moments
    if not parsed or not parsed.reviews:
        return moments
    return apply_reviews(moments, parsed.reviews, clip_count)


def select_key_moments(
    transcript: list[TranscriptSegment],
    video_duration: float,
    clip_count: int,
    target_duration: int,
    settings: Settings,
    words: list[TranscriptWord] | None = None,
    video_title: str = "",
    review: bool = True,
) -> list[Moment]:
    if not settings.openai_api_key:
        raise PipelineError("OPENAI_API_KEY is not configured")

    transcript_text = "\n".join(
        f"[{segment.start:.1f}-{segment.end:.1f}] {segment.text}" for segment in transcript
    )
    requested_candidates = min(24, max(clip_count * 3, 8))
    instructions = (
        "You are a top short-form editor who finds the clips that go viral from long "
        "podcasts and interviews. Read the whole transcript and mine for gold: moments a "
        "stranger scrolling X or TikTok would stop for, watch to the end, and share.\n\n"
        "What gold looks like:\n"
        "- A specific story with stakes, a turn, and a payoff\n"
        "- A contrarian or surprising claim the speaker then backs up\n"
        '- Concrete numbers, money, time, or results ("we went from 0 to $10M in 18 months")\n'
        "- A vivid confession, regret, or emotional peak\n"
        "- A sharp, quotable line or a genuinely funny exchange\n"
        "- A tactical insight someone could act on today\n\n"
        "What to reject: intros, outros, sponsor reads, small talk, setup with no payoff, "
        "rambling, repeated points, inside references that need earlier context, and "
        "generic advice anyone could say.\n\n"
        "Editing rules:\n"
        "- Start on the hook. The first sentence must grab attention by itself. Cut "
        'throat-clearing like "so yeah", "um", or the host\'s long question; keep only '
        "the part of a question needed to understand the answer.\n"
        "- End right after the payoff lands. Do not trail into the next topic.\n"
        "- Every start begins a complete sentence and every end finishes the thought. "
        "Duration is flexible; never cut a sentence to hit the requested length.\n"
        "- Spread picks across the whole video and across different kinds of moments.\n"
        "- Candidates must not overlap.\n\n"
        "For each candidate, give hook_line (the opening sentence as spoken), payoff "
        "(what the viewer gets by the end), kind, and honest 1-10 scores. Be a harsh "
        "judge: a 9 or 10 is a clip you would bet on going viral; a typical moment is a 5. "
        "Titles are short and punchy. Reasons say why a stranger would care."
    )
    prompt = (
        (f"Video title: {video_title}\n" if video_title else "")
        + f"Video duration: {video_duration:.1f} seconds.\n"
        f"Find {requested_candidates} candidate clips near {target_duration} seconds each. "
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

    shortlist_size = clip_count + 3 if review else clip_count
    moments = normalize_moments(
        rank_candidates(parsed.moments),
        video_duration=video_duration,
        target_duration=target_duration,
        clip_count=shortlist_size,
        transcript=transcript,
        words=words,
    )
    if not moments:
        raise PipelineError("No valid clip ranges were found")
    if review:
        reviewed = review_moments(moments, transcript, clip_count, target_duration, settings)
        moments = normalize_moments(
            reviewed,
            video_duration=video_duration,
            target_duration=target_duration,
            clip_count=clip_count,
            transcript=transcript,
            words=words,
        ) or moments[:clip_count]
    return moments
