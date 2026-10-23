"""Public configuration API for IASim."""

from __future__ import annotations

from iasim.config.loader import ConfigError, load_config
from iasim.config.models import (
    DebugConfig,
    GameConfig,
    IasimConfig,
    LogsConfig,
    McpConfig,
    UiConfig,
    WeatherConfig,
    WorldConfig,
)

__all__ = [
    "ConfigError",
    "DebugConfig",
    "GameConfig",
    "IasimConfig",
    "LogsConfig",
    "McpConfig",
    "UiConfig",
    "WeatherConfig",
    "WorldConfig",
    "load_config",
]
