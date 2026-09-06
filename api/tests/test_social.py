from app.services.social import format_social_post, quote_is_grounded


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


def test_formats_hook_and_quote_in_iced_coffee_hour_style() -> None:
    text = format_social_post(
        "Gold quietly created an extraordinary retail business",
        '"You were up ten times."',
    )

    assert text == (
        "Gold quietly created an extraordinary retail business…\n\n"
        "“You were up ten times.”"
    )
