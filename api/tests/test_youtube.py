import pytest

from app.services.youtube import validate_youtube_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_accepts_supported_youtube_urls(url: str) -> None:
    assert validate_youtube_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com.example.org/watch?v=abc",
        "https://example.com/video",
        "file:///tmp/video.mp4",
        "https://user:pass@youtube.com/watch?v=abc",
    ],
)
def test_rejects_untrusted_urls(url: str) -> None:
    with pytest.raises(ValueError, match="valid"):
        validate_youtube_url(url)
