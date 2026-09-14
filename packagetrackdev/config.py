"""Configuration: API key and server URL."""

from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".packagetrack"
CONFIG_PATH = CONFIG_DIR / "config.toml"

ENV_KEY = "PACKAGETRACK_API_KEY"
ENV_SERVER = "PACKAGETRACK_SERVER"

DEFAULT_SERVER = "https://packagetrack.dev"


@dataclass(slots=True)
class Config:
    api_key: str | None
    server: str


def _file_values() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load(api_key: str | None = None, server: str | None = None) -> Config:
    values = _file_values()
    return Config(
        api_key=api_key or os.environ.get(ENV_KEY) or values.get("api_key"),
        server=(
            server
            or os.environ.get(ENV_SERVER)
            or values.get("server")
            or DEFAULT_SERVER
        ).rstrip("/"),
    )


def save(api_key: str | None = None, server: str | None = None) -> Path:
    """Write the config file, keeping unchanged values."""
    values = _file_values()
    if api_key is not None:
        values["api_key"] = api_key
    if server is not None:
        values["server"] = server.rstrip("/")

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f'{key} = "{value}"' for key, value in sorted(values.items())]
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
    CONFIG_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return CONFIG_PATH
