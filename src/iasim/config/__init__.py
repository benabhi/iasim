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
    is_loopback_host,
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
    "is_loopback_host",
    "load_config",
]
