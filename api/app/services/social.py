import json
import re
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.models import ClipResult, TranscriptWord
from app.services.errors import PipelineError

FILLER_TOKENS = {"uh", "uhh", "um", "umm", "erm", "er", "ah", "hmm", "mm"}
FILLER_PHRASES = (["you", "know"], ["i", "mean"])
MIN_QUOTE_WORDS = 6
MAX_QUOTE_WORDS = 40
MAX_POST_CHARS = 280
MIN_BREAKDOWN_CHARS = 300
MAX_BREAKDOWN_CHARS = 900
MIN_SCROLL_STOP_SCORE = 7
GENERIC_CLOSES = (
    "thoughts?",
    "what do you think",
    "agree?",
    "let me know",
    "drop a comment",
    "comment below",
    "follow for more",
    "like and",
    "retweet",
)
BANNED_PHRASES = (
    "counterintuitive",
    "takeaway",
    "the speaker",
    "the host",
    "the guest",
    "this clip",
    "this video",
    "this episode",
    "argues",
    "says that",
    "game changer",
    "game-changer",
    "unlock",
    "here's why",
    "you won't believe",
    "mind-blowing",
    "mind blowing",
    "insane",
    "life lesson",
    "reminder that",
)
FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'd|i'll|me|my|mine|we|we're|our)\b", re.IGNORECASE)

