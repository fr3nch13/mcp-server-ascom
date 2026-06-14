"""
Camera control tools for ASCOM MCP.

Provides camera control capabilities including capture, cooling, and status.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ..devices.manager import DeviceManager
from ..utils.errors import (
    DeviceBusyError,
    InvalidParameterError,
)
from .base import BaseDeviceTools

logger = logging.getLogger(__name__)


class CameraTools(BaseDeviceTools):
    """Tools for controlling ASCOM cameras."""

    def __init__(self, device_manager: DeviceManager):
        super().__init__(device_manager)

    async def connect(self, device_id: str) -> dict[str, Any]:
        """Connect to a camera."""
        try:
            logger.info(f"Connecting to camera {device_id}")

            # Connect via device manager
            connected = await self.device_manager.connect_device(device_id)
            camera = connected.client

            # Get camera info
            info = {
                "device_id": device_id,
                "name": connected.info.name,
                "connected": camera.Connected,
                "description": camera.Description,
                "driver_info": camera.DriverInfo,
                "sensor_name": camera.SensorName
                if hasattr(camera, "SensorName")
                else "Unknown",
                "sensor_type": self._get_sensor_type_name(camera.SensorType),
                "pixel_size": {"x": camera.PixelSizeX, "y": camera.PixelSizeY},
                "sensor_size": {
                    "width": camera.CameraXSize,
                    "height": camera.CameraYSize,
                },
                "max_bin": {"x": camera.MaxBinX, "y": camera.MaxBinY},
                "has_cooler": camera.CanSetCCDTemperature,
                "can_abort": camera.CanAbortExposure,
                "can_pulse_guide": camera.CanPulseGuide,
            }

            # Get current state
            if camera.CanSetCCDTemperature:
                info["cooler_on"] = camera.CoolerOn
                info["ccd_temperature"] = camera.CCDTemperature

            return self._success_response(
                f"Connected to {connected.info.name}",
                camera=info,
            )

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return self._error_response(
                str(e),
                message=f"Failed to connect to camera {device_id}",
            )

    async def disconnect(self, device_id: str) -> dict[str, Any]:
        """Disconnect from a camera."""
        try:
            logger.info(f"Disconnecting from camera {device_id}")
            await self.device_manager.disconnect_device(device_id)
            return self._success_response(f"Disconnected from camera {device_id}")
        except Exception as e:
            logger.error(f"Failed to disconnect: {e}")
            return self._error_response(
                str(e),
                message=f"Failed to disconnect from camera {device_id}",
            )

    async def capture(
        self, device_id: str, exposure_seconds: float, light_frame: bool = True
    ) -> dict[str, Any]:
        """
        Capture an image with the camera.

        Args:
            device_id: Connected camera ID
            exposure_seconds: Exposure time in seconds
            light_frame: True for light frame, False for dark frame
        """
        try:
            # Validate exposure time
            if exposure_seconds <= 0:
                raise InvalidParameterError("Exposure time must be positive")

            # Get camera
            connected = self.device_manager.get_connected_device(device_id)
            camera = connected.client

            # Check if camera is ready
            if camera.CameraState != 0:  # 0 = idle
                raise DeviceBusyError("Camera is busy")

            logger.info(
                f"Starting {exposure_seconds}s {'light' if light_frame else 'dark'} frame"
            )

            # Start exposure
            camera.StartExposure(exposure_seconds, light_frame)

            # Wait for exposure to complete
            start_time = datetime.now(timezone.utc)
            while not camera.ImageReady:
                await asyncio.sleep(0.5)

                # Check for timeout (exposure time + 30 seconds)
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                if elapsed > exposure_seconds + 30:
                    raise TimeoutError("Exposure timeout")

            # Get image array
            image_array = camera.ImageArray

            # Get metadata
            metadata = {
                "exposure_time": exposure_seconds,
                "frame_type": "light" if light_frame else "dark",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "binning": {"x": camera.BinX, "y": camera.BinY},
                "subframe": {
                    "x": camera.StartX,
                    "y": camera.StartY,
                    "width": camera.NumX,
                    "height": camera.NumY,
                },
                "ccd_temperature": camera.CCDTemperature
                if camera.CanSetCCDTemperature
                else None,
                "gain": camera.Gain if hasattr(camera, "Gain") else None,
                "offset": camera.Offset if hasattr(camera, "Offset") else None,
            }

            return self._success_response(
                f"Captured {exposure_seconds}s {'light' if light_frame else 'dark'} frame",
                metadata=metadata,
                image_info={
                    "width": camera.NumX,
                    "height": camera.NumY,
                    "bit_depth": camera.ImageArray.dtype.name
                    if hasattr(image_array, "dtype")
                    else "unknown",
                },
            )

        except Exception as e:
            logger.error(f"Capture failed: {e}")
            return self._error_response(
                str(e),
                message="Failed to capture image",
            )

    async def get_status(self, device_id: str) -> dict[str, Any]:
        """Get current camera status."""
        try:
            # Get camera
            connected = self.device_manager.get_connected_device(device_id)
            camera = connected.client

            # Get camera state
            state_map = {
                0: "idle",
                1: "waiting",
                2: "exposing",
                3: "reading",
                4: "download",
                5: "error",
            }

            status = {
                "state": state_map.get(camera.CameraState, "unknown"),
                "state_code": camera.CameraState,
                "image_ready": camera.ImageReady,
                "percent_complete": camera.PercentCompleted
                if hasattr(camera, "PercentCompleted")
                else None,
            }

            # Temperature info
            if camera.CanSetCCDTemperature:
                status["temperature"] = {
                    "ccd": camera.CCDTemperature,
                    "cooler_on": camera.CoolerOn,
                    "cooler_power": camera.CoolerPower
                    if hasattr(camera, "CoolerPower")
                    else None,
                    "heat_sink": camera.HeatSinkTemperature
                    if hasattr(camera, "HeatSinkTemperature")
                    else None,
                }

            # Current settings
            settings = {
                "binning": {"x": camera.BinX, "y": camera.BinY},
                "subframe": {
                    "x": camera.StartX,
                    "y": camera.StartY,
                    "width": camera.NumX,
                    "height": camera.NumY,
                },
            }

            # Optional settings
            if hasattr(camera, "Gain"):
                settings["gain"] = camera.Gain
            if hasattr(camera, "Offset"):
                settings["offset"] = camera.Offset
            if hasattr(camera, "ReadoutMode"):
                settings["readout_mode"] = camera.ReadoutMode

            return self._success_response("Camera status retrieved", status=status, settings=settings)

        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return self._error_response(
                str(e),
                message="Failed to get camera status",
            )

    def _get_sensor_type_name(self, sensor_type: int) -> str:
        """Convert sensor type code to name."""
        sensor_types = {
            0: "Monochrome",
            1: "Color",
            2: "RGGB",
            3: "CMYG",
            4: "CMYG2",
            5: "LRGB",
        }
        return sensor_types.get(sensor_type, f"Unknown ({sensor_type})")
