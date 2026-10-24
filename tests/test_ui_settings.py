"""Tests for the F8 display settings view and F11 fullscreen toggle."""

from __future__ import annotations

import unittest

from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.weather import WeatherKind, WeatherState
from iasim.ui import theme
from iasim.ui.controls import KEY_GUIDE, UiState, UiView, handle_key
from iasim.ui.layout import render_base_screen, render_settings_screen
from iasim.ui.settings import (
    MAX_FONT_SCALE,
    MIN_FONT_SCALE,
    DisplaySettings,
    Palette,
)

NAMES = {AgentId("ag_01"): "Nia"}


def _state(*, weather: WeatherState | None = None) -> SessionState:
    return SessionState(
        seed=1,
        tick=3,
        rng_state=1,
        world=WorldMap(width=4, height=4, tiles=(TileType.GRASS,) * 16),
        weather=weather or WeatherState(),
        agents=(Agent(AgentId("ag_01"), Position(1, 1)),),
    )


class DisplaySettingsValidationTests(unittest.TestCase):
    def test_invalid_fields_fall_back_safely(self) -> None:
        settings = DisplaySettings.from_mapping(
            {
                "palette": "rainbow",
                "font_scale": 99,
                "pause_on_overlay": "yes",
                "show_ticker": None,
                "show_weather_layer": 1,
                "confirm_exit": "no",
                "fullscreen": 0,
            }
        )

        self.assertEqual(settings.palette, Palette.NORMAL)
        self.assertEqual(settings.font_scale, MIN_FONT_SCALE)
        self.assertFalse(settings.pause_on_overlay)
        self.assertTrue(settings.show_ticker)
        self.assertTrue(settings.show_weather_layer)
        self.assertTrue(settings.confirm_exit)
        self.assertFalse(settings.fullscreen)

    def test_normalized_repairs_constructed_invalid_values(self) -> None:
        settings = DisplaySettings(
            palette="bad",  # type: ignore[arg-type]
            font_scale=0,
            pause_on_overlay=1,  # type: ignore[arg-type]
            fullscreen="yes",  # type: ignore[arg-type]
        ).normalized()

        self.assertEqual(settings.palette, Palette.NORMAL)
        self.assertEqual(settings.font_scale, MIN_FONT_SCALE)
        self.assertFalse(settings.pause_on_overlay)
        self.assertFalse(settings.fullscreen)

    def test_mapping_roundtrip(self) -> None:
        settings = DisplaySettings(
            palette=Palette.COLORBLIND,
            font_scale=3,
            pause_on_overlay=True,
            show_ticker=False,
            show_weather_layer=False,
            confirm_exit=False,
            fullscreen=True,
        )

        self.assertEqual(DisplaySettings.from_mapping(settings.as_dict()), settings)

    def test_scale_cycles_inside_its_bounds(self) -> None:
        settings = DisplaySettings()

        for expected in range(MIN_FONT_SCALE + 1, MAX_FONT_SCALE + 1):
            settings = settings.cycled_font_scale()
            self.assertEqual(settings.font_scale, expected)
        self.assertEqual(settings.cycled_font_scale().font_scale, MIN_FONT_SCALE)


class SettingsScreenTests(unittest.TestCase):
    def test_the_settings_view_shows_every_option_and_value(self) -> None:
        settings = DisplaySettings(
            palette=Palette.COLORBLIND,
            font_scale=3,
            pause_on_overlay=True,
            show_ticker=False,
            show_weather_layer=False,
            confirm_exit=False,
            fullscreen=True,
        )

        screen = render_settings_screen(settings)
        text = screen.to_text()

        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
        for expected in (
            "F8 · AJUSTES DE VISUALIZACIÓN",
            "Solo presentación",
            "Paleta:",
            "APTA PARA DALTONISMO",
            "Escala de fuente:",
            "x3",
            "Pausar al abrir overlay:",
            "Mostrar ticker:",
            "Capa de clima por defecto:",
            "Confirmar salida y reinicio:",
            "Pantalla completa:",
            "MUESTRA DE COLORES",
            "Ajustes válidos: escala x1..x4",
            "[F11] Pantalla completa",
            "[ESC/F8] Volver",
        ):
            self.assertIn(expected, text)
        self.assertGreaterEqual(text.count("SÍ"), 2)
        self.assertGreaterEqual(text.count("NO"), 3)

    def test_the_palette_changes_colors_but_not_glyphs(self) -> None:
        normal = render_settings_screen(DisplaySettings())
        colorblind = render_settings_screen(DisplaySettings(palette=Palette.COLORBLIND))

        normal_colors = {cell.fg for cell in normal.cells}
        colorblind_colors = {cell.fg for cell in colorblind.cells}
        self.assertNotEqual(normal_colors, colorblind_colors)
        self.assertIn(theme.CYAN, normal_colors)
        self.assertNotIn(theme.CYAN, colorblind_colors)
        self.assertIn(theme.COLORBLIND_REPLACEMENTS[theme.CYAN], colorblind_colors)
        preview_row = next(y for y in range(45) if "MUESTRA DE COLORES" in normal.row_text(y)) + 1
        self.assertEqual(
            normal.row_text(preview_row),
            colorblind.row_text(preview_row),
        )


