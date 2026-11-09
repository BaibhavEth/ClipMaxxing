from app.config import Settings
from app.models import ClipResult, TranscriptWord
from app.services import social
from app.services.social import (
    SocialPostDraft,
    SocialPosts,
    format_breakdown_post,
    format_social_post,
    format_story_post,
    parse_social_posts,
    quote_is_grounded,
    review_draft,
    serialize_social_posts,
)


def test_accepts_only_contiguous_transcript_quotes() -> None:
    transcript = (
        "You bought one million dollars worth of gold chains and twenty years later "
        "you were up ten times"
    )

    assert quote_is_grounded(
        "one million dollars worth of gold chains",
        transcript,
    )
    assert not quote_is_grounded(
        "one million dollars and twenty years later",
        transcript,
    )


def test_quotes_may_drop_fillers_and_stutters_but_not_real_words() -> None:
    transcript = (
        "the claim is this this guy is uh better at scrabble than you know anyone is at any game"
    )

    assert quote_is_grounded(
        "This guy is better at Scrabble than anyone is at any game", transcript
    )
    assert not quote_is_grounded("This guy is better at Scrabble than anyone", "this guy is good")
    assert not quote_is_grounded("the claim is this guy is great", transcript)


BREAKDOWN_POINTS = [
    "He memorized the entire French Scrabble dictionary in about nine weeks",
    "He cannot hold a conversation in French and needed an interpreter to accept the title",
    "He had already won the US, UK, and world championships in English",
    "Rivals say he treats words as patterns of letters, not as meaning",
]


def _draft(**overrides: object) -> SocialPostDraft:
    values = {
        "mode": "story",
        "payoff": "He won the French title without speaking French",
        "scroll_stop_score": 8,
        "speaker": "Nigel Richards",
        "hook_pattern": "pattern_interrupt",
        "hook": "Nigel Richards won the French Scrabble championship without speaking French",
        "quote": "this guy is better at scrabble than anyone is at any game",
        "story_setup": "Nigel Richards rode his bike 222 miles to his first Scrabble tournament",
        "story_turn": "he won the US, UK, and French titles",
        "story_kicker": "he rode 222 miles home after",
        "breakdown_hook": "The best French Scrabble player alive cannot speak French",
        "breakdown_points": BREAKDOWN_POINTS,
        "breakdown_close": "Is that mastery of a game, or proof Scrabble was never about words?",
    }
    return SocialPostDraft(**{**values, **overrides})


def test_review_flags_meta_language_and_first_person() -> None:
    transcript = "the claim is this this guy is better at scrabble than anyone is at any game"

    assert review_draft(_draft(), transcript) == []
    problems = review_draft(
        _draft(hook="The host argues the counterintuitive takeaway is that I should try"),
        transcript,
    )
    assert any("banned wording" in problem for problem in problems)
    assert any("first person" in problem for problem in problems)
    assert any(
        "too flat" in problem for problem in review_draft(_draft(scroll_stop_score=5), transcript)
    )


def test_review_flags_thin_or_generic_breakdowns() -> None:
    transcript = "the claim is this this guy is better at scrabble than anyone is at any game"

    thin = review_draft(
        _draft(breakdown_points=["He won", "He won again", "He won once more"]), transcript
    )
    assert any("add concrete detail" in problem for problem in thin)

    generic = review_draft(_draft(breakdown_close="Wild story. Thoughts?"), transcript)
    assert any("generic call to action" in problem for problem in generic)

    repeated = review_draft(
        _draft(breakdown_hook=_draft().hook), transcript
    )
    assert any("repeats Post 1's hook" in problem for problem in repeated)


def test_formats_breakdown_with_spaced_lines_and_no_list_markers() -> None:
    text = format_breakdown_post(
        "Brian Armstrong built Coinbase while working full time at Airbnb.",
        ["- 8pm to midnight, 3 to 4 nights a week.", "2) Plus 7 hours every Sunday"],
        "Would you trade 18 months of weekends for that?",
    )

    assert text == (
        "Brian Armstrong built Coinbase while working full time at Airbnb\n\n"
        "8pm to midnight, 3 to 4 nights a week\n\n"
        "Plus 7 hours every Sunday\n\n"
        "Would you trade 18 months of weekends for that?"
    )


