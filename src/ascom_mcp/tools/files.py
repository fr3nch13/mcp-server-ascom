"""
Seestar SMB file access tools for ASCOM MCP.

Provides direct SMB/CIFS access to the Seestar S30 Pro's internal storage
via the EMMC Images share. This bypasses the ASCOM camera driver's limited
capture support and gives raw access to FITS, JPG, and thumbnail files.

The S30 Pro exposes an SMB share on port 445 with anonymous access.
"""

import io
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from ..config import config

logger = logging.getLogger(__name__)


def _format_smb_time(t):
    """Format SMB timestamp, handling float or datetime."""
    if t is None:
        return None
    if isinstance(t, (int, float)):
        from datetime import datetime as dt

        return dt.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(t, "strftime"):
        return t.strftime("%Y-%m-%d %H:%M:%S")
    return str(t)


class SeestarFileTools:
    """Tools for browsing and downloading files from Seestar's SMB share."""

    def __init__(self):
        self._smb_conn = None

    async def _ensure_connected(self) -> Any:
        """Lazy-connect to the SMB share."""
        if self._smb_conn is not None:
            try:
                # Ping check
                self._smb_conn.listPath(config.smb_share, "/")
                return self._smb_conn
            except Exception:
                self._smb_conn = None
                logger.info("SMB connection stale, reconnecting")

        try:
            from smb.SMBConnection import SMBConnection

            conn = SMBConnection(
                config.smb_user,
                config.smb_password,
                "hermes",
                "seestar",
                use_ntlm_v2=True,
            )
            conn.connect(config.smb_host, config.smb_port)
            self._smb_conn = conn
            logger.info(f"Connected to SMB share: {config.smb_host}")
            return conn
        except Exception as e:
            logger.error(f"SMB connection failed: {e}")
            host_part = f"{config.smb_host}:{config.smb_port}"
            raise ConnectionError(
                f"Cannot connect to Seestar SMB share at {host_part}. "
                f"Ensure the telescope is on the network and SMB port 445 is open. "
                f"Error: {e}"
            ) from e

    async def _ensure_disconnected(self) -> None:
        """Close SMB connection if open."""
        if self._smb_conn is not None:
            try:
                self._smb_conn.close()
            except Exception:
                pass
            self._smb_conn = None

    async def list_files(self, path: str = "/", pattern: str = "*") -> dict[str, Any]:
        """List files and directories on the Seestar's internal storage.

        Args:
            path: Directory path within the EMMC Images share (default: "/")
            pattern: File pattern filter (default: "*")

        Returns:
            Dictionary with directory listing
        """
        try:
            conn = await self._ensure_connected()
            share = config.smb_share

            # Normalize path
            if not path.startswith("/"):
                path = "/" + path

            entries = conn.listPath(share, path, pattern=pattern)

            files = []
            dirs = []
            for entry in entries:
                if entry.filename in [".", ".."]:
                    continue

                item = {
                    "name": entry.filename,
                    "is_directory": entry.isDirectory,
                    "size": entry.file_size if not entry.isDirectory else 0,
                    "last_modified": _format_smb_time(entry.last_write_time),
                }

                if entry.isDirectory:
                    dirs.append(item)
                else:
                    files.append(item)

            # Sort: directories first, then files, alphabetical
            dirs.sort(key=lambda x: x["name"].lower())
            files.sort(key=lambda x: x["name"].lower())

            return {
                "success": True,
                "path": path,
                "share": share,
                "directories": dirs,
                "files": files,
                "total_dirs": len(dirs),
                "total_files": len(files),
            }

        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to list files at '{path}': {str(e)}",
            }

    async def download_file(self, path: str) -> dict[str, Any]:
        """Download a file from the Seestar's internal storage.

        Downloads the file to a local temp directory and returns
        metadata about the saved file.

        Args:
            path: Path to the file within the EMMC Images share
                  (e.g., "/2025-08-01/M42_light_30s.fits")

        Returns:
            Dictionary with file info and local save path
        """
        try:
            conn = await self._ensure_connected()
            share = config.smb_share

            if not path.startswith("/"):
                path = "/" + path

            # Extract filename
            filename = os.path.basename(path)
            if not filename:
                raise ValueError(f"Invalid path: {path}")

            # Download file to temp dir via SMB
            file_data = io.BytesIO()
            conn.retrieveFile(share, path, file_data)
            raw_bytes = file_data.getvalue()

            if len(raw_bytes) == 0:
                raise ValueError(f"File is empty: {path}")

            # Save to temp directory
            save_dir = os.path.join(tempfile.gettempdir(), "seestar_files")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, filename)

            # Avoid overwrites
            counter = 1
            base, ext = os.path.splitext(save_path)
            while os.path.exists(save_path):
                save_path = f"{base}_{counter}{ext}"
                counter += 1

            with open(save_path, "wb") as f:
                f.write(raw_bytes)

            # Detect type by extension
            ext_lower = ext.lower()
            if ext_lower in [".fits", ".fit", ".fts"]:
                file_type = "fits"
            elif ext_lower in [".jpg", ".jpeg"]:
                file_type = "jpg"
            elif ext_lower in [".png"]:
                file_type = "png"
            elif ext_lower in [".tiff", ".tif"]:
                file_type = "tiff"
            elif ext_lower in [".mp4", ".mov"]:
                file_type = "video"
            else:
                file_type = "unknown"

            return {
                "success": True,
                "filename": filename,
                "file_type": file_type,
                "size_bytes": len(raw_bytes),
                "size_mb": round(len(raw_bytes) / (1024 * 1024), 2),
                "save_path": save_path,
                "download_time": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to download file: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to download file '{path}': {str(e)}",
            }

    async def get_storage_info(self) -> dict[str, Any]:
        """Get storage info from the Seestar's internal storage.

        Returns top-level directory listing which corresponds to
        observation dates/sessions, along with total file counts.

        Returns:
            Dictionary with storage overview
        """
        try:
            # List root to see session directories
            listing = await self.list_files(path="/")

            if not listing.get("success"):
                return listing

            # Get file counts per directory
            session_dirs = listing.get("directories", [])
            sessions = []

            for d in session_dirs:
                dir_listing = await self.list_files(path="/" + d["name"])
                if dir_listing.get("success"):
                    sessions.append(
                        {
                            "date": d["name"],
                            "files": dir_listing["total_files"],
                            "last_modified": d["last_modified"],
                        }
                    )

            # Sort by date descending
            sessions.sort(key=lambda x: x["date"], reverse=True)

            return {
                "success": True,
                "share": config.smb_share,
                "total_sessions": len(sessions),
                "sessions": sessions,
            }

        except Exception as e:
            logger.error(f"Failed to get storage info: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to get storage info: {str(e)}",
            }


# Singleton
seestar_file_tools = SeestarFileTools()
