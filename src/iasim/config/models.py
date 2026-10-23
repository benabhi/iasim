"""Validated configuration models for IASim."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """Base model that rejects unknown keys and prevents mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class GameConfig(StrictModel):
    """Top-level game session settings.

    Agent limits and persistence cadence live here because SRS section 7.1
    defines them under the ``[game]`` table.
    """

    seed: int | None = Field(default=None, ge=0)
    headless: bool = False
    min_agents: int = Field(default=1, ge=1, le=8)
    max_agents: int = Field(default=8, ge=1, le=8)
    tick_minutes: int = Field(default=5, ge=1)
    turn_timeout_ms: int = Field(default=60_000, ge=1)
    timeout_disconnects: int = Field(default=3, ge=1)
    allow_late_join: bool = False
    pause_on_overlay: bool = True
    autosave_every_ticks: int = Field(default=1_000, ge=0)

    @field_validator("max_agents")
    @classmethod
    def max_agents_must_cover_min_agents(cls, value: int, info: ValidationInfo) -> int:
        """Reject a maximum agent count below the configured minimum."""
        min_agents = info.data.get("min_agents")
        if isinstance(min_agents, int) and value < min_agents:
            raise ValueError("must be greater than or equal to min_agents")
        return value


class WorldConfig(StrictModel):
    """MVP island dimensions and display name."""

    width: Literal[80] = 80
    height: Literal[40] = 40
    name: str = Field(default="isla_boscosa", min_length=1)


class WeatherConfig(StrictModel):
    """Weather and seasonal settings.

    Snow accumulation and seasonal content are F2 work, but the settings are
    part of the forward-compatible MVP configuration contract.
    """

    snow_enabled: bool = False
    season: Literal["spring", "summer", "autumn", "winter"] = "summer"
    season_days: int = Field(default=7, ge=1)
    weather_min_ticks: int = Field(default=12, ge=1)
    weather_max_ticks: int = Field(default=72, ge=1)
    forecast_enabled: bool = True
    forecast_horizon_ticks: int = Field(default=6, ge=0, le=6)

    @field_validator("weather_max_ticks")
    @classmethod
    def max_weather_must_cover_min_weather(cls, value: int, info: ValidationInfo) -> int:
        """Reject a maximum weather duration below the configured minimum."""
        min_ticks = info.data.get("weather_min_ticks")
        if isinstance(min_ticks, int) and value < min_ticks:
            raise ValueError("must be greater than or equal to weather_min_ticks")
        return value


class McpConfig(StrictModel):
    """Local HTTP MCP transport settings."""

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8765, ge=1, le=65_535)
    require_token: bool = True
    dev_open: bool = False

    @model_validator(mode="after")
    def dev_open_must_stay_on_loopback(self) -> Self:
        """Refuse to disable authentication on a non-loopback interface."""
        if not self.dev_open:
            return self

        host = self.host.strip().lower()
        if host == "localhost":
            return self
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("dev_open requires a loopback host") from exc
        if not address.is_loopback:
            raise ValueError("dev_open requires a loopback host")
        return self


class UiConfig(StrictModel):
    """Terminal UI settings; player-facing text remains Spanish."""

    language: Literal["es"] = "es"
    font_path: Path = Path("assets/fonts/DejaVuSansMono.ttf")
    font_width: int = Field(default=12, ge=1)
    font_height: int = Field(default=24, ge=1)
    palette: str = Field(default="default", min_length=1)
    map_zoom_font_width: int = Field(default=24, ge=1)
    map_zoom_font_height: int = Field(default=24, ge=1)


class LogsConfig(StrictModel):
    """Run-directory, snapshot, and export settings."""

    dir: Path = Path("runs")
    snapshot_every_ticks: int = Field(default=100, ge=1)
    export_csv: bool = True


class DebugConfig(StrictModel):
    """Operator-only debug console settings; never exposed through MCP."""

    enabled: bool = False
    confirm_destructive: bool = True


class IasimConfig(StrictModel):
    """Complete validated IASim configuration."""

    game: GameConfig = Field(default_factory=GameConfig)
    world: WorldConfig = Field(default_factory=WorldConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
