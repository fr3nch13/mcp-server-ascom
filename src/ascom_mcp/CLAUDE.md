# ASCOM MCP Core Implementation

## Module Overview
Core implementation of ASCOM device bridging to MCP protocol using FastMCP 2.0.

## Key Components

### `server_fastmcp.py`
- FastMCP 2.0 server with Context pattern
- All tools accept Context as first parameter
- ToolError for recoverable errors
- Structured logging to stderr

### `devices/manager.py`
- Device discovery and connection management
- Simulator auto-detection on port 4700
- Tenacity retry logic (3 attempts)
- DeviceInfo and ConnectedDevice classes

### `config.py`
- Environment configuration
- `ASCOM_KNOWN_DEVICES`: Known device list
- `ASCOM_SIMULATOR_DEVICES`: Simulator devices
- Format: `host:port:name`

### `tools/` directory
- DiscoveryTools, TelescopeTools, CameraTools
- SeestarFileTools - SMB file browsing/download from S30 Pro (pysmb)
- Business logic separated from MCP protocol
- Testable without MCP overhead

### `config.py` — SMB
- `SEESTAR_SMB_PORT` — Port (default: 445)
- `SEESTAR_SMB_SHARE` — Share name (default: "EMMC Images")
- `SEESTAR_SMB_USER` / `SEESTAR_SMB_PASSWORD` — Auth (default: anonymous)
- SMB host derived from first `ASCOM_KNOWN_DEVICES` entry automatically

## Critical Patterns

### FastMCP 2.0 Tool Pattern
```python
@mcp.tool()
async def telescope_connect(ctx: Context, device_id: str) -> dict[str, Any]:
    await ctx.info("connecting_telescope", device_id=device_id)
    try:
        return await telescope_tools.connect(device_id=device_id)
    except Exception as e:
        await ctx.error("telescope_connect_failed", error=str(e))
        raise ToolError(
            f"Cannot connect to telescope '{device_id}': {str(e)}",
            code="connection_failed",
            recoverable=True
        )
```

### Device Discovery Pattern
```python
# Includes UDP broadcast, known devices, and simulators
devices = await device_manager.discover_devices(timeout=5.0)
```

## Performance
- Connection caching in DeviceManager
- HTTP session reuse via aiohttp
- Retry logic with exponential backoff
- Simulator TCP check (2s timeout)

## Common Issues
- **Wrong Python** → Use `.venv/bin/python`
- **Import errors** → Unit tests mock alpaca/alpyca
- **Discovery fails** → Set `ASCOM_SIMULATOR_DEVICES`
- **Connection refused** → Start seestar_alp first

## Debugging
```bash
# Structured logging to stderr
LOG_LEVEL=DEBUG python -m ascom_mcp 2>&1 | jq

# Monitor with multitail
multitail -ci green mcp.log -ci yellow device.log
```