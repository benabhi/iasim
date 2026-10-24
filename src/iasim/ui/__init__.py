"""Operator UI rendering."""

from __future__ import annotations

from iasim.ui.controls import KEY_GUIDE, UiCommand, UiState, UiView, handle_key
from iasim.ui.events import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    PAGE_SIZE,
    EventRow,
    filter_events,
)
from iasim.ui.inspection import describe_position
from iasim.ui.layout import (
    BaseScreen,
    Cell,
    render_agent_screen,
    render_base_screen,
    render_events_screen,
    render_help_screen,
    render_map_screen,
    render_metrics_screen,
    render_replay_screen,
    render_settings_screen,
    render_world_screen,
)
from iasim.ui.panel import PANEL_TABS, TAB_LABELS, PanelState, RightPanelTab
from iasim.ui.settings import PALETTE_LABELS, DisplaySettings, Palette

__all__ = [
    "CATEGORY_LABELS",
    "CATEGORY_ORDER",
    "KEY_GUIDE",
    "PAGE_SIZE",
    "PALETTE_LABELS",
    "PANEL_TABS",
    "TAB_LABELS",
    "BaseScreen",
    "Cell",
    "DisplaySettings",
    "EventRow",
    "Palette",
    "PanelState",
    "RightPanelTab",
    "UiCommand",
    "UiState",
    "UiView",
    "describe_position",
    "filter_events",
    "handle_key",
    "render_agent_screen",
    "render_base_screen",
    "render_events_screen",
    "render_help_screen",
    "render_map_screen",
    "render_metrics_screen",
    "render_replay_screen",
    "render_settings_screen",
    "render_world_screen",
]
