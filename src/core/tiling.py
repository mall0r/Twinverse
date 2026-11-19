"""Pure, connector-keyed per-monitor tiling, independent of profile models."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TilingTemplate:
    """Named layout containing proportional rectangles for one monitor."""

    id: str
    title: str
    rectangles: tuple[tuple[float, float, float, float], ...]

    @property
    def capacity(self) -> int:
        """Return the number of available player rectangles."""
        return len(self.rectangles)


TEMPLATES: dict[str, TilingTemplate] = {
    template.id: template
    for template in (
        TilingTemplate("fullscreen", "Fullscreen", ((0, 0, 1, 1),)),
        TilingTemplate("columns", "Columns", ((0, 0, 0.5, 1), (0.5, 0, 0.5, 1))),
        TilingTemplate("rows", "Rows", ((0, 0, 1, 0.5), (0, 0.5, 1, 0.5))),
        TilingTemplate("main-left", "Main left", ((0, 0, 0.5, 1), (0.5, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5))),
        TilingTemplate("main-top", "Main top", ((0, 0, 1, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5))),
        TilingTemplate(
            "grid", "Grid", ((0, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5))
        ),
    )
}


@dataclass
class MonitorPlan:
    """Resolved template and player slots for a connected monitor."""

    key: str
    index: int
    display: dict
    template: TilingTemplate
    players: list[int | None]


@dataclass
class TilingPlan:
    """Connected monitor placements and instances exceeding their capacity."""

    monitors: list[MonitorPlan]
    unassigned: list[int]


def monitor_key(display: Mapping[str, Any], index: int) -> str:
    """Use the connector identity, falling back to the physical display ID."""
    return display.get("name") or f"monitor-{display.get('id', index)}"


def build_tiling_plan(instances: list[int], displays: Sequence[Mapping[str, Any]], monitor_layouts: dict) -> TilingPlan:
    """Reserve connected explicit assignments first, then fill holes in display order.

    Stale/excluded and repeated assignments are ignored. Overflow is never placed
    on another player's rectangle. All returned mutable containers are new.
    """
    selected = list(dict.fromkeys(instances))
    selected_set = set(selected)
    claimed = set()
    monitors = []
    ordered = sorted(enumerate(displays), key=lambda item: item[1].get("id", item[0]))
    for index, (_, display) in enumerate(ordered):
        key = monitor_key(display, index)
        config = monitor_layouts.get(key, {})
        template_id = config.get("template", "fullscreen") if isinstance(config, dict) else config.template
        saved = config.get("players", []) if isinstance(config, dict) else config.players
        template = TEMPLATES[template_id]
        players: list[int | None] = [None] * template.capacity
        for slot, player in enumerate(saved[: template.capacity]):
            if type(player) is int and player in selected_set and player not in claimed:
                players[slot] = player
                claimed.add(player)
        monitors.append(MonitorPlan(key, index, dict(display), template, players))
    remaining = iter(player for player in selected if player not in claimed)
    for monitor in monitors:
        for slot, player in enumerate(monitor.players):
            if player is None:
                monitor.players[slot] = next(remaining, None)
    return TilingPlan(monitors, list(remaining))
