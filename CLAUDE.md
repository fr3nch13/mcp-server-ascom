# CLAUDE.md - ASCOM MCP Server (v0.5.0)

Bridge ASCOM devices to Claude via MCP. **Now with instant connections!**

## Quick Start

```bash
# Activate venv
source .venv/bin/activate

# Run server
python -m ascom_mcp

# Run tests
pytest tests/unit/ -v         # Unit tests (55+ passing ✅)
pytest tests/integration/ -v  # Integration tests
pytest tests/mcp/ -v          # MCP protocol tests
```

## Architecture

Our server is a "USB cable" between MCP and ASCOM:

```
Claude → MCP Protocol → Our Server → HTTP/Alpaca → seestar_alp → Telescope
         (FastMCP 2.0)    (Translation)   (ASCOM)     (Community)   (Hardware)
             ↑                ↓
             └── Event Stream ←── Real-time events from devices (v0.4.0)
```

## FastMCP 2.0 Patterns

### 1. Context Parameter (Required)
```python
@mcp.tool()
async def telescope_goto(ctx: Context, device_id: str, ra: float, dec: float):
    await ctx.info(f"Slewing to RA={ra}, Dec={dec}")  # Direct logging
    # NOT ctx.logger.info() - that's wrong!
```

### 2. ToolError for User-Friendly Errors
```python
raise ToolError(
    "Device not found. Run discovery first.",
    code="device_not_found",
    recoverable=True,
    details={"suggestions": ["Try: discover_ascom_devices"]}
)
```

### 3. Structured Logging
```python
await ctx.debug("tool_called: telescope_goto")
await ctx.info(f"connected: device_id={device_id}")
await ctx.error(f"failed: {str(e)}")
```

## Key Commands (v0.4.0 IoT Patterns)

### Direct Connection (No Discovery Required!)
```python
# Connect instantly with connection string
telescope_connect(device_id="seestar@192.168.1.100:5555")

# Or use pre-configured device
telescope_connect(device_id="telescope_1")

# Discovery only when adding new devices
discover_ascom_devices(timeout=5.0)  # Optional!

# Initialize telescope (CRITICAL for Seestar!)
telescope_custom_action(
    device_id="Telescope_0",
    action="action_start_up_sequence",
    parameters={"lat": 40.745, "lon": -74.0256, "move_arm": True}
)
```

### Basic Operations
```python
# Go to coordinates
telescope_goto(device_id="Telescope_0", ra=5.5, dec=-5.0)

# Go to object
telescope_goto_object(device_id="Telescope_0", object_name="M31")

# Get position
telescope_get_position(device_id="Telescope_0")

# Park telescope
telescope_park(device_id="Telescope_0")
```

### Seestar-Specific
```python
# Movement (counterintuitive!)
# North/South = horizontal pan, East/West = vertical tilt
telescope_custom_action(
    device_id="Telescope_0",
    action="method_sync",
    parameters={
        "method": "scope_speed_move",
        "params": {"speed": 400, "angle": 180, "dur_sec": 3}  # South = pan north
    }
)

# View modes
telescope_custom_action(
    device_id="Telescope_0", 
    action="method_sync",
    parameters={
        "method": "iscope_start_view",
        "params": {"mode": "scenery"}  # or "star", "moon", "sun"
    }
)
```

### Event Streaming (v0.4.0+)
```python
# Get available event types
get_event_types()
# Returns: {"PiStatus": "System status", "GotoComplete": "Movement completed", ...}

# Get event history
get_event_history(
    device_id="telescope_1",
    count=50,
    event_types=["PiStatus", "GotoComplete"],
    since_timestamp=time.time() - 3600  # Last hour
)

# Read event stream resource
# MCP clients can read: ascom://events/{device_id}/stream
# Returns current event buffer with automatic updates

# Clear event history
clear_event_history(device_id="telescope_1")
```

### SMB File Access (Seestar S30 Pro) 🆕
```python
# List files in root of EMMC Images share
seestar_list_files(path="/")

# List files in a specific directory
seestar_list_files(path="/MyWorks/Solar_photo")

# Download a file (saves to local temp dir)
seestar_download_file(path="/MyWorks/Solar_photo/2026-06-14-141332-Solar.jpg")

# Get storage overview
seestar_storage_info()
```

## Environment Variables (v0.4.0)

```bash
# Pre-configure devices for instant access
export ASCOM_DIRECT_DEVICES="telescope_1:localhost:5555:Seestar S50,telescope_99:localhost:4700:Simulator"

# Known devices (checked if device_id not found)
export ASCOM_KNOWN_DEVICES="localhost:5555:seestar_alp"

# Use simulator
export ASCOM_SIMULATOR_DEVICES="localhost:4700:seestar_simulator"

# Debug logging
export LOG_LEVEL=DEBUG
```

### SMB File Access (Seestar S30 Pro)

The S30 Pro runs a Samba server on port 445 exposing an `EMMC Images` share with anonymous access:
- `SEESTAR_SMB_PORT` - Port (default: 445)
- `SEESTAR_SMB_SHARE` - Share name (default: "EMMC Images")
- `SEESTAR_SMB_USER` / `SEESTAR_SMB_PASSWORD` - Auth (default: empty/anonymous)

