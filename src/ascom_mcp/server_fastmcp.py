#!/usr/bin/env python3
"""
ASCOM MCP Server implemented with FastMCP from the official SDK.

This is a cleaner, more maintainable implementation compared to the low-level API.
FastMCP is now the recommended approach for MCP servers in Python.
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from . import __version__
from .ascom_logging import StructuredLogger
from .config import config
from .devices.manager import DeviceManager
from .devices.seestar_event_bridge import SeestarEventBridge
from .resources.event_stream import EventStreamManager
from .tools.camera import CameraTools
from .tools.discovery import DiscoveryTools
from .tools.events import EventTools
from .tools.files import seestar_file_tools
from .tools.telescope import TelescopeTools

# Structured logger (logs to stderr per MCP spec)
logger = StructuredLogger("ascom.server")

# Create the FastMCP server
mcp = FastMCP("ASCOM MCP Server")

# Global device manager (initialized at startup)
device_manager: DeviceManager | None = None
event_manager: EventStreamManager | None = None
event_bridge: SeestarEventBridge | None = None
discovery_tools: DiscoveryTools | None = None
telescope_tools: TelescopeTools | None = None
camera_tools: CameraTools | None = None
event_tools: EventTools | None = None


# Server lifecycle management
@asynccontextmanager
async def server_lifespan(server: FastMCP):
    """Manage server startup and shutdown."""
    global device_manager, event_manager, event_bridge, discovery_tools, telescope_tools, camera_tools, event_tools

    logger.info(f"Starting ASCOM MCP Server v{__version__} (FastMCP)")

    # Initialize device manager and tools
    device_manager = DeviceManager()
    await device_manager.initialize()

    event_manager = EventStreamManager()
    event_bridge = SeestarEventBridge(event_manager)
    event_bridge.setup_event_loop()  # Capture asyncio event loop for sync->async bridge

    # Register event callbacks
    device_manager.register_event_callback(
        "on_device_connected", event_bridge.connect_to_seestar
    )

    discovery_tools = DiscoveryTools(device_manager)
    telescope_tools = TelescopeTools(device_manager)
    camera_tools = CameraTools(device_manager)
    event_tools = EventTools(device_manager, event_manager)

    logger.info("ASCOM MCP Server initialized successfully")

    try:
        yield
    finally:
        # Cleanup on shutdown
        logger.info("Shutting down ASCOM MCP Server")
        if device_manager:
            await device_manager.shutdown()
        # Close SMB connection if open
        try:
            await seestar_file_tools._ensure_disconnected()
        except Exception:
            pass
        logger.info("Server shutdown complete")


async def ensure_initialized():
    """Ensure all global tools are initialized."""
    global device_manager, event_manager, event_bridge, discovery_tools, telescope_tools, camera_tools, event_tools

    if device_manager is None:
        device_manager = DeviceManager()
        await device_manager.initialize()

    if event_manager is None:
        event_manager = EventStreamManager()

    if event_bridge is None:
        event_bridge = SeestarEventBridge(event_manager)
        event_bridge.setup_event_loop()  # Capture asyncio event loop
        # Register event callbacks
        device_manager.register_event_callback(
            "on_device_connected", event_bridge.connect_to_seestar
        )

    if discovery_tools is None:
        discovery_tools = DiscoveryTools(device_manager)

    if telescope_tools is None:
        telescope_tools = TelescopeTools(device_manager)

    if camera_tools is None:
        camera_tools = CameraTools(device_manager)

    if event_tools is None:
        event_tools = EventTools(device_manager, event_manager)


# Discovery tools
@mcp.tool()
async def discover_ascom_devices(ctx: Context, timeout: float = 5.0) -> dict[str, Any]:
    """Discover ASCOM devices on the network.

    Args:
        ctx: FastMCP context for logging and request metadata
        timeout: Discovery timeout in seconds (default: 5.0)

    Returns:
        Dictionary with discovered devices
    """
    await ensure_initialized()

    await ctx.debug(f"tool_called: discover_ascom_devices with timeout={timeout}")
    try:
        result = await discovery_tools.discover_devices(timeout=timeout)
        await ctx.info(f"devices_discovered: count={result.get('count', 0)}")
        return result
    except Exception as e:
        await ctx.error(f"discovery_failed: {str(e)}")
        raise ToolError(
            f"Device discovery failed: {str(e)}",
            code="discovery_failed",
            recoverable=True,
            details={
                "suggestions": [
                    "Check network connectivity",
                    "Ensure devices are powered on",
                ]
            },
        )


@mcp.tool()
async def get_device_info(ctx: Context, device_id: str) -> dict[str, Any]:
    """Get detailed information about a specific ASCOM device.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Device ID from discovery

    Returns:
        Device information dictionary
    """
    await ensure_initialized()
    await ctx.info(f"getting_device_info: device_id={device_id}")
    try:
        return await discovery_tools.get_device_info(device_id=device_id)
    except Exception as e:
        await ctx.error(f"device_info_failed: device_id={device_id}, error={str(e)}")
        raise ToolError(
            f"Cannot get info for device '{device_id}': {str(e)}",
            code="device_not_found",
            recoverable=True,
        )


# Telescope tools
@mcp.tool()
async def telescope_connect(ctx: Context, device_id: str) -> dict[str, Any]:
    """Connect to an ASCOM telescope.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Device ID from discovery

    Returns:
        Connection status dictionary
    """
    await ensure_initialized()
    await ctx.info(f"connecting_telescope: device_id={device_id}")
    try:
        return await telescope_tools.connect(device_id=device_id)
    except Exception as e:
        await ctx.error(
            f"telescope_connect_failed: device_id={device_id}, error={str(e)}"
        )
        raise ToolError(
            f"Cannot connect to telescope '{device_id}': {str(e)}",
            code="connection_failed",
            recoverable=True,
            details={
                "suggestions": [
                    "Check if seestar_alp is running (python root_app.py)",
                    "Try using simulator mode",
                    "Verify device ID from discovery",
                ]
            },
        )


@mcp.tool()
async def telescope_disconnect(ctx: Context, device_id: str) -> dict[str, Any]:
    """Disconnect from an ASCOM telescope.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Connected telescope device ID

    Returns:
        Disconnection status dictionary
    """
    await ensure_initialized()
    await ctx.info(f"disconnecting_telescope: device_id={device_id}")
    try:
        return await telescope_tools.disconnect(device_id=device_id)
    except Exception as e:
        await ctx.error(
            f"telescope_disconnect_failed: device_id={device_id}, error={str(e)}"
        )
        raise ToolError(
            f"Cannot disconnect telescope '{device_id}': {str(e)}",
            code="disconnect_failed",
            recoverable=True,
        )


@mcp.tool()
async def telescope_goto(
    ctx: Context, device_id: str, ra: float, dec: float
) -> dict[str, Any]:
    """Slew telescope to specific coordinates.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Connected telescope device ID
        ra: Right Ascension in hours (0-24)
        dec: Declination in degrees (-90 to +90)

    Returns:
        Slew status dictionary
    """
    await ensure_initialized()
    await ctx.info(f"telescope_goto: device_id={device_id}, ra={ra}, dec={dec}")
    try:
        return await telescope_tools.goto(device_id=device_id, ra=ra, dec=dec)
    except Exception as e:
        await ctx.error(f"telescope_goto_failed: device_id={device_id}, error={str(e)}")
        raise ToolError(
            f"Cannot slew telescope: {str(e)}", code="slew_failed", recoverable=True
        )


@mcp.tool()
async def telescope_goto_object(
    ctx: Context, device_id: str, object_name: str
) -> dict[str, Any]:
    """Slew telescope to a named celestial object.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Connected telescope device ID
        object_name: Name of celestial object (e.g., 'M31', 'Orion Nebula')

    Returns:
        Slew status dictionary
    """
    await ensure_initialized()
    await ctx.info(
        f"telescope_goto_object: device_id={device_id}, object={object_name}"
    )
    try:
        return await telescope_tools.goto_object(
            device_id=device_id, object_name=object_name
        )
    except Exception as e:
        await ctx.error(
            f"telescope_goto_object_failed: device_id={device_id}, object={object_name}, error={str(e)}"
        )
        raise ToolError(
            f"Cannot slew to object '{object_name}': {str(e)}",
            code="object_lookup_failed",
            recoverable=True,
            details={
                "suggestions": [
                    "Check object name spelling",
                    "Try catalog designation (e.g., M31, NGC 224)",
                ]
            },
        )


@mcp.tool()
async def telescope_get_position(ctx: Context, device_id: str) -> dict[str, Any]:
    """Get current telescope position.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Connected telescope device ID

    Returns:
        Position information dictionary
    """
    await ensure_initialized()
    await ctx.debug(f"getting_telescope_position: device_id={device_id}")
    try:
        return await telescope_tools.get_position(device_id=device_id)
    except Exception as e:
        await ctx.error(f"get_position_failed: device_id={device_id}, error={str(e)}")
        raise ToolError(
            f"Cannot get telescope position: {str(e)}",
            code="position_read_failed",
            recoverable=True,
        )


@mcp.tool()
async def telescope_park(ctx: Context, device_id: str) -> dict[str, Any]:
    """Park telescope at home position.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Connected telescope device ID

    Returns:
        Park status dictionary
    """
    await ensure_initialized()
    await ctx.info(f"parking_telescope: device_id={device_id}")
    try:
        return await telescope_tools.park(device_id=device_id)
    except Exception as e:
        await ctx.error(f"telescope_park_failed: device_id={device_id}, error={str(e)}")
        raise ToolError(
            f"Cannot park telescope: {str(e)}", code="park_failed", recoverable=True
        )


@mcp.tool()
async def telescope_custom_action(
    ctx: Context,
    device_id: str,
    action: str,
    parameters: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute custom ASCOM action (e.g., Seestar-specific commands).

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Connected telescope device ID
        action: Action name (e.g., 'method_sync', 'goto_preset')
        parameters: Action parameters as JSON string or dict (varies by action)

    Returns:
        Action result dictionary

    Examples:
        # Seestar focus control
        telescope_custom_action(device_id, "method_sync",
            '{"method": "get_focuser_position"}')

        # Seestar movement
        telescope_custom_action(device_id, "method_sync",
            '{"method": "scope_speed_move", "params": {"speed": 300, "angle": 90, "dur_sec": 3}}')
    """
    await ensure_initialized()
    await ctx.info(f"telescope_custom_action: device_id={device_id}, action={action}")

    # Handle string parameters (workaround for MCP/Claude JSON serialization issue)
    if isinstance(parameters, str):
        try:
            import json

            parameters = json.loads(parameters)
            await ctx.debug("Parsed string parameters to dict")
        except json.JSONDecodeError as e:
            await ctx.error(f"Invalid JSON in parameters: {e}")
            raise ToolError(
                f"Invalid JSON in parameters: {e}",
                code="invalid_json",
                recoverable=True,
            )

    try:
        return await telescope_tools.custom_action(
            device_id=device_id, action=action, parameters=parameters
        )
    except Exception as e:
        await ctx.error(
            f"custom_action_failed: device_id={device_id}, action={action}, error={str(e)}"
        )
        raise ToolError(
            f"Custom action '{action}' failed: {str(e)}",
            code="custom_action_failed",
            recoverable=True,
        )


