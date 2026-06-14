"""Device management for ASCOM devices."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from aiohttp import ClientSession
from alpaca.camera import Camera
from alpaca.filterwheel import FilterWheel
from alpaca.focuser import Focuser
from alpaca.telescope import Telescope
from alpaca import discovery
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import config
from .state_persistence import DeviceStatePersistence
from .device_resolver import DeviceResolver

logger = logging.getLogger(__name__)


class DeviceNotFoundError(Exception):
    """Device not found error."""

    pass


class DeviceInfo:
    """Information about a discovered device."""

    def __init__(self, device_data: dict[str, Any]):
        self.data = device_data
        self.type = device_data.get("DeviceType", "Unknown")
        self.number = device_data.get("DeviceNumber", 0)
        self.name = device_data.get("DeviceName", "Unknown Device")
        self.unique_id = device_data.get("UniqueID", f"{self.type}_{self.number}")
        self.host = device_data.get("Host", "localhost")
        self.port = device_data.get("Port", 11111)
        self.api_version = device_data.get("ApiVersion", 1)
        self.is_simulator = device_data.get("IsSimulator", False)

        # Generate device ID
        self.id = f"{self.type.lower()}_{self.number}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "number": self.number,
            "unique_id": self.unique_id,
            "host": self.host,
            "port": self.port,
            "api_version": self.api_version,
            "discovered_at": datetime.now(timezone.utc).isoformat() + "Z",
            "connection_url": f"http://{self.host}:{self.port}/api/v1",
        }


class ConnectedDevice:
    """Represents a connected ASCOM device."""

    def __init__(self, info: DeviceInfo, client: Any):
        self.info = info
        self.client = client
        self.connected_at = datetime.now(timezone.utc)
        self.last_used = datetime.now(timezone.utc)

    def update_last_used(self):
        """Update last used timestamp."""
        self.last_used = datetime.now(timezone.utc)


class DeviceManager:
    """Manages ASCOM device discovery and connections."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._available_devices: dict[str, DeviceInfo] = {}
        self._connected_devices: dict[str, ConnectedDevice] = {}
        self._session: ClientSession | None = None
        self._discovery_lock = asyncio.Lock()
        self._connection_lock = asyncio.Lock()
        self._state_persistence = DeviceStatePersistence()
        self._event_callbacks: dict[str, callable] = {}
        self._initialized = True

    async def initialize(self):
        """Initialize the device manager."""
        self._session = ClientSession()
        logger.info("Device manager initialized")
        
        # Load devices from persistent state
        stored_devices = self._state_persistence.load_devices()
        for device in stored_devices:
            self._available_devices[device.id] = device
            logger.debug(f"Loaded device from state: {device.name}")
        
        # Pre-populate known devices to avoid discovery requirement
        self._prepopulate_known_devices()

    async def shutdown(self):
        """Shutdown device manager and disconnect all devices."""
        # Disconnect all devices
        device_ids = list(self._connected_devices.keys())
        for device_id in device_ids:
            try:
                await self.disconnect_device(device_id)
            except Exception as e:
                logger.error(f"Error disconnecting device {device_id}: {e}")

        # Save final state
        all_devices = list(self._available_devices.values())
        self._state_persistence.save_devices(all_devices)
        
        # Close session
        if self._session:
            await self._session.close()

        logger.info("Device manager shutdown complete")

    async def discover_devices(self, timeout: float = 5.0) -> list[DeviceInfo]:
        """
        Discover ASCOM devices on the network.

        Uses alpyca discovery to find Alpaca devices.
        """
        async with self._discovery_lock:
            logger.info(f"Starting device discovery (timeout: {timeout}s)")

            try:
                # Clear old devices
                self._available_devices.clear()
                found_devices = []

                # Check if we should skip UDP discovery
                skip_udp = os.getenv("ASCOM_SKIP_UDP_DISCOVERY", "false").lower() == "true"
                
                # Run all discovery methods concurrently
                tasks = []
                
                # UDP discovery (if not skipped)
                if not skip_udp:
                    tasks.append(self._discover_udp_async(timeout))
                
                # Known devices check
                tasks.append(self._check_known_devices_async())
                
                # Simulator check
                tasks.append(self._check_simulators_async())
                
                # Wait for all discovery methods
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results
                for result in results:
                    if isinstance(result, list):
                        for device in result:
                            if isinstance(device, DeviceInfo) and device.id not in self._available_devices:
                                self._available_devices[device.id] = device
                                found_devices.append(device)
                                logger.info(
                                    f"Discovered: {device.name} ({device.type}) "
                                    f"at {device.host}:{device.port}"
                                )
                    elif isinstance(result, Exception):
                        logger.debug(f"Discovery method failed: {result}")

                logger.info(f"Discovery complete: found {len(found_devices)} devices")
                if not found_devices:
                    logger.warning(
                        "No ASCOM devices found on network. "
                        "Ensure devices are powered on and connected."
                    )
                    
                # Save discovered devices to persistent state
                all_devices = list(self._available_devices.values())
                self._state_persistence.save_devices(all_devices)

                return found_devices

            except Exception as e:
                logger.error(f"Discovery failed: {e}")
                raise

    async def _discover_udp_async(self, timeout: float) -> list[DeviceInfo]:
        """Async wrapper for UDP discovery."""
        try:
            # Run UDP discovery in thread with timeout
            devices = await asyncio.wait_for(
                asyncio.to_thread(discovery.search_ipv4, timeout=timeout),
                timeout=timeout + 1.0
            )
            return [DeviceInfo(device_data) for device_data in devices]
        except asyncio.TimeoutError:
            logger.debug("UDP discovery timed out")
            return []
        except Exception as e:
            logger.debug(f"UDP discovery failed: {e}")
            return []

    async def _check_known_devices_async(self) -> list[DeviceInfo]:
        """Check all known devices concurrently."""
        tasks = []
        for host, port, name in config.known_devices:
            tasks.append(self._check_single_known_device(host, port, name))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        devices = []
        for result in results:
            if isinstance(result, list):
                devices.extend(result)
        return devices

    async def _check_single_known_device(self, host: str, port: int, name: str) -> list[DeviceInfo]:
        """Check a single known device."""
        logger.info(f"Checking known device: {name} at {host}:{port}")
        try:
            # Query management API
            url = f"http://{host}:{port}/management/v1/configureddevices"
            async with self._session.get(url, timeout=2.0) as response:
                if response.status == 200:
                    data = await response.json()
                    devices = data.get("Value", [])
                    device_infos = []
                    for device_data in devices:
                        # Add host and port to device data
                        device_data["Host"] = host
                        device_data["Port"] = port
                        device_infos.append(DeviceInfo(device_data))
                    return device_infos
        except asyncio.TimeoutError:
            logger.warning(f"Known device {name} at {host}:{port} timed out")
        except Exception as e:
            logger.warning(f"Error checking known device {name}: {e}")
        return []

    async def _check_simulators_async(self) -> list[DeviceInfo]:
        """Check all simulators concurrently."""
        tasks = []
        for host, port, name in config.simulator_devices:
            tasks.append(self._check_single_simulator(host, port, name))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        devices = []
        for result in results:
            if isinstance(result, DeviceInfo):
                devices.append(result)
        return devices

    async def _check_single_simulator(self, host: str, port: int, name: str) -> DeviceInfo | None:
        """Check a single simulator device."""
        logger.info(f"Checking simulator: {name} at {host}:{port}")
        
        try:
            # Quick TCP check to see if simulator is running
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=2.0
            )
            writer.close()
            await writer.wait_closed()
            
            # If we can connect, add as a simulator device
            device_data = {
                "DeviceType": "Telescope",
                "DeviceNumber": 99,  # Reserved for simulator
                "DeviceName": f"{name} (Simulator)",
                "Host": host,
                "Port": port,
                "UniqueID": f"simulator_{host}_{port}",
                "IsSimulator": True,
                "ApiVersion": 1
            }
            
            device_info = DeviceInfo(device_data)
            logger.info(f"Found simulator: {device_info.name}")
            return device_info
            
        except asyncio.TimeoutError:
            logger.debug(f"Simulator {name} at {host}:{port} connection timed out")
        except Exception as e:
            logger.debug(f"Simulator {name} at {host}:{port} not available: {e}")
        
        return None

    async def get_available_devices(self) -> list[dict[str, Any]]:
        """Get list of available devices."""
        return [device.to_dict() for device in self._available_devices.values()]

    async def get_connected_devices(self) -> list[dict[str, Any]]:
        """Get list of connected devices."""
        devices = []
        for _device_id, connected in self._connected_devices.items():
            device_dict = connected.info.to_dict()
            device_dict.update(
                {
                    "connected_at": connected.connected_at.isoformat(),
                    "last_used": connected.last_used.isoformat(),
                }
            )
            devices.append(device_dict)
        return devices

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(ConnectionError),
        before_sleep=lambda retry_state: logger.warning(
            f"Connection attempt {retry_state.attempt_number} failed, retrying..."
        )
    )
    async def connect_device(self, device_id: str) -> ConnectedDevice:
        """
        Connect to a device by ID with automatic retry.

        Creates appropriate client based on device type.
        Retries up to 3 times with exponential backoff on connection failures.
        """
        async with self._connection_lock:
            # Check if already connected
            if device_id in self._connected_devices:
                logger.info(f"Device {device_id} already connected")
                return self._connected_devices[device_id]

            # Resolve device info from multiple sources
            device_info = await self._resolve_device_id(device_id)
            if not device_info:
                raise DeviceNotFoundError(
                    f"Device '{device_id}' not found. "
                    f"Options: 1) Run discover_ascom_devices, "
                    f"2) Use format 'name@host:port' (e.g., 'seestar@192.168.1.100:5555'), "
                    f"3) Add to ASCOM_DIRECT_DEVICES environment variable"
                )

            # Add to available devices if not already there
            if device_id not in self._available_devices:
                self._available_devices[device_id] = device_info
                # Save to persistent state
                all_devices = list(self._available_devices.values())
                self._state_persistence.save_devices(all_devices)
            logger.info(
                f"Connecting to {device_info.name} "
                f"at {device_info.host}:{device_info.port}"
            )

            try:
                # Create appropriate client based on device type
                client = None
                base_url = f"{device_info.host}:{device_info.port}"

                if device_info.type.lower() == "telescope":
                    client = Telescope(base_url, device_info.number)
                elif device_info.type.lower() == "camera":
                    client = Camera(base_url, device_info.number)
                elif device_info.type.lower() == "focuser":
                    client = Focuser(base_url, device_info.number)
                elif device_info.type.lower() == "filterwheel":
                    client = FilterWheel(base_url, device_info.number)
                else:
                    raise ConnectionError(
                        f"Unsupported device type: {device_info.type}"
                    )

                # Test connection
                client.Connected = True
                if not client.Connected:
                    raise ConnectionError("Failed to connect to device")

                # Store connected device
                connected = ConnectedDevice(device_info, client)
                self._connected_devices[device_id] = connected

                logger.info(f"Successfully connected to {device_info.name}")
                
                # Notify event callbacks about connection
                if "on_device_connected" in self._event_callbacks:
                    try:
                        await self._event_callbacks["on_device_connected"](device_id, device_info)
                    except Exception as e:
                        logger.error(f"Error in device connected callback: {e}")
                        
                return connected

            except Exception as e:
                logger.error(f"Failed to connect to {device_id}: {e}")
                raise ConnectionError(f"Connection failed: {str(e)}") from e

    async def disconnect_device(self, device_id: str):
        """Disconnect from a device."""
        async with self._connection_lock:
            if device_id not in self._connected_devices:
                logger.warning(f"Device {device_id} not connected")
                return

            connected = self._connected_devices[device_id]
            logger.info(f"Disconnecting from {connected.info.name}")

            try:
                # Disconnect client
                connected.client.Connected = False
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")

            # Remove from connected devices
            del self._connected_devices[device_id]
            logger.info(f"Disconnected from {connected.info.name}")

    def get_connected_device(self, device_id: str) -> ConnectedDevice:
        """Get a connected device by ID."""
        if device_id not in self._connected_devices:
            raise DeviceNotFoundError(f"Device {device_id} is not connected")
        device = self._connected_devices[device_id]
        device.update_last_used()
        return device
        
    def register_event_callback(self, event_name: str, callback: callable):
        """Register a callback for device events.
        
        Args:
            event_name: Name of the event (e.g., 'on_device_connected')
            callback: Async function to call when event occurs
        """
        self._event_callbacks[event_name] = callback
        logger.info(f"Registered event callback for {event_name}")

    async def get_device_info(self, device_id: str) -> dict[str, Any]:
        """Get information about a device."""
        if device_id in self._connected_devices:
            # Get info from connected device
            connected = self._connected_devices[device_id]
            info = connected.info.to_dict()
            info["connected"] = True
            
            # Get driver info from connected device
            try:
                client = connected.client
                info["driver_info"] = getattr(client, "DriverInfo", "Unknown")
                info["driver_version"] = getattr(client, "DriverVersion", "Unknown")
                info["can_slew"] = getattr(client, "CanSlew", None)
                info["can_park"] = getattr(client, "CanPark", None)
                info["can_find_home"] = getattr(client, "CanFindHome", None)
                info["can_track"] = getattr(client, "CanTrack", None)
                info["slewing"] = getattr(client, "Slewing", None)
                info["is_parked"] = getattr(client, "AtPark", None)
            except Exception as e:
                logger.warning(f"Could not get driver info: {e}")
                
            return info
        elif device_id in self._available_devices:
            # Get info from available device
            info = self._available_devices[device_id].to_dict()
            info["connected"] = False
            return info
        else:
            raise DeviceNotFoundError(f"Device {device_id} not found")
    
    def _prepopulate_known_devices(self):
        """Pre-populate known devices so they can be connected without discovery."""
        # Pre-populate from ASCOM_DIRECT_DEVICES environment variable
        # Format: "telescope_1:localhost:5555:Seestar S50,telescope_99:localhost:4700:Simulator"
        direct_devices = os.getenv("ASCOM_DIRECT_DEVICES", "")
        
        if direct_devices:
            for device_spec in direct_devices.split(","):
                parts = device_spec.strip().split(":")
                if len(parts) >= 4:
                    device_id = parts[0]
                    host = parts[1]
                    port = int(parts[2])
                    name = parts[3]
                    
                    # Extract device type and number from ID
                    device_type = "Telescope"  # Default
                    device_number = 1
                    if "_" in device_id:
                        type_part, num_part = device_id.rsplit("_", 1)
                        device_type = type_part.title()
                        try:
                            device_number = int(num_part)
                        except ValueError:
                            pass
                    
                    device_data = {
                        "DeviceType": device_type,
                        "DeviceNumber": device_number,
                        "DeviceName": f"{name} (Direct)",
                        "Host": host,
                        "Port": port,
                        "UniqueID": f"direct_{host}_{port}",
                        "ApiVersion": 1
                    }
                    device_info = DeviceInfo(device_data)
                    self._available_devices[device_id] = device_info
                    logger.info(f"Pre-populated {name} at {host}:{port} as {device_id}")
        
        # Also pre-populate from known_devices
        for host, port, name in config.known_devices:
                device_data = {
                    "DeviceType": "Telescope",
                    "DeviceNumber": 1,
                    "DeviceName": f"{name} (Known)",
                    "Host": host,
                    "Port": port,
                    "UniqueID": f"known_{host}_{port}",
                    "ApiVersion": 1
                }
                device_info = DeviceInfo(device_data)
                device_id = f"telescope_{port - 5554}"  # Generate ID from port
                self._available_devices[device_id] = device_info
                logger.info(f"Pre-populated known device {name} at {host}:{port} as {device_id}")
    
    async def _resolve_device_id(self, device_id: str) -> Optional[DeviceInfo]:
        """Resolve a device ID to DeviceInfo from multiple sources.
        
        Checks in order:
        1. Already available devices (memory)
        2. Persistent state (disk)
        3. Direct connection string (e.g., "seestar@192.168.1.100:5555")
        4. Environment variables (ASCOM_DIRECT_DEVICES)
        5. Known devices config
        
        Args:
            device_id: Device identifier to resolve
            
        Returns:
            DeviceInfo if found, None otherwise
        """
        # 1. Check memory cache
        if device_id in self._available_devices:
            logger.debug(f"Found {device_id} in memory cache")
            return self._available_devices[device_id]
            
        # 2. Check persistent state
        stored_devices = self._state_persistence.load_devices()
        for device in stored_devices:
            if device.id == device_id:
                logger.debug(f"Found {device_id} in persistent state")
                # Add to memory cache
                self._available_devices[device_id] = device
                return device
                
        # 3. Check if it's a direct connection string
        connection_info = DeviceResolver.parse_connection_string(device_id)
        if connection_info:
            name, host, port = connection_info
            logger.info(f"Parsed connection string: {name} at {host}:{port}")
            
            # Extract type from device_id if possible
            device_type, device_number = DeviceResolver.parse_device_id_type(device_id)
            
            device_info = DeviceResolver.create_device_info_from_connection(
                device_id=device_id,
                name=name,
                host=host,
                port=port,
                device_type=device_type,
                device_number=device_number
            )
            return device_info
            
        # 4. Check environment variable for direct devices
        direct_devices = os.getenv("ASCOM_DIRECT_DEVICES", "")
        if direct_devices:
            for device_spec in direct_devices.split(","):
                parts = device_spec.strip().split(":")
                if len(parts) >= 4 and parts[0] == device_id:
                    host = parts[1]
                    port = int(parts[2])
                    name = parts[3]
                    
                    device_type, device_number = DeviceResolver.parse_device_id_type(device_id)
                    
                    device_info = DeviceResolver.create_device_info_from_connection(
                        device_id=device_id,
                        name=f"{name} (Direct)",
                        host=host,
                        port=port,
                        device_type=device_type,
                        device_number=device_number
                    )
                    logger.info(f"Found {device_id} in ASCOM_DIRECT_DEVICES")
                    return device_info
                    
        # 5. Check known devices config
        for host, port, name in config.known_devices:
            # Generate possible device IDs
            possible_ids = [
                f"telescope_{port - 5554}",  # Legacy format
                f"telescope_{port}",
                name.lower().replace(" ", "_"),
                f"{name}@{host}:{port}"
            ]
            
            if device_id in possible_ids:
                device_type, device_number = DeviceResolver.parse_device_id_type(device_id)
                
                device_info = DeviceResolver.create_device_info_from_connection(
                    device_id=device_id,
                    name=f"{name} (Known)",
                    host=host,
                    port=port,
                    device_type=device_type,
                    device_number=device_number
                )
                logger.info(f"Found {device_id} in known devices config")
                return device_info
                
        # Not found
        logger.debug(f"Could not resolve device ID: {device_id}")
        return None