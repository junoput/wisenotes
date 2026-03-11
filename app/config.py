from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


def _parse_cfg(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        result[key] = val
    return result


class Settings(BaseSettings):
    app_name: str = "Wisenotes"
    data_dir: Path = Field(default_factory=lambda: Path("./data"))
    data_file: str = "notes.json"
    max_payload_bytes: int = 512_000
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


@lru_cache
def get_accessibility_bindings() -> dict[str, str]:
    cfg_path = Path(__file__).parent / "config" / "accessibility.cfg"
    if not cfg_path.exists():
        cfg_path = Path(__file__).parent / "accessibility.cfg"
    return _parse_cfg(cfg_path)
