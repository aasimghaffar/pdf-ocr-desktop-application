"""Persistent settings (JSON in %APPDATA%) and API key storage (Windows Credential Manager)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import keyring
from keyring.errors import KeyringError

APP_NAME = "PdfOcr"
KEYRING_SERVICE = "PdfOcr"
KEYRING_USER = "gemini"
DEFAULT_MODEL = "gemini-3.8-flash"
SUGGESTED_MODELS = [DEFAULT_MODEL, "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"]


def is_retired_model(name: str) -> bool:
    """Gemini 1.x and 2.x models: new API keys can no longer use them."""
    return name.startswith(("gemini-1", "gemini-2"))


def _config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


SETTINGS_FILE = _config_dir() / "settings.json"
LOG_FILE = _config_dir() / "app.log"


@dataclass
class Settings:
    input_dir: str = ""
    output_dir: str = ""
    model: str = DEFAULT_MODEL
    output_mode: str = "text"  # "text" (text only, images removed) or "overlay" (searchable scan)
    dpi: int = 200
    overwrite: bool = False
    watch: bool = False

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in data.items() if k in known})
        if is_retired_model(settings.model):
            settings.model = DEFAULT_MODEL
        return settings

    def save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def get_api_key() -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except KeyringError:
        return ""


def set_api_key(key: str) -> None:
    key = key.strip()
    if key:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except KeyringError:
            pass
