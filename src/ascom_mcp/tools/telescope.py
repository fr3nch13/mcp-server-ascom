"""
Telescope control tools for ASCOM MCP.

Provides telescope control capabilities including goto, tracking, and parking.
"""

import logging
from typing import Any

# For Seestar EventBus integration
try:
    from blinker import signal
    BLINKER_AVAILABLE = True
except ImportError:
    BLINKER_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Blinker not available - Seestar event streaming will be disabled")

# Make astropy optional for now due to environment issues
try:
    from astropy import units as u
    from astropy.coordinates import SkyCoord, get_body, EarthLocation
    from astropy.time import Time

    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Astropy not available - celestial object lookups will be disabled")

from ..utils.errors import (
    DeviceBusyError,
    InvalidParameterError,
    OperationNotSupportedError,
)
from .base import BaseDeviceTools

logger = logging.getLogger(__name__)


class TelescopeTools(BaseDeviceTools):
    """Tools for controlling ASCOM telescopes."""

    async def connect(self, device_id: str) -> dict[str, Any]:
        """Connect to a telescope."""
        try:
            logger.info(f"Connecting to telescope {device_id}")

            # Connect via device manager
            connected = await self.device_manager.connect_device(device_id)
            telescope = connected.client

            # Get telescope info
            info = {
                "device_id": device_id,
                "name": connected.info.name,
                "connected": telescope.Connected,
                "description": telescope.Description,
                "driver_info": telescope.DriverInfo,
                "can_slew": telescope.CanSlew,
                "can_park": telescope.CanPark,
                "can_find_home": telescope.CanFindHome,
                "can_track": telescope.CanSetTracking,
                "tracking": telescope.Tracking
                if hasattr(telescope, "Tracking")
                else None,
            }

            # Hook into Seestar EventBus for real-time events
            logger.debug(f"EventBus check: BLINKER_AVAILABLE={BLINKER_AVAILABLE}, port={connected.info.port}, name={connected.info.name}")
            if BLINKER_AVAILABLE and connected.info.port == 5555 and "seestar" in connected.info.name.lower():
                try:
                    # Import event bridge access
                    from ..server_fastmcp import event_bridge, event_tools
                    
                    logger.debug(f"Event bridge check: event_bridge={event_bridge is not None}, event_tools={event_tools is not None}")
                    if event_bridge and event_tools:
                        # Set up event handling for this device
                        await event_tools.setup_device_events(device_id)
                        
                        # Connect to the Seestar EventBus signal
                        device_name = f"Seestar {connected.info.name.split()[-1]}"  # e.g., "Seestar Alpha"
                        signal_name = f"{device_name}.eventbus"
                        logger.info(f"Attempting to connect to EventBus signal: {signal_name}")
                        
                        eventbus_signal = signal(signal_name)
                        
                        # Create a callback that forwards events to our event bridge
                        def forward_event(event_data):
                            logger.debug(f"EventBus event received: {event_data}")
                            if event_bridge._event_loop:
                                # Forward to event bridge (handles async conversion)
                                event_bridge.handle_sync_event(device_id, event_data)
                        
                        # Connect to the signal
                        eventbus_signal.connect(forward_event, weak=False)
                        logger.info(f"✅ Connected to Seestar EventBus for {device_id} (signal: {signal_name})")
                        
                        # Store the connection for cleanup
                        if not hasattr(self, '_eventbus_connections'):
                            self._eventbus_connections = {}
                        self._eventbus_connections[device_id] = (eventbus_signal, forward_event)
                        
                except Exception as e:
                    logger.warning(f"Could not connect to Seestar EventBus: {e}", exc_info=True)
                    # Non-fatal - telescope still works without events
            else:
                logger.debug(f"EventBus not connected: conditions not met")

            return {
                "success": True,
                "message": f"Connected to {connected.info.name}",
                "telescope": info,
            }

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to connect to telescope {device_id}",
            }

    async def disconnect(self, device_id: str) -> dict[str, Any]:
        """Disconnect from a telescope."""
        try:
            logger.info(f"Disconnecting from telescope {device_id}")

            # Get device to check if parking is needed
            connected = self.device_manager.get_connected_device(device_id)
            telescope = connected.client

            # Park if possible and not already parked
            if telescope.CanPark and not telescope.AtPark:
                logger.info("Parking telescope before disconnect")
                telescope.Park()

            # Clean up EventBus connection if present
            if hasattr(self, '_eventbus_connections') and device_id in self._eventbus_connections:
                eventbus_signal, callback = self._eventbus_connections[device_id]
                eventbus_signal.disconnect(callback)
                del self._eventbus_connections[device_id]
                logger.info(f"Disconnected from Seestar EventBus for {device_id}")
            
            # Disconnect
            await self.device_manager.disconnect_device(device_id)

            return {
                "success": True,
                "message": f"Disconnected from telescope {device_id}",
            }

        except Exception as e:
            logger.error(f"Failed to disconnect: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to disconnect from telescope {device_id}",
            }

    async def goto(self, device_id: str, ra: float, dec: float) -> dict[str, Any]:
        """
        Slew telescope to RA/Dec coordinates.

        Args:
            device_id: Connected telescope ID
            ra: Right Ascension in hours (0-24)
            dec: Declination in degrees (-90 to +90)
        """
        try:
            # Validate coordinates
            if not 0 <= ra <= 24:
                raise InvalidParameterError("RA must be between 0 and 24 hours")
            if not -90 <= dec <= 90:
                raise InvalidParameterError("Dec must be between -90 and +90 degrees")

            # Get telescope
            connected = self.device_manager.get_connected_device(device_id)
            telescope = connected.client

            # Check capabilities
            if not telescope.CanSlew:
                raise OperationNotSupportedError("Telescope cannot slew")

            # Check if slewing
            if telescope.Slewing:
                raise DeviceBusyError("Telescope is already slewing")

            logger.info(f"Slewing telescope to RA={ra}h, Dec={dec}°")

            # Perform async slew (returns immediately)
            telescope.SlewToCoordinatesAsync(ra, dec)

            # Get initial status
            status = {
                "slewing": telescope.Slewing,
                "target_ra": ra,
                "target_dec": dec,
                "current_ra": telescope.RightAscension,
                "current_dec": telescope.Declination,
            }

            return {
                "success": True,
                "message": f"Slewing to RA={ra:.3f}h, Dec={dec:+.2f}°",
                "status": status,
            }

        except Exception as e:
            logger.error(f"Goto failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to slew telescope",
            }

    async def goto_object(self, device_id: str, object_name: str) -> dict[str, Any]:
        """
        Slew telescope to a named object.

        Uses astropy to resolve object names to coordinates.
        """
        try:
            logger.info(f"Resolving object name: {object_name}")

            # Try to resolve object name
            try:
                # First try as a solar system object
                if object_name.lower() in [
                    "moon",
                    "sun",
                    "mercury",
                    "venus",
                    "mars",
                    "jupiter",
                    "saturn",
                    "uranus",
                    "neptune",
                ]:
                    # Calculate ephemeris using astropy
                    if not ASTROPY_AVAILABLE:
                        return {
                            "success": False,
                            "error": "Astropy not available",
                            "message": f"Cannot resolve '{object_name}' — astropy is required for ephemeris calculation. Use telescope_goto with RA/Dec coordinates instead.",
                        }

                    try:
                        # Get scope's current position for location
                        scope_loc = None
                        try:
                            connected = self.device_manager.get_connected_device(device_id)
                            telescope = connected.client
                            lat = getattr(telescope, "Latitude", None)
                            lon = getattr(telescope, "Longitude", None)
                            if lat is not None and lon is not None:
                                scope_loc = EarthLocation(lat=float(lat), lon=float(lon))
                        except Exception:
                            pass

                        if scope_loc is None:
                            raise ValueError(
                                "Cannot resolve solar system object — telescope has not reported its location. "
                                "Set the telescope's location in the Seestar app and try again."
                            )

                        now = Time.now()
                        body = get_body(object_name.lower(), now, location=scope_loc)
                        ra_hours = body.ra.hour
                        dec_deg = body.dec.degree

                        logger.info(
                            f"Resolved {object_name} via ephemeris to RA={ra_hours:.3f}h, Dec={dec_deg:+.2f}°"
                        )

                        result = await self.goto(device_id, ra_hours, dec_deg)

                        if result["success"]:
                            result["message"] = (
                                f"Slewing to {object_name} (RA={ra_hours:.3f}h, Dec={dec_deg:+.2f}°)"
                            )
                            result["object_info"] = {
                                "name": object_name,
                                "ra_hours": ra_hours,
                                "dec_degrees": dec_deg,
                                "ra_hms": body.ra.to_string(unit=u.hour, sep=":", precision=1),
                                "dec_dms": body.dec.to_string(unit=u.degree, sep=":", precision=0),
                            }

                        return result

                    except Exception as e:
                        logger.error(f"Ephemeris calculation failed for {object_name}: {e}")
                        return {
                            "success": False,
                            "error": str(e),
                            "message": f"Could not calculate position for '{object_name}': {e}",
                        }

                # Check if astropy is available
                if not ASTROPY_AVAILABLE:
                    return {
                        "success": False,
                        "error": "Celestial object lookup unavailable",
                        "message": "Astropy is not available. Please use telescope_goto with RA/Dec coordinates instead.",
                    }

                # Try to resolve as deep sky object
                skycoord = SkyCoord.from_name(object_name)
                ra_hours = skycoord.ra.hour
                dec_deg = skycoord.dec.degree

                logger.info(
                    f"Resolved {object_name} to RA={ra_hours:.3f}h, Dec={dec_deg:+.2f}°"
                )

                # Use regular goto
                result = await self.goto(device_id, ra_hours, dec_deg)

                if result["success"]:
                    result["message"] = (
                        f"Slewing to {object_name} (RA={ra_hours:.3f}h, Dec={dec_deg:+.2f}°)"
                    )
                    result["object_info"] = {
                        "name": object_name,
                        "ra_hours": ra_hours,
                        "dec_degrees": dec_deg,
                        "ra_hms": skycoord.ra.to_string(
                            unit=u.hour, sep=":", precision=1
                        ),
                        "dec_dms": skycoord.dec.to_string(
                            unit=u.degree, sep=":", precision=0
                        ),
                    }

                return result

            except Exception as e:
                logger.error(f"Failed to resolve object name: {e}")
                return {
                    "success": False,
                    "error": "Object not found",
                    "message": f"Could not resolve '{object_name}'. Try catalog designations like 'M31' or 'NGC 224'",
                }

        except Exception as e:
            logger.error(f"goto_object failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to slew to object",
            }

    async def get_position(self, device_id: str) -> dict[str, Any]:
        """Get current telescope position."""
        try:
            # Get telescope
            connected = self.device_manager.get_connected_device(device_id)
            telescope = connected.client

            # Get position
            ra = telescope.RightAscension
            dec = telescope.Declination

            # Build position info
            position = {
                "ra_hours": ra,
                "dec_degrees": dec,
            }

            # Add formatted coordinates
            if ASTROPY_AVAILABLE:
                skycoord = SkyCoord(ra=ra * u.hour, dec=dec * u.degree)
                position["ra_hms"] = skycoord.ra.to_string(
                    unit=u.hour, sep=":", precision=1
                )
                position["dec_dms"] = skycoord.dec.to_string(
                    unit=u.degree, sep=":", precision=0
                )
            else:
                # Simple formatting without astropy
                hours = int(ra)
                minutes = int((ra - hours) * 60)
                seconds = ((ra - hours) * 60 - minutes) * 60
                position["ra_hms"] = f"{hours:02d}:{minutes:02d}:{seconds:04.1f}"

                sign = "+" if dec >= 0 else "-"
                degrees = int(abs(dec))
                arcmin = int((abs(dec) - degrees) * 60)
                arcsec = ((abs(dec) - degrees) * 60 - arcmin) * 60
                position["dec_dms"] = f"{sign}{degrees:02d}:{arcmin:02d}:{arcsec:02.0f}"

            position.update(
                {
                    "altitude": telescope.Altitude
                    if hasattr(telescope, "Altitude")
                    else None,
                    "azimuth": telescope.Azimuth
                    if hasattr(telescope, "Azimuth")
                    else None,
                    "sidereal_time": telescope.SiderealTime
                    if hasattr(telescope, "SiderealTime")
                    else None,
                }
            )

            # Get status
            status = {
                "tracking": telescope.Tracking
                if hasattr(telescope, "Tracking")
                else None,
                "slewing": telescope.Slewing,
                "at_park": telescope.AtPark if hasattr(telescope, "AtPark") else None,
                "at_home": telescope.AtHome if hasattr(telescope, "AtHome") else None,
            }

            return {"success": True, "position": position, "status": status}

        except Exception as e:
            logger.error(f"Failed to get position: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to get telescope position",
            }

    async def park(self, device_id: str) -> dict[str, Any]:
        """Park the telescope."""
        try:
            # Get telescope
            connected = self.device_manager.get_connected_device(device_id)
            telescope = connected.client

            # Check if can park
            if not telescope.CanPark:
                raise OperationNotSupportedError("Telescope cannot park")

            # Check if already parked
            if telescope.AtPark:
                return {"success": True, "message": "Telescope is already parked"}

            logger.info("Parking telescope")

            # Park telescope
            telescope.Park()

            return {
                "success": True,
                "message": "Telescope parking initiated",
                "status": {"at_park": telescope.AtPark, "slewing": telescope.Slewing},
            }

        except Exception as e:
            logger.error(f"Failed to park: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to park telescope",
            }

    async def custom_action(
        self, device_id: str, action: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute custom ASCOM action on telescope."""
        try:
            # Get telescope
            connected = self.device_manager.get_connected_device(device_id)
            telescope = connected.client

            logger.info(f"Executing custom action: {action}")

            # Convert parameters to JSON string for ASCOM
            if parameters:
                import json

                param_str = json.dumps(parameters)
            else:
                param_str = ""

            # Execute action
            result = telescope.Action(action, param_str)

            # Try to parse result as JSON
            try:
                import json

                if isinstance(result, str) and result.strip():
                    result = json.loads(result)
            except:
                # If not JSON, return as string
                pass

            return {
                "success": True,
                "action": action,
                "result": result,
                "message": f"Action '{action}' completed successfully",
            }

        except Exception as e:
            logger.error(f"Custom action failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "action": action,
                "message": f"Failed to execute action '{action}'",
            }
