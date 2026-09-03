from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


APP_NAME = "AuthorizedBookBuilder"
DEFAULT_BASE_URL = "https://z-library.biz"
LEGACY_BASE_URLS = {"https://z-library.bz"}


def normalize_base_url(value: str) -> str:
    if not isinstance(value, str):
        return DEFAULT_BASE_URL
    normalized = value.strip().rstrip("/")
    if normalized.casefold() in LEGACY_BASE_URLS:
        return DEFAULT_BASE_URL
    return normalized or DEFAULT_BASE_URL


def app_data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_download_dir() -> Path:
    path = Path.home() / "Downloads" / "BookLibrary"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(slots=True)
class Settings:
    output_dir: str = ""
    base_url: str = DEFAULT_BASE_URL
    request_delay: float = 3.0
    page_timeout: int = 120
    download_timeout: int = 3600
    authorization_confirmed: bool = False
    auto_update_source: bool = True
    source_checked_at: float = 0.0

    @classmethod
    def load(cls) -> "Settings":
        path = app_data_dir() / "settings.json"
        if not path.exists():
            return cls(output_dir=str(default_download_dir()))
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            allowed = {key: value for key, value in raw.items() if key in cls.__dataclass_fields__}
            settings = cls(**allowed)
            if not settings.output_dir:
                settings.output_dir = str(default_download_dir())
            settings.base_url = normalize_base_url(settings.base_url)
            if not isinstance(settings.auto_update_source, bool):
                settings.auto_update_source = True
            try:
                settings.source_checked_at = float(settings.source_checked_at)
            except (TypeError, ValueError):
                settings.source_checked_at = 0.0
            return settings
        except (OSError, ValueError, TypeError):
            return cls(output_dir=str(default_download_dir()))

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
