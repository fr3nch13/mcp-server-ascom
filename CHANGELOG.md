# Changelog

## [0.5.0] - 2026-06-14

Seestar S30 Pro support. SMB file access. Ephemeris for planets.

### Added
- `seestar_list_files`, `seestar_download_file`, `seestar_storage_info` — SMB file access tools for browsing and downloading images from Seestar's internal storage (port 445, anonymous)
- Ephemeris calculation for solar system objects in `telescope_goto_object` — Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune (replaces TODO stub)
- SMB configuration via `SEESTAR_SMB_PORT`, `SEESTAR_SMB_SHARE`, `SEESTAR_SMB_USER`, `SEESTAR_SMB_PASSWORD` env vars — host auto-derived from `ASCOM_KNOWN_DEVICES`
- `pysmb>=1.2.10` optional dependency (`pip install mcp-server-ascom[smb]`)
- Unit tests for `SeestarFileTools` and SMB config derivation

### Changed
- Version bump to 0.5.0
- README updated with SMB file access documentation
- CLAUDE.md updated with SMB examples and env vars
- Internal `src/ascom_mcp/CLAUDE.md` updated with SeestarFileTools and SMB config docs

## [0.3.0] - 2025-01-30

FastMCP. Structured logging. Half the code.

### Changed
- Migrated to FastMCP from low-level Server API
- Default entry point uses FastMCP implementation
- Reduced codebase: 600 → 300 lines

### Added
- Structured JSON logging to stderr
- OpenTelemetry-compatible log format
- Comprehensive test script: test_v030.py

### Fixed
- "Method not found" errors in Claude Desktop
- Decorator return type mismatches
- Protocol compliance issues

### Migration
From v0.2.x: No API changes. Internal improvements only.

Key files changed:
- `server.py` → `server_fastmcp.py` (new implementation)
- `__main__.py` (imports FastMCP version)
- `logging.py` (new structured logger)

## [0.2.6] - 2025-01-30

### Fixed
- Decorator functions return lists, not Result objects
- UV cache issues with local development

## [0.2.5] - 2025-01-30

### Fixed
- Added missing method registration in __init__
- Integration tests verify all MCP methods

## [0.2.4] - 2025-01-30

### Fixed
- tools/list and resources/list registration
- Claude Desktop compatibility

## [0.2.3] - 2025-01-29

### Added
- Initial PyPI release
- Full MCP protocol support

## [0.2.2] - 2025-07-30

### Fixed
- Removed `initialize_fn` parameter - MCP API changed

## [0.2.1] - 2025-07-30

### Fixed
- CLI entry point - added synchronous wrapper for `mcp-server-ascom` command
- Removed deprecated license classifier per modern packaging standards

## [0.2.0] - 2025-07-30

MCP 2025-06-18. Modern. Fast. Secure.

### Added
- MCP 2025-06-18 protocol support
- Structured JSON responses with text fallbacks
- Version negotiation (2025-06-18, 2025-03-26, 2024-11-05)
- Optional OAuth 2.0 security (disabled by default)
- Security module with JWT support
- Content creation utilities
- Human-readable error suggestions
- Helper script for MCP Inspector

### Changed
- Protocol: 2024-11-05 → 2025-06-18
- Responses: text-only → structured JSON + fallback
- Errors: basic → contextual with fixes
- Writing: verbose → concise

### Fixed
- TextContent type field
- alpyca/alpaca import confusion
- Virtual environment with uv

## [0.1.0] - 2025-07-30

Initial release.

- ASCOM Alpaca device control
- Discovery, telescope, camera tools
- Natural language ("Point at M31")
- Full test coverage
- GitHub Actions CI/CD