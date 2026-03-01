"""engine.mcp

MCP (Model Context Protocol) integration layer.

Bidirectional MCP support for b1e55ed producers:
- Inbound:  Producers can consume data from MCP servers (MCP-first, REST fallback).
- Outbound: All producer signals exposed via a single b1e55ed MCP server.

External agents (Claude, oracle consumers, agent builders) connect to the MCP server
to subscribe to live producer signals without REST API setup.
"""