# Camera tools
@mcp.tool()
async def camera_connect(ctx: Context, device_id: str) -> dict[str, Any]:
    """Connect to an ASCOM camera.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Device ID from discovery

    Returns:
        Connection status dictionary
    """
    await ensure_initialized()
    await ctx.info(f"connecting_camera: device_id={device_id}")
    try:
        return await camera_tools.connect(device_id=device_id)
    except Exception as e:
        await ctx.error(f"camera_connect_failed: device_id={device_id}, error={str(e)}")
        raise ToolError(
            f"Cannot connect to camera '{device_id}': {str(e)}",
            code="connection_failed",
            recoverable=True,
        )


@mcp.tool()
async def camera_capture(
    ctx: Context, device_id: str, exposure_seconds: float, light_frame: bool = True
) -> dict[str, Any]:
    """Capture an image with the camera.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Connected camera device ID
        exposure_seconds: Exposure time in seconds
        light_frame: True for light frame, False for dark (default: True)

    Returns:
        Capture result dictionary
    """
    await ensure_initialized()
    await ctx.info(
        f"camera_capture: device_id={device_id}, exposure={exposure_seconds}, light_frame={light_frame}"
    )
    try:
        return await camera_tools.capture(
            device_id=device_id,
            exposure_seconds=exposure_seconds,
            light_frame=light_frame,
        )
    except Exception as e:
        await ctx.error(f"camera_capture_failed: device_id={device_id}, error={str(e)}")
        raise ToolError(
            f"Camera capture failed: {str(e)}", code="capture_failed", recoverable=True
        )