SMB host is derived from the first entry in `ASCOM_KNOWN_DEVICES`. No separate env var needed.

### Removed in v0.4.0:
- ❌ `ASCOM_SKIP_UDP_DISCOVERY` - No longer needed!
- ❌ `ASCOM_PREPOPULATE_KNOWN` - Devices resolved on-demand

## Testing

### Test Structure
```
tests/
├── unit/          # Core logic (40+ tests, all pass)
├── integration/   # Real simulator tests (NEW!)
│   ├── test_discovery_timeout.py      # Discovery optimization
│   ├── test_iot_connection_pattern.py # Direct connections
│   ├── test_event_stream.py          # Seestar events
│   └── test_observation_workflow.py   # Complete sessions
├── mcp/          # Protocol validation
│   ├── test_protocol.py              # Basic MCP tests
│   ├── test_ascom_endpoint_mapping.py # HTTP mapping
│   └── test_*_patterns.py            # Usage examples
```

### Running Tests
```bash
# Fast unit tests
pytest tests/unit/ -v

# MCP protocol tests  
pytest tests/mcp/ -v

# With coverage
pytest --cov=ascom_mcp
```

## Common Issues

### alpyca Import Error
The `alpyca` package installs as module name `alpaca`:
```python
# WRONG:
from alpyca import Camera  # ImportError!

# CORRECT:
from alpaca.camera import Camera
from alpaca.telescope import Telescope
from alpaca.filterwheel import FilterWheel
from alpaca import discovery
```

### "Device not found" (v0.4.0)
Helpful error messages now guide you:
1. Use direct connection: `telescope_connect device_id="seestar@host:port"`
2. Add to ASCOM_DIRECT_DEVICES environment
3. Run discovery (only if needed): `discover_ascom_devices`

### Connection Examples
```python
# Direct connection (no setup)
telescope_connect(device_id="seestar@192.168.1.100:5555")

# Pre-configured
telescope_connect(device_id="telescope_1")  # From ASCOM_DIRECT_DEVICES

# After discovery
discover_ascom_devices()  # Only needed once!
telescope_connect(device_id="telescope_0")
```

### Tests hanging
- MCP tests use mocked discovery - no network calls
- If hanging, check for unmocked network operations

### Context errors
- All tools need Context as first parameter
- Use `await ctx.info()` not `ctx.logger.info()`

## Safety Notes

1. **Always initialize Seestar** with `action_start_up_sequence` after connecting
2. **Solar observation** requires explicit mode change and safety protocols
3. **Park before disconnect** to protect equipment

## Development Workflow

```bash
# 1. Make changes
vim src/ascom_mcp/server_fastmcp.py

# 2. Run tests
pytest tests/unit/ -v        # Fast feedback
pytest tests/mcp/ -v         # Protocol validation

# 3. Test with simulator
export ASCOM_SIMULATOR_DEVICES="localhost:4700:seestar_simulator"
python -m ascom_mcp

# 4. Test with real device
cd ../seestar_alp && python root_app.py  # Terminal 1
python -m ascom_mcp                      # Terminal 2
```

### Hot-Reload Development (NEW!)

```bash
# Standard development (manual restart)
invoke dev

# With hot-reload (auto-restart on file changes)
invoke dev --hot

# Hot-reload with HTTP transport (for Claude Code)
invoke dev --hot --transport=streamable-http

# The dev task automatically:
# - Sets PYTHONPATH correctly
# - Configures ASCOM_DIRECT_DEVICES
# - Watches Python files for changes
# - Restarts on modifications
```

### Version Management

Version is now dynamically read from package metadata:
```python
# In __init__.py - no more manual version updates!
from importlib.metadata import version
__version__ = version("mcp-server-ascom")
```

This ensures version consistency between pyproject.toml and runtime.

## Release Process

```bash
# Update version
python scripts/release.py --version X.Y.Z

# Build and publish
python -m build
twine upload dist/*
```

## Key Files

- `src/ascom_mcp/server_fastmcp.py` - Main server with all tools
- `src/ascom_mcp/tools/` - Tool implementations
  - `events.py` - Event history and management
  - `files.py` - SMB file browsing and download (Seestar S30 Pro) 🆕
- `src/ascom_mcp/resources/` - MCP resources (NEW!)
  - `event_stream.py` - Real-time event streaming
- `src/ascom_mcp/devices/` - Device management
  - `device_resolver.py` - Smart device ID resolution
  - `state_persistence.py` - Device memory across sessions
  - `seestar_event_bridge.py` - Seestar event integration
- `tests/conftest.py` - Shared test fixtures
- `docs/MCP_CONFIGURATION_GUIDE.md` - Complete config reference

## Documentation

- `README.md` - User guide
- `docs/development.md` - Developer guide
- `docs/PRODUCTION_DEPLOYMENT.md` - Deployment guide
- `tests/README.md` - Testing guide
- `tests/mcp/README.md` - MCP patterns for AI