INSTRUCTIONS = """\
You write X posts for an account that posts clips from podcasts and interviews. The account is
a curator, never the person speaking: write in the third person and name who is talking when
the title, channel, or transcript makes it clear. If you cannot tell who is speaking, describe
them by what makes them interesting ("a Scrabble champion", "a founder who sold for $1B"),
never as "the speaker", "the host", or "the guest".

Everything must be supported by the transcript or title. Never invent names, numbers,
employers, timelines, or outcomes.

How X works, and what to write for:
- On X the post text is the reason someone presses play. It is not a description of the
  video. Every post must open a gap the clip closes, or deliver a line so sharp people want
  to see it said.
- X's ranking rewards people sending a post to a friend, copying its link, replying, and
  quote-posting far more than likes or views. Write posts a stranger would forward ("you
  need to see this") or argue with in the replies.
- Specific beats vague every time: real numbers, names, places, amounts, and timelines from
  the clip stop the scroll. Adjectives ("incredible", "massive") read as noise.
- Never use announcement language ("new episode", "great conversation", "in this clip").

STEP 1: classify the clip and find its payoff
- mode "story": something happened to someone, with an outcome, cost, or reveal.
  payoff = that outcome ("the parking attendant broke down in tears").
- mode "take": the clip is mostly an opinion, argument, or observation with no real outcome.
  payoff = the boldest, most arguable claim in the clip, stated as plainly as a person would
  tweet it ("'taste' is just a way to call everyone else a peasant"). Pick the claim people
  would quote-tweet to agree or argue with, not the safest or most balanced point. Never use
  side details (tips, exercises, book names) as the payoff of a take.

STEP 2: pick the hook pattern that fits this clip best (hook_pattern):
- "sharp_claim": a specific, arguable statement people will quote-post to agree or fight
  ("Cold DMs beat cold email for consultants under $500k")
- "micro_story": drop the reader into a scene with a result but an unexplained middle
  ("He pitched the board with a napkin sketch. They wrote a $40M check.")
- "number_with_stakes": lead with the most striking number and what it cost or earned
  ("Brian Armstrong worked on Coinbase 30 hours a week for 18 months, unpaid")
- "pattern_interrupt": a failure, regret, or reversal where readers expect a win
  ("He turned down $1B for Instagram's competitor. He still thinks about it.")
- "instruction_gap": the first step of something useful, with the rest in the clip
  ("Step one of negotiating a raise: never name your number first")

STEP 3: write three posts that all land on the payoff.

POST 1: hook + quote
- hook: one sentence, under 200 characters, that makes someone stop scrolling, written in
  your chosen hook_pattern.
  story: lead with the most surprising concrete fact, attributed to a person.
  take: state the claim itself, sharp and plain, as if it were obviously true.
  No hype words and no meta language ("takeaway", "argues", "says that", "lesson",
  "counterintuitive", "this clip").
- quote: the single best line in the clip, 8 to 30 words, copied from the transcript. You may
  drop filler sounds (uh, um), stutters ("this this"), and "you know" / "I mean", and you may
  fix capitalization and punctuation. Do not change, reorder, or add any other words. Pick
  the line that delivers the payoff: a punchline, a surprising number, or the spiciest version
  of the take. Strong language is fine when it is the sharpest line. Skip lines that need
  context, and skip lines about the speaker's own doubts or framing.

Good story hook: Nigel Richards won the French Scrabble championship without speaking French
Good take hook: Calling something "slop" has become the easiest way to sound smart without
  saying anything
Bad hook: The host argues taste is often a status signal, not a meaningful standard.
  (meta language, hedged, no edge)

POST 2: three beats, under 280 characters total, beats 2 and 3 lowercase with no period
Story example:
  Brian Armstrong built Coinbase from 8pm to midnight, 3 to 4 nights a week, plus 7 hours
  every Sunday, for 18 months

  he never touched Airbnb's laptop doing it

  friendships were the actual cost
Take example:
  Everyone in 2026 says the thing that matters now is taste

  nobody can define it

  it's just a polite way to call you a peasant
- story_setup: story: one person doing one specific thing, with the most concrete numbers and
  details. take: the common belief or situation the claim pushes against. One sentence, no
  more than 25 words, one idea, not a list of facts.
- story_turn: story: the detail that raises the stakes or flips expectations. take: the
  problem with that belief. Under 12 words.
- story_kicker: the payoff, under 10 words. story: the most satisfying concrete fact. take:
  the claim at its sharpest. Never a moral, a life lesson, or a side detail.
  Bad kicker: "the real advantage goes to the few who try" (moral)
  Bad kicker: "he builds a swipe file on his phone" (side detail)
  Good kicker: "he broke down in floods of tears"
- Do not start both the turn and the kicker with "but" or "and".

POST 3: breakdown, the in-depth post, 300 to 900 characters total
This is for readers who want the substance. It should read like a sharp friend explaining
why this clip matters, packed with specifics from the transcript.
- breakdown_hook: one sentence under 200 characters, in your hook_pattern, different
  wording from Post 1's hook.
- breakdown_points: 3 to 5 short lines, each one concrete thing from the clip: a number, a
  decision, a mechanism, a detail, or a consequence. Each line under 160 characters and
  stands on its own. Order them so they build toward the payoff. No bullets, numbering, or
  emojis; one idea per line. No filler lines and no restating the hook.
- breakdown_close: one line under 160 characters that makes people reply. Either a pointed,
  specific question only this clip could raise ("Would you trade 18 months of weekends for a
  shot at Coinbase?"), or the payoff stated so sharply people will want to argue. Never a
  generic prompt like "Thoughts?", "Agree?", or "Let me know below".

Good breakdown:
  Brian Armstrong built Coinbase while still working full time at Airbnb

  8pm to midnight, 3 to 4 nights a week

  plus 7 hours every Sunday, for 18 months

  he never touched his Airbnb laptop for it, so the company could never claim it

  the real cost wasn't sleep, it was his friendships

  Would you trade your social life for 18 months on a side project that might not work?

STEP 4: rate your own posts. scroll_stop_score is 1 to 10: would a stranger stop scrolling,
watch the clip, and send it to someone? Be harsh. A 10 is a post you would bet goes viral; a
5 is accurate but forgettable.

No hashtags, emojis, or quotation marks in the story or breakdown. Only the breakdown close
may invite replies; no other calls to action anywhere.
"""


HookPattern = Literal[
    "sharp_claim",
    "micro_story",
    "number_with_stakes",
    "pattern_interrupt",
    "instruction_gap",
]


class SocialPostDraft(BaseModel):
    mode: Literal["story", "take"]
    payoff: str = Field(min_length=8, max_length=200)
    speaker: str = Field(max_length=120)
    hook_pattern: HookPattern
    hook: str = Field(min_length=20, max_length=300)
    quote: str = Field(min_length=10, max_length=500)
    story_setup: str = Field(min_length=20, max_length=240)
    story_turn: str = Field(min_length=8, max_length=140)
    story_kicker: str = Field(min_length=8, max_length=120)
    breakdown_hook: str = Field(min_length=20, max_length=300)
    breakdown_points: list[str] = Field(min_length=3, max_length=5)
    breakdown_close: str = Field(min_length=8, max_length=240)
    scroll_stop_score: int = Field(ge=1, le=10)


