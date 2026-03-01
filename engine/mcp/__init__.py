"""engine.mcp

MCP (Model Context Protocol) integration layer.

Bidirectional MCP support for b1e55ed producers:
- Inbound:  Producers can consume data from MCP servers (MCP-first, REST fallback).
- Outbound: All producer signals exposed via a single b1e55ed MCP server.

External agents (Claude, oracle consumers, agent builders) connect to the MCP server
to subscribe to live producer signals without REST API setup.
"""

from engine.mcp.registry import MCPProducerRegistry, get_registry
from engine.mcp.server import MCPServer
from engine.mcp.types import MCPProducerManifest, MCPSignalBuffer, MCPSignalPayload

__all__ = [
    "MCPProducerRegistry",
    "MCPServer",
    "MCPProducerManifest",
    "MCPSignalBuffer",
    "MCPSignalPayload",
    "get_registry",
]
