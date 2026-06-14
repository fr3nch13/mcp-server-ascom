"""Configuration for ASCOM MCP Server."""

import os


class Config:
    """Server configuration."""

    def __init__(self):
        # Discovery settings
        self.discovery_timeout = float(os.getenv("ASCOM_DISCOVERY_TIMEOUT", "5.0"))

        # Known devices that don't implement UDP discovery
        # Format: [(host, port, name), ...]
        self.known_devices = self._parse_known_devices()

        # Simulator devices
        # Format: [(host, port, name), ...]
        self.simulator_devices = self._parse_simulator_devices()

        # SMB file access settings (Seestar internal storage)
        self.smb_host = self._derive_smb_host()
        self.smb_port = int(os.getenv("SEESTAR_SMB_PORT", "445"))
        self.smb_share = os.getenv("SEESTAR_SMB_SHARE", "EMMC Images")
        self.smb_user = os.getenv("SEESTAR_SMB_USER", "")
        self.smb_password = os.getenv("SEESTAR_SMB_PASSWORD", "")

        # Security settings
        self.local_only = os.getenv("ASCOM_LOCAL_ONLY", "true").lower() == "true"

    def _parse_known_devices(self) -> list[tuple[str, int, str]]:
        """Parse ASCOM_KNOWN_DEVICES environment variable.

        Format: "host1:port1:name1,host2:port2:name2"
        Example: "localhost:5555:seestar_alp,192.168.1.100:11111:MyMount"
        """
        devices = []
        known_str = os.getenv("ASCOM_KNOWN_DEVICES", "localhost:5555:seestar_alp")

        if known_str:
            for device in known_str.split(","):
                parts = device.strip().split(":")
                if len(parts) >= 2:
                    host = parts[0]
                    port = int(parts[1])
                    name = parts[2] if len(parts) > 2 else f"{host}:{port}"
                    devices.append((host, port, name))

        return devices

    def _derive_smb_host(self) -> str:
        """Derive SMB host from ASCOM_KNOWN_DEVICES or explicit env var."""
        env_host = os.getenv("SEESTAR_SMB_HOST")
        if env_host:
            return env_host
        if self.known_devices:
            return self.known_devices[0][0]
        return "localhost"

    def _parse_simulator_devices(self) -> list[tuple[str, int, str]]:
        """Parse ASCOM_SIMULATOR_DEVICES environment variable.

        Format: "host1:port1:name1,host2:port2:name2"
        Example: "localhost:4700:seestar_simulator"
        Default: "localhost:4700:seestar_simulator"
        """
        devices = []
        simulator_str = os.getenv(
            "ASCOM_SIMULATOR_DEVICES", "localhost:4700:seestar_simulator"
        )

        if simulator_str:
            for device in simulator_str.split(","):
                parts = device.strip().split(":")
                if len(parts) >= 2:
                    host = parts[0]
                    port = int(parts[1])
                    name = parts[2] if len(parts) > 2 else f"{host}:{port}_simulator"
                    devices.append((host, port, name))

        return devices


# Global config instance
config = Config()
