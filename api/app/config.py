from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
ROOT_DIR = REPO_ROOT if (REPO_ROOT / "api").is_dir() else APP_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_transcription_model: str = "whisper-1"
    openai_moment_model: str = "gpt-5-mini"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    app_encryption_key: str = ""
    web_origin: str = "http://localhost:3000"
    ytdlp_proxy: str = ""
    youtube_cookies_file: str = ""
    data_dir: Path = Field(default=ROOT_DIR / "api" / "data")
    max_video_seconds: int = 4 * 60 * 60
    process_timeout_seconds: int = 30 * 60
    audio_chunk_seconds: int = 10 * 60
    job_retention_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
