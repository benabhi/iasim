"""IASim protocol identity and compatibility expectations.

``PROTOCOL_VERSION`` identifies the agent-facing contract: the tool catalog,
its argument schemas, and the observation shape. An incompatible change to any
of them must increase the major part of the version and bump the observation
``schema_version``; the MVP only speaks ``iasim-mcp/1.0``.
"""

PROTOCOL_VERSION = "iasim-mcp/1.0"
MAX_PROTOCOL_VERSION_LENGTH = 32
