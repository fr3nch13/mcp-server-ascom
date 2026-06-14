---
name: mcp-server-ascom
description: Control ASCOM Alpaca-compatible telescopes (Seestar S30 Pro, S50, etc.) via an MCP server. Telescope control (slew, track, park), camera capture via HTTP, and filter wheel control.
---

# ASCOM / Seestar Telescope Control

Control ASCOM Alpaca-compatible smart telescopes through the `ascom` MCP server.

## Architecture

```
Agent → MCP Server (fastmcp) → HTTP/Alpaca → Telescope
```

## MCP Tools

### Discovery & Info
| Tool | Description |
|------|-------------|
| `discover_ascom_devices(timeout)` | Discover ASCOM Alpaca devices on the network |
| `get_device_info(device_id)` | Get details about a specific device |

### Telescope Control
| Tool | Description |
|------|-------------|
| `telescope_connect(device_id)` | Connect to a telescope |
| `telescope_disconnect(device_id)` | Disconnect |
| `telescope_goto(device_id, ra, dec)` | Slew to RA/Dec coordinates |
| `telescope_goto_object(device_id, object_name)` | Slew to a named object (Messier, NGC, planets, Sun, Moon) |
| `telescope_get_position(device_id)` | Get current position, altitude, tracking/slewing status |
| `telescope_park(device_id)` | Park at home position |
| `telescope_custom_action(device_id, action, parameters)` | Execute Seestar-specific commands |

### File Access (SMB) 🆕
| Tool | Description |
|------|-------------|
| `seestar_list_files(path)` | Browse directories on the telescope's internal storage |
| `seestar_download_file(path)` | Download a file to the local machine |
| `seestar_storage_info()` | Get storage overview with session directories |

The S30 Pro exposes an `EMMC Images` SMB share on port 445 with anonymous access. Files are organized under `MyWorks/` by target name. SMB host is derived from `ASCOM_KNOWN_DEVICES`.

### Camera
| Tool | Description |
|------|-------------|
| `camera_connect(device_id)` | Connect a camera |
| `camera_capture(device_id, exposure_seconds, light_frame)` | Capture — **may fail on some drivers** |
| `camera_get_status(device_id)` | Camera status |

### Events
| Tool | Description |
|------|-------------|
| `get_event_history(device_id)` | Retrieve past device events |
| `clear_event_history(device_id)` | Clear stored events |

## MCP Client Configuration

Add to your MCP client's config (e.g., `claude_desktop_config.json` for Claude Desktop):

```json
{
  "mcpServers": {
    "ascom": {
      "command": "python",
      "args": ["-m", "ascom_mcp"],
      "env": {
        "ASCOM_KNOWN_DEVICES": "host:port:name"
      }
    }
  }
}
```

The `ASCOM_KNOWN_DEVICES` env var pre-populates known devices so discovery works without UDP broadcast. Format: `host:port:label`.

## Device ID Format

When found via `discover_ascom_devices`, devices are registered as `type_number` (e.g., `telescope_0`, `camera_0`). Connecting with a direct connection string also works:

```
telescope_connect(device_id="seestar@192.168.1.100:5555")
```

The format is `name@host:port` — bypasses discovery entirely.

## Ephemeris Support

The `telescope_goto_object` tool now calculates ephemeris for all nine solar system objects (Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune) using astropy's `get_body()`. The scope's location is read from the mount if available, with a configurable fallback.

## ⚠️ Safety: Parking

**Always confirm with the user before parking.** The telescope may have accessories attached (solar filter, dew cap, lens cover). Parking with attachments can damage equipment.

## Driver Limitations

The Camera V3 driver on some Seestar models doesn't implement standard ASCOM capture properties (`Offset`, `PercentCompleted`). If `camera_capture` fails, direct HTTP calls may be used instead as a backup, but ask the user first to confirm this non-standard approach.

```bash
# Start exposure
curl -s -X PUT "http://host:port/api/v1/camera/0/startexposure" \
  -d "Duration=0.5&Light=true"

# Check if ready
curl -s "http://host:port/api/v1/camera/0/imageready"

# Download raw frame (returns 2160×3840 uint16 JSON array)
curl -s "http://host:port/api/v1/camera/0/imagearray" -o /tmp/frame.json

# Convert to viewable image
python3 -c "
import json, numpy as np
from PIL import Image
with open('/tmp/frame.json') as f:
    data = json.load(f)
arr = np.array(data['Value'], dtype=np.uint16)
norm = ((arr.astype(np.float32) - arr.min()) / (arr.max() - arr.min()) * 255).astype(np.uint8)
Image.fromarray(norm).save('/tmp/frame.png')
"
```

## Useful HTTP Endpoints

```
# Management
GET  /management/v1/description               # Server info
GET  /management/v1/configureddevices          # All configured devices

# Telescope
GET  /api/v1/telescope/0/description
GET  /api/v1/telescope/0/rightascension        # RA in hours
GET  /api/v1/telescope/0/declination           # Dec in degrees
GET  /api/v1/telescope/0/altitude
GET  /api/v1/telescope/0/azimuth
PUT  /api/v1/telescope/0/slewtocoordinates     # GOTO (RightAscension, Declination)
PUT  /api/v1/telescope/0/park
PUT  /api/v1/telescope/0/unpark
GET  /api/v1/telescope/0/attpark
GET  /api/v1/telescope/0/tracking
PUT  /api/v1/telescope/0/tracking              # Set tracking (TrackingState=true/false)

# Camera
PUT  /api/v1/camera/0/startexposure            # (Duration, Light)
GET  /api/v1/camera/0/imageready
GET  /api/v1/camera/0/imagearray
GET  /api/v1/camera/0/camerastate

# Filter Wheel
GET  /api/v1/filterwheel/0/names
GET  /api/v1/filterwheel/0/position
PUT  /api/v1/filterwheel/0/position            # 0=Dark, 1=IR, 2=LP
```

## Notes

- **Scope offline doesn't break the MCP server** — tools return connection errors, no restart needed
- **Camera capture** via the MCP tool may fail on Camera V3 drivers; use the HTTP API directly if allowed by the user
- **Filter wheel positions** vary by model
- **Raw frames** are full-sensor uint16 arrays in JSON (e.g., 2160×3840 on S30 Pro) — normalize to view

## Port Note: Seestar S30 Pro

The Seestar S30 Pro may exposes its ASCOM Alpaca API on **port 32323**, not the default 5555 or 11111. If you're troubleshooting connectivity with a Seestar smart telescope and the standard ports aren't responding, try scanning for alternate ports or checking the management API directly:

```bash
curl -s http://host:port/management/v1/description
curl -s http://host:port/management/v1/configureddevices
```