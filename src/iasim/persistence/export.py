"""Export the aggregated metrics as ``summary.json`` and ``metrics.csv``.

Both files are written from the same metrics snapshot, so they always agree.
The CSV layout is stable and documented below: one row per agent plus one
session row, with ``scope``, ``agent_id``, ``name`` and a fixed metric column
order. Missing values are written as empty cells, and mapping metrics are
serialized as compact JSON so the CSV stays parseable.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from iasim.protocol import SCHEMA_VERSION

SUMMARY_FILENAME = "summary.json"
METRICS_CSV_FILENAME = "metrics.csv"

# SRS 8.3 order, followed by the numerator/denominator components.
DOCUMENTED_METRICS: tuple[str, ...] = (
    "survival_ticks",
    "days_survived",
    "cause_of_death",
    "killed_by",
    "avg_hunger",
    "avg_thirst",
    "avg_energy",
    "critical_need_ratio",
    "exploration_pct",
    "distance_traveled",
    "resources_gathered",
    "items_crafted",
    "structures_built",
    "actions_total",
    "actions_failed",
    "invalid_action_rate",
    "timeouts",
    "messages_sent",
    "trades_offered",
    "trades_completed",
    "alliances_formed",
    "betrayals",
    "attacks_made",
    "damage_dealt",
    "damage_taken",
    "kills",
    "mind_reports",
    "mind_report_rate",
    "decision_latency_p50_ms",
    "decision_latency_p95_ms",
    "final_state_hash",
)
COMPONENT_COLUMNS: tuple[str, ...] = (
    "critical_need_ticks",
    "alive_ticks",
    "explored_cells",
    "transitable_cells",
    "decision_latency_samples",
    "agent_count",
)
METRIC_COLUMNS: tuple[str, ...] = (*DOCUMENTED_METRICS, *COMPONENT_COLUMNS)
CSV_COLUMNS: tuple[str, ...] = ("scope", "agent_id", "name", *METRIC_COLUMNS)


def write_summary(directory: Path, snapshot: Mapping[str, Any]) -> Path:
    """Write ``summary.json`` atomically from one metrics snapshot."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SUMMARY_FILENAME
    document = {"schema_version": SCHEMA_VERSION, **snapshot}
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OSError(f"cannot write {path}: {exc}") from exc
    return path


def write_metrics_csv(directory: Path, snapshot: Mapping[str, Any]) -> Path:
    """Write ``metrics.csv`` atomically from the same metrics snapshot."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / METRICS_CSV_FILENAME
    temporary = path.with_name(path.name + ".tmp")
    session = snapshot.get("session", {})
    agents = snapshot.get("agents", {})
    rows: list[dict[str, str]] = [_row("session", "", "", session)]
    for agent_id in sorted(agents):
        row = agents[agent_id]
        name = row.get("name") if isinstance(row, Mapping) else None
        rows.append(_row("agent", str(agent_id), "" if name is None else str(name), row))
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(CSV_COLUMNS),
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OSError(f"cannot write {path}: {exc}") from exc
    return path


def _row(scope: str, agent_id: str, name: str, values: Mapping[str, Any]) -> dict[str, str]:
    row: dict[str, str] = {"scope": scope, "agent_id": agent_id, "name": name}
    for column in METRIC_COLUMNS:
        row[column] = _cell(values.get(column))
    return row


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
