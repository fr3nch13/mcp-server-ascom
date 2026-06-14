"""
ASCOM MCP Server - Control astronomy equipment through AI.

A modern Model Context Protocol (MCP) server implementing the 2025-06-18 specification
for controlling ASCOM Alpaca-compatible astronomy equipment.

Features:
- Auto-discovery of ASCOM devices on the network
- Structured tool outputs for rich data representation
- Optional OAuth 2.0 security integration
- Future-ready architecture for multi-agent orchestration
- Natural language astronomy targeting (e.g., "Point at M31")
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("mcp-server-ascom")
except PackageNotFoundError:
    # Fallback for development when package is not installed
    __version__ = "0.5.0"

from .server_fastmcp import create_server

__all__ = ["create_server", "__version__"]
