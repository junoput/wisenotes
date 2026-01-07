from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings
from functools import lru_cache as _lru_cache
from pathlib import Path as _Path
from typing import Dict


def _parse_cfg(path: _Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
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
        # strip optional surrounding quotes
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        result[key] = val
    return result


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


@_lru_cache()
def get_accessibility_bindings() -> Dict[str, str]:
    cfg_path = _Path(__file__).parent / "config" / "accessibility.cfg"
    # fall back to file next to module if present
    if not cfg_path.exists():
        cfg_path = _Path(__file__).parent / "accessibility.cfg"
    return _parse_cfg(cfg_path)