class BaseScreenDisplayTests(unittest.TestCase):
    def test_hiding_the_ticker_removes_the_event_panel(self) -> None:
        hidden = render_base_screen(
            _state(),
            NAMES,
            events=("algo",),
            display=DisplaySettings(show_ticker=False),
        )
        shown = render_base_screen(
            _state(),
            NAMES,
            events=("algo",),
            display=DisplaySettings(),
        )

        self.assertNotIn("EVENTOS", hidden.row_text(41))
        self.assertIn("EVENTOS", shown.row_text(41))

    def test_the_default_weather_layer_can_be_disabled(self) -> None:
        weather = WeatherState(kind=WeatherKind.RAIN, remaining_ticks=5, wind=4)
        with_layer = render_base_screen(
            _state(weather=weather),
            NAMES,
            display=DisplaySettings(),
        )
        without_layer = render_base_screen(
            _state(weather=weather),
            NAMES,
            display=DisplaySettings(show_weather_layer=False),
        )

        self.assertNotEqual(with_layer.to_text(), without_layer.to_text())
        self.assertIn(
            theme.WEATHER_RAIN_GLYPH,
            "".join(cell.char for cell in with_layer.cells),
        )

    def test_the_base_screen_uses_the_selected_palette(self) -> None:
        normal = render_base_screen(_state(), NAMES)
        colorblind = render_base_screen(
            _state(),
            NAMES,
            display=DisplaySettings(palette=Palette.COLORBLIND),
        )

        self.assertEqual(normal.to_text(), colorblind.to_text())
        self.assertIn(
            theme.COLORBLIND_REPLACEMENTS[theme.AGENT_COLOR],
            {cell.fg for cell in colorblind.cells},
        )


class DisplayControlTests(unittest.TestCase):
    def test_settings_keys_apply_immediately(self) -> None:
        state = handle_key(UiState(), "f8", ())

        self.assertEqual(state.view, UiView.SETTINGS)
        state = handle_key(state, "p", ())
        self.assertEqual(state.display.palette, Palette.COLORBLIND)
        state = handle_key(state, "s", ())
        self.assertEqual(state.display.font_scale, 2)
        state = handle_key(state, "o", ())
        self.assertTrue(state.display.pause_on_overlay)
        state = handle_key(state, "t", ())
        self.assertFalse(state.display.show_ticker)
        state = handle_key(state, "l", ())
        self.assertFalse(state.display.show_weather_layer)
        state = handle_key(state, "c", ())
        self.assertFalse(state.display.confirm_exit)
        self.assertEqual(handle_key(state, "esc", ()).view, UiView.NONE)

    def test_pause_on_overlay_applies_when_opening_a_view(self) -> None:
        disabled = handle_key(UiState(), "f3", ())
        self.assertFalse(disabled.paused)

        settings = DisplaySettings(pause_on_overlay=True)
        enabled = handle_key(UiState(display=settings), "f3", ())
        self.assertTrue(enabled.paused)
        self.assertEqual(enabled.view, UiView.WORLD_SUMMARY)
        self.assertTrue(handle_key(enabled, "esc", ()).paused)

    def test_f11_toggles_fullscreen(self) -> None:
        state = handle_key(UiState(), "f11", ())

        self.assertTrue(state.display.fullscreen)
        self.assertFalse(handle_key(state, "f11", ()).display.fullscreen)

    def test_exit_confirmation_can_be_disabled(self) -> None:
        confirmed = handle_key(UiState(), "q", ())
        self.assertIsNotNone(confirmed.pending_confirmation)

        settings = DisplaySettings(confirm_exit=False)
        immediate = handle_key(UiState(display=settings), "q", ())
        self.assertTrue(immediate.quit_requested)
        self.assertIsNone(immediate.pending_confirmation)
        restarted = handle_key(UiState(display=settings), "r", ())
        self.assertTrue(restarted.restart_requested)

    def test_key_guide_mentions_display_settings_and_fullscreen(self) -> None:
        keys = {key for key, _ in KEY_GUIDE}

        self.assertTrue({"F8", "F11"} <= keys)


if __name__ == "__main__":
    unittest.main()
