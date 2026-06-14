"""Unit tests for device manager."""

from unittest.mock import MagicMock, patch

import pytest

from ascom_mcp.devices.manager import (
    ConnectedDevice,
    DeviceInfo,
    DeviceManager,
    DeviceNotFoundError,
)


class TestDeviceInfo:
    """Test DeviceInfo class."""

    def test_device_info_creation(self):
        """Test creating device info from discovery data."""
        data = {
            "DeviceName": "Test Telescope",
            "DeviceType": "Telescope",
            "DeviceNumber": 0,
            "UniqueID": "test-123",
            "Host": "192.168.1.100",
            "Port": 11111,
            "ApiVersion": 1
        }

        info = DeviceInfo(data)

        assert info.id == "telescope_0"
        assert info.name == "Test Telescope"
        assert info.type == "Telescope"
        assert info.host == "192.168.1.100"
        assert info.port == 11111

    def test_device_info_to_dict(self):
        """Test converting device info to dictionary."""
        data = {"DeviceType": "Camera", "DeviceNumber": 1}
        info = DeviceInfo(data)

        result = info.to_dict()

        assert result["id"] == "camera_1"
        assert result["connection_url"] == "http://localhost:11111/api/v1"
        assert "discovered_at" in result


class TestDeviceManager:
    """Test DeviceManager class."""

    @pytest.mark.asyncio
    async def test_initialize(self):
        """Test device manager initialization."""
        manager = DeviceManager()

        await manager.initialize()

        assert manager._session is not None

    @pytest.mark.asyncio
    async def test_discover_devices(self, mock_discovery_response):
        """Test device discovery."""
        # Patch config to avoid environment devices
        with patch("ascom_mcp.devices.manager.config") as mock_config:
            mock_config.known_devices = []
            mock_config.simulator_devices = []
            
            manager = DeviceManager()
            await manager.initialize()

            with patch("ascom_mcp.devices.manager.discovery.search_ipv4") as mock_search:
                mock_search.return_value = mock_discovery_response

                devices = await manager.discover_devices(timeout=2.0)

                assert len(devices) == 2
                assert devices[0].type == "Telescope"
                assert devices[1].type == "Camera"
                mock_search.assert_called_once_with(timeout=2.0)

    @pytest.mark.asyncio
    async def test_connect_device_not_found(self):
        """Test connecting to non-existent device."""
        manager = DeviceManager()
        await manager.initialize()

        with pytest.raises(DeviceNotFoundError):
            await manager.connect_device("nonexistent_device")

    @pytest.mark.asyncio
    async def test_connect_telescope(self, mock_telescope):
        """Test connecting to telescope."""
        manager = DeviceManager()
        await manager.initialize()

        # Add device to available
        device_info = DeviceInfo({
            "DeviceType": "Telescope",
            "DeviceNumber": 0,
            "Host": "localhost"
        })
        manager._available_devices["telescope_0"] = device_info

        with patch("ascom_mcp.devices.manager.Telescope") as MockTelescope:
            MockTelescope.return_value = mock_telescope

            connected = await manager.connect_device("telescope_0")

            assert connected.info.id == "telescope_0"
            assert connected.client == mock_telescope
            assert mock_telescope.Connected is True

    @pytest.mark.asyncio
    async def test_connect_already_connected(self, mock_telescope):
        """Test connecting to already connected device."""
        manager = DeviceManager()
        await manager.initialize()

        # Setup
        device_info = DeviceInfo({"DeviceType": "Telescope", "DeviceNumber": 0})
        manager._available_devices["telescope_0"] = device_info
        connected = ConnectedDevice(device_info, mock_telescope)
        manager._connected_devices["telescope_0"] = connected

        # Should return existing connection
        result = await manager.connect_device("telescope_0")

        assert result == connected

    @pytest.mark.asyncio
    async def test_disconnect_device(self, mock_telescope):
        """Test disconnecting device."""
        manager = DeviceManager()
        await manager.initialize()

        # Setup connected device
        device_info = DeviceInfo({"DeviceType": "Telescope", "DeviceNumber": 0})
        connected = ConnectedDevice(device_info, mock_telescope)
        manager._connected_devices["telescope_0"] = connected

        await manager.disconnect_device("telescope_0")

        assert mock_telescope.Connected is False
        assert "telescope_0" not in manager._connected_devices

    @pytest.mark.asyncio
    async def test_get_connected_device(self):
        """Test getting connected device."""
        manager = DeviceManager()
        await manager.initialize()

        # Setup
        device_info = DeviceInfo({"DeviceType": "Camera", "DeviceNumber": 0})
        mock_camera = MagicMock()
        connected = ConnectedDevice(device_info, mock_camera)
        manager._connected_devices["camera_0"] = connected

        result = manager.get_connected_device("camera_0")

        assert result == connected
        assert result.last_used > connected.connected_at

    @pytest.mark.asyncio
    async def test_get_device_info_connected(self, mock_telescope):
        """Test getting info for connected device."""
        manager = DeviceManager()
        await manager.initialize()

        # Setup
        device_info = DeviceInfo({
            "DeviceType": "Telescope",
            "DeviceNumber": 0,
            "DeviceName": "Test Scope"
        })
        connected = ConnectedDevice(device_info, mock_telescope)
        manager._connected_devices["telescope_0"] = connected

        info = await manager.get_device_info("telescope_0")

        assert info["connected"] is True
        assert info["name"] == "Test Scope"
        assert info["driver_info"] == "Mock Driver v1.0"
        assert info["can_slew"] is True

    @pytest.mark.asyncio
    async def test_shutdown(self, mock_telescope):
        """Test manager shutdown."""
        manager = DeviceManager()
        await manager.initialize()

        # Add connected device
        device_info = DeviceInfo({"DeviceType": "Telescope", "DeviceNumber": 0})
        connected = ConnectedDevice(device_info, mock_telescope)
        manager._connected_devices["telescope_0"] = connected

        await manager.shutdown()

        assert len(manager._connected_devices) == 0
        assert mock_telescope.Connected is False