class SocialPosts(BaseModel):
    quote: str
    story: str
    breakdown: str = ""


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:['’][a-z0-9]+)?", value.lower().replace("’", "'"))


def _matches_at(quote: list[str], transcript: list[str], start: int) -> bool:
    position = start
    for index, token in enumerate(quote):
        while True:
            if position >= len(transcript):
                return False
            current = transcript[position]
            if current == token:
                position += 1
                break
            if index == 0:
                return False
            if current in FILLER_TOKENS or current == transcript[position - 1]:
                position += 1
            elif transcript[position : position + 2] in FILLER_PHRASES:
                position += 2
            else:
                return False
    return True


def quote_is_grounded(quote: str, transcript: str) -> bool:
    quote_tokens = [token for token in _tokens(quote) if token not in FILLER_TOKENS]
    transcript_tokens = _tokens(transcript)
    if not quote_tokens:
        return False
    return any(
        _matches_at(quote_tokens, transcript_tokens, index)
        for index in range(len(transcript_tokens))
    )


def review_draft(draft: SocialPostDraft, transcript: str) -> list[str]:
    problems: list[str] = []
    if not quote_is_grounded(draft.quote, transcript):
        problems.append(
            "The quote is not in the transcript. Copy the words exactly; only fillers "
            "and stutters may be dropped."
        )
    quote_words = len(_tokens(draft.quote))
    if quote_words < MIN_QUOTE_WORDS or quote_words > MAX_QUOTE_WORDS:
        problems.append(f"The quote is {quote_words} words; use 8 to 30.")

    story = format_story_post(draft.story_setup, draft.story_turn, draft.story_kicker)
    if len(story) > MAX_POST_CHARS:
        problems.append(f"The story post is {len(story)} characters; keep it under 280.")
    if len(draft.hook) > 200:
        problems.append("The hook is too long; keep it under 200 characters.")

    breakdown = format_breakdown_post(
        draft.breakdown_hook, draft.breakdown_points, draft.breakdown_close
    )
    if len(breakdown) < MIN_BREAKDOWN_CHARS:
        problems.append(
            f"The breakdown is {len(breakdown)} characters; add concrete detail from the "
            f"clip to reach at least {MIN_BREAKDOWN_CHARS}."
        )
    if len(breakdown) > MAX_BREAKDOWN_CHARS:
        problems.append(
            f"The breakdown is {len(breakdown)} characters; tighten it under "
            f"{MAX_BREAKDOWN_CHARS}."
        )
    if _clean_line(draft.breakdown_hook).lower() == _clean_line(draft.hook).lower():
        problems.append("The breakdown hook repeats Post 1's hook; reword it.")
    close = draft.breakdown_close.lower()
    generic = [phrase for phrase in GENERIC_CLOSES if phrase in close]
    if generic:
        problems.append(
            "The breakdown close is a generic call to action; ask a pointed question only "
            "this clip could raise."
        )

    written = {
        "hook": draft.hook,
        "story_setup": draft.story_setup,
        "story_turn": draft.story_turn,
        "story_kicker": draft.story_kicker,
        "breakdown_hook": draft.breakdown_hook,
        "breakdown_close": draft.breakdown_close,
        **{
            f"breakdown_points[{index}]": point
            for index, point in enumerate(draft.breakdown_points)
        },
    }
    for field, text in written.items():
        lowered = text.lower()
        banned = [phrase for phrase in BANNED_PHRASES if phrase in lowered]
        if banned:
            problems.append(f"{field} uses banned wording: {', '.join(banned)}.")
        if FIRST_PERSON.search(text):
            problems.append(f"{field} is in first person; write as a third-party curator.")
    if draft.scroll_stop_score < MIN_SCROLL_STOP_SCORE:
        problems.append(
            f"You rated these posts {draft.scroll_stop_score}/10, which is too flat. Find a "
            "sharper payoff: the most surprising fact or the boldest claim in the clip, and "
            "make both posts land on it."
        )
    return problems


def _clean_line(value: str) -> str:
    return value.strip().strip('"“”').strip()


def _casual_beat(value: str) -> str:
    text = _clean_line(value).rstrip(".!? ")
    if not text:
        return text
    return text[0].lower() + text[1:]


def _clean_quote(value: str) -> str:
    text = _clean_line(value)
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?…":
        text += "."
    return text


def format_social_post(hook: str, quote: str) -> str:
    clean_hook = hook.strip()
    if clean_hook[-1] not in ".!?…":
        clean_hook += "…"
    return f"{clean_hook}\n\n“{_clean_quote(quote)}”"


def format_story_post(setup: str, turn: str, kicker: str) -> str:
    return f"{_clean_line(setup)}\n\n{_casual_beat(turn)}\n\n{_casual_beat(kicker)}"


def _strip_list_marker(value: str) -> str:
    return re.sub(r"^(?:[-•*→]|\d+[.)])\s*", "", _clean_line(value))


def format_breakdown_post(hook: str, points: list[str], close: str) -> str:
    lines = [_clean_line(hook).rstrip(".")]
    lines.extend(
        _strip_list_marker(point).rstrip(".") for point in points if point.strip()
    )
    lines.append(_clean_line(close))
    return "\n\n".join(line for line in lines if line)


def serialize_social_posts(posts: SocialPosts) -> str:
    return posts.model_dump_json()


def parse_social_posts(value: str | None) -> SocialPosts:
    if not value:
        return SocialPosts(quote="", story="")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return SocialPosts(quote=value, story="")
    if isinstance(payload, dict) and isinstance(payload.get("quote"), str):
        story = payload.get("story")
        breakdown = payload.get("breakdown")
        return SocialPosts(
            quote=payload["quote"],
            story=story if isinstance(story, str) else "",
            breakdown=breakdown if isinstance(breakdown, str) else "",
        )
    return SocialPosts(quote=value, story="")


def _join_words(words: list[TranscriptWord]) -> str:
    return " ".join(word.word.strip() for word in words if word.word.strip())


def generate_social_post(
    video_title: str,
    clip: ClipResult,
    words: list[TranscriptWord],
    settings: Settings,
    channel: str = "",
    context_words: list[TranscriptWord] | None = None,
) -> SocialPosts:
    if not settings.openai_api_key:
        raise PipelineError("OPENAI_API_KEY is not configured")
    transcript = _join_words(words)
    if not transcript:
        raise PipelineError("This clip has no transcript for social copy")

    context = _join_words(context_words or [])
    prompt = (
        f"Channel: {channel or 'unknown'}\n"
        f"Video title: {video_title}\n"
        f"Clip title: {clip.title}\n"
        f"Why this moment matters: {clip.reason}\n\n"
        + (
            f"EARLIER CONTEXT (for identifying people only; do not quote)\n{context}\n\n"
            if context
            else ""
        )
        + f"CLIP TRANSCRIPT\n{transcript}"
    )

    client = OpenAI(api_key=settings.openai_api_key)
    model = settings.openai_social_model or settings.openai_moment_model
    options = {"reasoning": {"effort": "low"}} if model.startswith(("gpt-5", "o")) else {}
    best: SocialPostDraft | None = None
    best_rank: tuple[int, int] | None = None
    feedback = ""
    for _ in range(2):
        try:
            response = client.responses.parse(
                model=model,
                instructions=INSTRUCTIONS,
                input=prompt + feedback,
                text_format=SocialPostDraft,
                **options,
            )
            draft = response.output_parsed
        except Exception as exc:
            raise PipelineError("OpenAI could not generate social post copy") from exc
        if draft is None:
            continue
        problems = review_draft(draft, transcript)
        is_flat = draft.scroll_stop_score < MIN_SCROLL_STOP_SCORE
        rank = (len(problems) - is_flat, -draft.scroll_stop_score)
        if quote_is_grounded(draft.quote, transcript) and (best_rank is None or rank < best_rank):
            best, best_rank = draft, rank
        if not problems:
            break
        feedback = (
            "\n\nYOUR PREVIOUS DRAFT\n"
            f"{draft.model_dump_json(indent=2)}\n\n"
            "Fix these problems and return a new draft:\n- " + "\n- ".join(problems)
        )

    if best is None:
        raise PipelineError("The generated quote could not be verified against the transcript")
    return SocialPosts(
        quote=format_social_post(best.hook, best.quote),
        story=format_story_post(best.story_setup, best.story_turn, best.story_kicker),
        breakdown=format_breakdown_post(
            best.breakdown_hook, best.breakdown_points, best.breakdown_close
        ),
    )