SPOKEN = "this guy is better at scrabble than anyone is at any game"
CLIP = ClipResult(title="Scrabble", reason="Wild", start=0, end=20, filename="clip-01.mp4")


def _spoken_words() -> list[TranscriptWord]:
    return [
        TranscriptWord(start=index, end=index + 0.5, word=word)
        for index, word in enumerate(SPOKEN.split(" "))
    ]


def _fake_openai(monkeypatch, drafts: list[SocialPostDraft]) -> list[str]:
    remaining = iter(drafts)
    prompts: list[str] = []

    class FakeResponses:
        def parse(self, **kwargs):
            prompts.append(kwargs["input"])
            return type("Response", (), {"output_parsed": next(remaining)})()

    class FakeClient:
        def __init__(self, **_):
            self.responses = FakeResponses()

    monkeypatch.setattr(social, "OpenAI", FakeClient)
    return prompts


def test_revises_draft_once_when_review_finds_problems(monkeypatch) -> None:
    prompts = _fake_openai(
        monkeypatch, [_draft(hook="The host argues something about Scrabble here"), _draft()]
    )

    posts = social.generate_social_post(
        "Rabbit Hole", CLIP, _spoken_words(), Settings(openai_api_key="sk-test"), channel="MFM"
    )

    assert len(prompts) == 2
    assert "banned wording" in prompts[1]
    assert posts.quote.startswith("Nigel Richards won the French Scrabble championship")
    assert posts.quote.endswith("“This guy is better at scrabble than anyone is at any game.”")
    assert posts.breakdown.startswith("The best French Scrabble player alive cannot speak French")
    assert posts.breakdown.endswith("proof Scrabble was never about words?")


def test_keeps_the_stronger_draft_when_revision_is_worse(monkeypatch) -> None:
    _fake_openai(
        monkeypatch,
        [_draft(scroll_stop_score=6), _draft(hook="The host argues about Scrabble here")],
    )

    posts = social.generate_social_post(
        "Rabbit Hole", CLIP, _spoken_words(), Settings(openai_api_key="sk-test")
    )

    assert posts.quote.startswith("Nigel Richards won the French Scrabble championship")


def test_formats_hook_and_quote_in_iced_coffee_hour_style() -> None:
    text = format_social_post(
        "Gold quietly created an extraordinary retail business",
        '"You were up ten times."',
    )

    assert text == (
        "Gold quietly created an extraordinary retail business…\n\n“You were up ten times.”"
    )


def test_formats_lowercase_three_beat_story_post() -> None:
    text = format_story_post(
        "Brian Armstrong built Coinbase from 8pm to midnight, 3 to 4 nights a week, "
        "plus 7 hours every Sunday, for 18 months",
        "He never touched Airbnb's laptop doing it.",
        "Friendships were the actual cost",
    )

    assert text == (
        "Brian Armstrong built Coinbase from 8pm to midnight, 3 to 4 nights a week, "
        "plus 7 hours every Sunday, for 18 months\n\n"
        "he never touched Airbnb's laptop doing it\n\n"
        "friendships were the actual cost"
    )


def test_round_trips_all_social_post_styles() -> None:
    posts = SocialPosts(
        quote="Hook…\n\n“Quote”",
        story="Setup\n\nturn\n\nkicker",
        breakdown="Hook\n\npoint\n\nclose?",
    )

    assert parse_social_posts(serialize_social_posts(posts)) == posts
    assert parse_social_posts('{"quote": "q", "story": "s"}') == SocialPosts(
        quote="q", story="s", breakdown=""
    )
    assert parse_social_posts("old quote-only post") == SocialPosts(
        quote="old quote-only post",
        story="",
    )
