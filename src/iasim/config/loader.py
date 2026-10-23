"""TOML loading, deep override merging, and validation for IASim."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from iasim.config.models import IasimConfig


class ConfigError(ValueError):
    """Raised when configuration cannot be read, parsed, or validated."""

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        prefix = f"{source}: " if source else ""
        super().__init__(f"{prefix}{message}")


def load_config(
    path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> IasimConfig:
    """Load TOML defaults, apply nested CLI overrides, and validate the result.

    A missing path means built-in defaults. CLI overrides take precedence over
    TOML values at any depth. Validation failures identify the source file,
    the offending dotted key, and the violated constraint.
    """
    source = str(path) if path is not None else ("<overrides>" if overrides else "<defaults>")
    data: dict[str, Any] = {}

    if path is not None:
        data = _load_toml(Path(path), source)

    if overrides:
        data = _deep_merge(data, overrides)

    try:
        return IasimConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_errors(exc), source=source) from exc


def _load_toml(path: Path, source: str) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError("configuration file does not exist", source=source)
    if not path.is_file():
        raise ConfigError("configuration path is not a file", source=source)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read configuration file: {exc}", source=source) from exc

    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}", source=source) from exc


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _format_validation_errors(exc: ValidationError) -> str:
    lines: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<config>"
        input_value = error.get("input")
        lines.append(f"  {location}: {error['msg']} (got {input_value!r})")
    return "invalid configuration:\n" + "\n".join(lines)
