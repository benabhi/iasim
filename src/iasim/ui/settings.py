"""Operator display settings for the F8 view.

The settings are presentation-only: they never mutate simulation state. Every
field is validated defensively so an invalid user configuration falls back to a
safe default instead of breaking the operator UI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

MIN_FONT_SCALE = 1
MAX_FONT_SCALE = 4


class Palette(StrEnum):
    """Color palettes selectable from the display settings view."""

    NORMAL = "normal"
    COLORBLIND = "colorblind"

    def toggled(self) -> Palette:
        """Return the other palette."""
        return Palette.COLORBLIND if self is Palette.NORMAL else Palette.NORMAL


PALETTE_LABELS: dict[Palette, str] = {
    Palette.NORMAL: "NORMAL",
    Palette.COLORBLIND: "APTA PARA DALTONISMO",
}


@dataclass(frozen=True, slots=True)
class DisplaySettings:
    """Presentation settings persisted for the duration of the session."""

    palette: Palette = Palette.NORMAL
    font_scale: int = MIN_FONT_SCALE
    pause_on_overlay: bool = False
    show_ticker: bool = True
    show_weather_layer: bool = True
    confirm_exit: bool = True
    fullscreen: bool = False

    def normalized(self) -> DisplaySettings:
        """Return a copy with every invalid field replaced by its default."""
        palette = (
            self.palette if isinstance(self.palette, Palette) else _palette_or_default(self.palette)
        )
        scale = (
            self.font_scale
            if isinstance(self.font_scale, int)
            and not isinstance(self.font_scale, bool)
            and MIN_FONT_SCALE <= self.font_scale <= MAX_FONT_SCALE
            else MIN_FONT_SCALE
        )
        defaults = DisplaySettings()
        return replace(
            self,
            palette=palette,
            font_scale=scale,
            pause_on_overlay=_bool_or_default(
                self.pause_on_overlay,
                defaults.pause_on_overlay,
            ),
            show_ticker=_bool_or_default(self.show_ticker, defaults.show_ticker),
            show_weather_layer=_bool_or_default(
                self.show_weather_layer,
                defaults.show_weather_layer,
            ),
            confirm_exit=_bool_or_default(self.confirm_exit, defaults.confirm_exit),
            fullscreen=_bool_or_default(self.fullscreen, defaults.fullscreen),
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> DisplaySettings:
        """Build settings from an untrusted mapping, falling back per field."""
        if not isinstance(data, Mapping):
            return cls()
        values = dict(data)
        return cls(
            palette=_palette_or_default(values.get("palette")),
            font_scale=_scale_or_default(values.get("font_scale")),
            pause_on_overlay=_bool_or_default(
                values.get("pause_on_overlay"),
                False,
            ),
            show_ticker=_bool_or_default(values.get("show_ticker"), True),
            show_weather_layer=_bool_or_default(
                values.get("show_weather_layer"),
                True,
            ),
            confirm_exit=_bool_or_default(values.get("confirm_exit"), True),
            fullscreen=_bool_or_default(values.get("fullscreen"), False),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation of the settings."""
        return {
            "palette": str(self.palette),
            "font_scale": self.font_scale,
            "pause_on_overlay": self.pause_on_overlay,
            "show_ticker": self.show_ticker,
            "show_weather_layer": self.show_weather_layer,
            "confirm_exit": self.confirm_exit,
            "fullscreen": self.fullscreen,
        }

    def toggled_palette(self) -> DisplaySettings:
        return replace(self, palette=self.palette.toggled())

    def cycled_font_scale(self) -> DisplaySettings:
        next_scale = self.font_scale + 1
        if next_scale > MAX_FONT_SCALE:
            next_scale = MIN_FONT_SCALE
        return replace(self, font_scale=next_scale)

    def toggled_pause_on_overlay(self) -> DisplaySettings:
        return replace(self, pause_on_overlay=not self.pause_on_overlay)

    def toggled_ticker(self) -> DisplaySettings:
        return replace(self, show_ticker=not self.show_ticker)

    def toggled_weather_layer(self) -> DisplaySettings:
        return replace(self, show_weather_layer=not self.show_weather_layer)

    def toggled_confirm_exit(self) -> DisplaySettings:
        return replace(self, confirm_exit=not self.confirm_exit)

    def toggled_fullscreen(self) -> DisplaySettings:
        return replace(self, fullscreen=not self.fullscreen)


def _palette_or_default(value: object) -> Palette:
    if isinstance(value, Palette):
        return value
    if isinstance(value, str):
        try:
            return Palette(value)
        except ValueError:
            return Palette.NORMAL
    return Palette.NORMAL


def _scale_or_default(value: object) -> int:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and MIN_FONT_SCALE <= value <= MAX_FONT_SCALE
    ):
        return value
    return MIN_FONT_SCALE


def _bool_or_default(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default
