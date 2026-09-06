import re

from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.models import ClipResult, TranscriptWord
from app.services.errors import PipelineError


class SocialPostDraft(BaseModel):
    hook: str = Field(min_length=20, max_length=500)
    quote: str = Field(min_length=10, max_length=700)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:['’][a-z0-9]+)?", value.lower())


def quote_is_grounded(quote: str, transcript: str) -> bool:
    quote_tokens = _tokens(quote)
    transcript_tokens = _tokens(transcript)
    if not quote_tokens:
        return False
    width = len(quote_tokens)
    return any(
        transcript_tokens[index : index + width] == quote_tokens
        for index in range(len(transcript_tokens) - width + 1)
    )


def format_social_post(hook: str, quote: str) -> str:
    clean_hook = hook.strip()
    if clean_hook[-1] not in ".!?…":
        clean_hook += "…"
    clean_quote = quote.strip().strip('"“”').strip()
    return f"{clean_hook}\n\n“{clean_quote}”"


def generate_social_post(
    video_title: str,
    clip: ClipResult,
    words: list[TranscriptWord],
    settings: Settings,
) -> str:
    if not settings.openai_api_key:
        raise PipelineError("OPENAI_API_KEY is not configured")
    transcript = " ".join(word.word.strip() for word in words if word.word.strip())
    if not transcript:
        raise PipelineError("This clip has no transcript for social copy")

    instructions = (
        "Write social post copy for a video clip in the Iced Coffee Hour X format. "
        "Return a curiosity-driven one-sentence hook followed by one strong verbatim quote. "
        "The hook should identify the speaker or subject when the provided context supports it, "
        "state the counterintuitive takeaway, and end naturally. The quote must be one exact, "
        "contiguous passage from the transcript: do not rewrite, clean up, combine, or invent "
        "words, names, numbers, or claims. Do not use hashtags, emojis, headings, or calls to "
        "action. Keep the writing specific and editorial rather than sensational."
    )
    prompt = (
        f"Video title: {video_title}\n"
        f"Clip title: {clip.title}\n"
        f"Why this moment matters: {clip.reason}\n\n"
        f"CLIP TRANSCRIPT\n{transcript}"
    )
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.parse(
            model=settings.openai_moment_model,
            instructions=instructions,
            input=prompt,
            text_format=SocialPostDraft,
        )
        draft = response.output_parsed
    except Exception as exc:
        raise PipelineError("OpenAI could not generate social post copy") from exc

    if not draft or not quote_is_grounded(draft.quote, transcript):
        raise PipelineError("The generated quote could not be verified against the transcript")
    return format_social_post(draft.hook, draft.quote)
