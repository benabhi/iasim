"""Process exit codes and shared runtime exceptions."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Documented process exit codes from SRS section 7.2."""

    SUCCESS = 0
    CONFIGURATION = 1
    WORLD_GENERATION = 2
    MCP = 3
    PERSISTENCE = 4
    INTERNAL = 5


class IasimError(Exception):
    """Base class for errors that map to a documented exit code."""

    exit_code: ExitCode = ExitCode.INTERNAL


class ConfigurationError(IasimError):
    """Invalid command-line or configuration input."""

    exit_code = ExitCode.CONFIGURATION


class WorldGenerationError(IasimError):
    """The configured world could not be generated."""

    exit_code = ExitCode.WORLD_GENERATION


class WorldValidationError(WorldGenerationError):
    """A generated map failed the SRS validation rules."""


class McpError(IasimError):
    """The MCP transport could not start or failed fatally."""

    exit_code = ExitCode.MCP


class PersistenceError(IasimError):
    """A session could not be created, loaded, saved, or replayed."""

    exit_code = ExitCode.PERSISTENCE
