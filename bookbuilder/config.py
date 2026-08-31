from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


APP_NAME = "AuthorizedBookBuilder"


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
    base_url: str = "https://z-library.bz"
    request_delay: float = 3.0
    page_timeout: int = 120
    download_timeout: int = 3600
    authorization_confirmed: bool = False

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
            return settings
        except (OSError, ValueError, TypeError):
            return cls(output_dir=str(default_download_dir()))

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
