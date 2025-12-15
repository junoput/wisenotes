from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Wisenotes"
    data_dir: Path = Field(default_factory=lambda: Path("./data"))
    data_file: str = "notes.json"
    max_payload_bytes: int = 512_000  # safeguard import size
    enable_sample_plugins: bool = True
    session_secret_key: str = "change-me"

    class Config:
        env_prefix = "WISENOTES_"
        env_file = ".env"
        extra = "ignore"

    @property
    def data_path(self) -> Path:
        return self.data_dir / self.data_file


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
