"""Presentation-only state for the tabbed right-hand observability panel.

Tabs and scroll offsets never touch the simulation; the operator UI owns them
and passes them to the renderer so the base screen stays a pure function.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

PANEL_STEP = 1
PANEL_PAGE = 10


class RightPanelTab(StrEnum):
    """The four right-panel tabs from SRS 5.3.1."""

    SUMMARY = "resumen"
    EVENTS = "eventos"
    MIND = "mente"
    LINKS = "vinculos"


PANEL_TABS: tuple[RightPanelTab, ...] = (
    RightPanelTab.SUMMARY,
    RightPanelTab.EVENTS,
    RightPanelTab.MIND,
    RightPanelTab.LINKS,
)

TAB_LABELS: dict[RightPanelTab, str] = {
    RightPanelTab.SUMMARY: "RESUMEN",
    RightPanelTab.EVENTS: "EVENTOS",
    RightPanelTab.MIND: "MENTE",
    RightPanelTab.LINKS: "VÍNCULOS",
}


@dataclass(frozen=True, slots=True)
class PanelState:
    """Active tab and scroll offset for the right panel."""

    tab: RightPanelTab = RightPanelTab.SUMMARY
    scroll: int = 0

    def with_tab(self, tab: RightPanelTab) -> PanelState:
        """Return the state focused on one tab with its scroll reset."""
        return replace(self, tab=tab, scroll=0)

    def cycle(self, direction: int) -> PanelState:
        """Return the state on the previous or next tab."""
        index = PANEL_TABS.index(self.tab)
        return self.with_tab(PANEL_TABS[(index + direction) % len(PANEL_TABS)])

    def scrolled(self, delta: int) -> PanelState:
        """Return the state with the scroll offset moved by ``delta``."""
        return replace(self, scroll=max(0, self.scroll + delta))