@mcp.tool()
async def camera_get_status(ctx: Context, device_id: str) -> dict[str, Any]:
    """Get current camera status.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Connected camera device ID

    Returns:
        Camera status dictionary
    """
    await ensure_initialized()
    await ctx.debug(f"getting_camera_status: device_id={device_id}")
    try:
        return await camera_tools.get_status(device_id=device_id)
    except Exception as e:
        await ctx.error(f"camera_status_failed: device_id={device_id}, error={str(e)}")
        raise ToolError(
            f"Cannot get camera status: {str(e)}",
            code="status_read_failed",
            recoverable=True,
        )


# Event tools
@mcp.tool()
async def get_event_history(
    ctx: Context,
    device_id: str,
    count: int = 50,
    event_types: list[str] | None = None,
    since_timestamp: float | None = None,
) -> dict[str, Any]:
    """Get historical events for a device.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Device identifier
        count: Maximum number of events to return (default: 50)
        event_types: Filter by specific event types
        since_timestamp: Get events after this Unix timestamp

    Returns:
        Event history and metadata
    """
    await ensure_initialized()
    await ctx.info(f"getting_event_history: device_id={device_id}, count={count}")
    try:
        return await event_tools.get_event_history(
            device_id=device_id,
            count=count,
            event_types=event_types,
            since_timestamp=since_timestamp,
        )
    except Exception as e:
        await ctx.error(
            f"get_event_history_failed: device_id={device_id}, error={str(e)}"
        )
        raise ToolError(
            f"Cannot get event history: {str(e)}",
            code="event_history_failed",
            recoverable=True,
        )


