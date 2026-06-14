"""Unit tests for ASCOM MCP configuration."""

import os
from unittest.mock import patch

from ascom_mcp.config import Config


class TestConfigSMB:
    """Test SMB configuration derivation."""

    def teardown_method(self):
        """Clean up environment variables after each test."""
        for key in ["SEESTAR_SMB_HOST", "ASCOM_KNOWN_DEVICES"]:
            os.environ.pop(key, None)

    def test_smb_host_from_known_devices(self):
        """Test SMB host derives from ASCOM_KNOWN_DEVICES."""
        with patch.dict(
            os.environ, {"ASCOM_KNOWN_DEVICES": "192.168.1.100:32323:s30_pro"}
        ):
            config = Config()
            assert config.smb_host == "192.168.1.100"

    def test_smb_host_from_env_var(self):
        """Test explicit SEESTAR_SMB_HOST takes priority."""
        with patch.dict(
            os.environ,
            {
                "ASCOM_KNOWN_DEVICES": "192.168.1.100:32323:s30_pro",
                "SEESTAR_SMB_HOST": "10.0.0.1",
            },
        ):
            config = Config()
            assert config.smb_host == "10.0.0.1"

    def test_smb_host_no_devices(self):
        """Test fallback to localhost when no known devices."""
        with patch.dict(os.environ, {}, clear=True):
            config = Config()
            assert config.smb_host == "localhost"

    def test_smb_host_multiple_known_devices(self):
        """Test takes first device from known devices list."""
        with patch.dict(
            os.environ,
            {
                "ASCOM_KNOWN_DEVICES": (
                    "10.0.0.1:5555:device1,"
                    "192.168.1.100:32323:device2"
                )
            },
        ):
            config = Config()
            assert config.smb_host == "10.0.0.1"

    def test_smb_defaults(self):
        """Test SMB default values."""
        with patch.dict(os.environ, {}, clear=True):
            config = Config()
            assert config.smb_port == 445
            assert config.smb_share == "EMMC Images"
            assert config.smb_user == ""
            assert config.smb_password == ""

    def test_smb_port_env_override(self):
        """Test SEESTAR_SMB_PORT override."""
        with patch.dict(os.environ, {"SEESTAR_SMB_PORT": "139"}):
            config = Config()
            assert config.smb_port == 139

    def test_smb_share_env_override(self):
        """Test SEESTAR_SMB_SHARE override."""
        with patch.dict(os.environ, {"SEESTAR_SMB_SHARE": "MyShare"}):
            config = Config()
            assert config.smb_share == "MyShare"
