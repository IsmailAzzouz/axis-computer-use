"""Model Context Protocol (MCP) package for AXIS."""
from typing import Any

def __getattr__(name: str) -> Any:
    if name == "MCPServer":
        from cu_suite.mcp.server import MCPServer
        return MCPServer
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = ["MCPServer"]