@mcp.tool()
async def clear_event_history(ctx: Context, device_id: str) -> dict[str, Any]:
    """Clear event history for a device.

    Args:
        ctx: FastMCP context for logging and request metadata
        device_id: Device identifier

    Returns:
        Operation result
    """
    await ensure_initialized()
    await ctx.info(f"clearing_event_history: device_id={device_id}")
    try:
        return await event_tools.clear_event_history(device_id=device_id)
    except Exception as e:
        await ctx.error(
            f"clear_event_history_failed: device_id={device_id}, error={str(e)}"
        )
        raise ToolError(
            f"Cannot clear event history: {str(e)}",
            code="clear_history_failed",
            recoverable=True,
        )


@mcp.tool()
async def get_event_types(ctx: Context) -> dict[str, Any]:
    """Get available event types and descriptions.

    Args:
        ctx: FastMCP context for logging and request metadata

    Returns:
        Dictionary of event types and their descriptions
    """
    await ensure_initialized()
    await ctx.debug("getting_event_types")
    try:
        return await event_tools.get_event_types()
    except Exception as e:
        await ctx.error(f"get_event_types_failed: error={str(e)}")
        raise ToolError(
            f"Cannot get event types: {str(e)}",
            code="event_types_failed",
            recoverable=True,
        )


# Resources
@mcp.resource("ascom://health")
async def health_check() -> str:
    """Health check endpoint with device and simulator status."""
    await ensure_initialized()

    health_data = {
        "status": "healthy",
        "version": __version__,
        "server": "ASCOM MCP Server",
        "implementation": "FastMCP 2.0",
        "devices": {
            "available": (
                len(device_manager._available_devices) if device_manager else 0
            ),
            "connected": (
                len(device_manager._connected_devices) if device_manager else 0
            ),
        },
        "known_devices": [
            {"host": host, "port": port, "name": name}
            for host, port, name in config.known_devices
        ],
        "simulator_status": "Check ASCOM_SIMULATOR_DEVICES env var for simulator configuration",
    }
    return json.dumps(health_data, indent=2)


@mcp.resource("ascom://server/info")
async def get_server_info() -> str:
    """Information about the ASCOM MCP server."""
    info = {
        "name": "ascom-mcp-server",
        "version": __version__,
        "description": "MCP server for ASCOM astronomy equipment control",
        "ascom_version": "Alpaca v1.0",
        "implementation": "FastMCP",
        "capabilities": [
            "telescope",
            "camera",
            "focuser",
            "filterwheel",
            "dome",
            "rotator",
        ],
    }
    return json.dumps(info, indent=2)


# Seestar file tools
@mcp.tool()
async def seestar_list_files(ctx: Context, path: str = "/") -> dict[str, Any]:
    """List files and directories on the Seestar's internal storage.

    Browse images captured by the Seestar S30 Pro. Files are organized
    in date-based directories (e.g., "/2025-08-01/").

    Args:
        ctx: FastMCP context for logging and request metadata
        path: Directory path within the EMMC Images share (default: "/")

    Returns:
        Directory listing with files and subdirectories
    """
    await ctx.info(f"listing_files: path={path}")
    try:
        return await seestar_file_tools.list_files(path=path)
    except Exception as e:
        await ctx.error(f"list_files_failed: {str(e)}")
        raise ToolError(
            f"Cannot list files: {str(e)}",
            code="list_files_failed",
            recoverable=True,
            details={
                "suggestions": [
                    "Ensure Seestar is on the network",
                    "Check SMB port 445 is open",
                    "Try listing root path '/'",
                ]
            },
        )


@mcp.tool()
async def seestar_download_file(ctx: Context, path: str) -> dict[str, Any]:
    """Download a file from the Seestar's internal storage.

    Retrieves FITS, JPG, or other files from the telescope and saves
    them locally. Supports all file types the Seestar captures.

    Args:
        ctx: FastMCP context for logging and request metadata
        path: Path to the file within the EMMC Images share
              (e.g., "/2025-08-01/M42_light_30s.fits")

    Returns:
        File metadata and local save path
    """
    await ctx.info(f"downloading_file: path={path}")
    try:
        return await seestar_file_tools.download_file(path=path)
    except Exception as e:
        await ctx.error(f"download_file_failed: {str(e)}")
        raise ToolError(
            f"Cannot download file: {str(e)}", code="download_failed", recoverable=True
        )


@mcp.tool()
async def seestar_storage_info(ctx: Context) -> dict[str, Any]:
    """Get storage overview from the Seestar's internal storage.

    Returns a summary of observation sessions (organized by date)
    and file counts for each session.

    Args:
        ctx: FastMCP context for logging and request metadata

    Returns:
        Storage info with session directories and file counts
    """
    await ctx.info("getting_storage_info")
    try:
        return await seestar_file_tools.get_storage_info()
    except Exception as e:
        await ctx.error(f"storage_info_failed: {str(e)}")
        raise ToolError(
            f"Cannot get storage info: {str(e)}",
            code="storage_info_failed",
            recoverable=True,
        )


@mcp.resource("ascom://devices/connected")
async def get_connected_devices() -> str:
    """List of currently connected ASCOM devices."""
    if device_manager:
        devices = await device_manager.get_connected_devices()
        return json.dumps({"devices": devices}, indent=2)
    return json.dumps({"devices": []}, indent=2)


@mcp.resource("ascom://devices/available")
async def get_available_devices() -> str:
    """List of available ASCOM devices from discovery."""
    if device_manager:
        devices = await device_manager.get_available_devices()
        return json.dumps({"devices": devices}, indent=2)
    return json.dumps({"devices": []}, indent=2)


@mcp.resource("ascom://events/{device_id}/stream")
async def get_event_stream(device_id: str, ctx: Context) -> str:
    """Get the current event stream for a device.

    This resource provides the latest events from an ASCOM device.
    The resource will be automatically updated when new events arrive,
    triggering notifications to subscribed clients.

    Args:
        device_id: Device identifier
        ctx: FastMCP context

    Returns:
        JSON with current event state and recent events
    """
    await ensure_initialized()

    try:
        # Get current events (last 50 by default)
        events = await event_manager.get_events(device_id, limit=50)

        # Add server metadata
        events["server_time"] = time.time()
        events["resource_uri"] = f"ascom://events/{device_id}/stream"

        return json.dumps(events, indent=2)

    except Exception as e:
        logger.error(f"Failed to get event stream: {e}")
        return json.dumps(
            {"device_id": device_id, "status": "error", "error": str(e), "events": []},
            indent=2,
        )


def create_server():
    """Create and return the ASCOM MCP server instance.

    This function exists for compatibility with the existing API.
    """
    return mcp


def run():
    """Synchronous wrapper for entry point."""
    import argparse

    # Handle command line arguments
    parser = argparse.ArgumentParser(
        description="ASCOM MCP Server - Control astronomy equipment through AI"
    )
    parser.add_argument(
        "--version", action="version", version=f"mcp-server-ascom {__version__}"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=os.getenv("LOG_LEVEL", "INFO"),
        help="Set logging level",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="Port for HTTP transports (default: 3000)",
    )

    args = parser.parse_args()

    # Update logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Set lifespan
    mcp.lifespan = server_lifespan

    # Log startup
    logger.info("server_starting", transport=args.transport, log_level=args.log_level)

    # Run the server
    if args.transport == "stdio":
        logger.debug("Starting stdio transport")
        try:
            logger.debug("Calling mcp.run()...")
            mcp.run(transport="stdio")
            logger.debug("mcp.run() returned")
        except Exception as e:
            logger.error("Error running stdio transport", error=str(e))
            import traceback

            traceback.print_exc()
    elif args.transport == "sse":
        logger.debug(f"Starting SSE transport on port {args.port}")
        mcp.run(transport="sse", port=args.port)
    elif args.transport == "streamable-http":
        logger.debug(f"Starting streamable-http transport on port {args.port}")
        mcp.run(transport="streamable-http", port=args.port)


if __name__ == "__main__":
    run()
