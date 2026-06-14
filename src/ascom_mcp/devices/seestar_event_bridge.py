"""
Bridge between Seestar eventbus and MCP event system.

This module handles the integration between Seestar's blinker-based
event system and the MCP event stream manager.
"""

import asyncio
import json
from typing import Any

from ascom_mcp.ascom_logging import StructuredLogger

logger = StructuredLogger("ascom.seestar.events")


class SeestarEventBridge:
    """Bridges Seestar events to MCP event system."""
    
    def __init__(self, event_manager):
        """Initialize the event bridge.
        
        Args:
            event_manager: The EventStreamManager instance
        """
        self.event_manager = event_manager
        self._active_subscriptions = {}
        self._event_loop = None
        
    async def connect_to_seestar(self, device_id: str, device_info: Any) -> None:
        """Connect to a Seestar device's event system.
        
        This is called when a Seestar telescope is connected.
        
        Args:
            device_id: The device identifier
            device_info: Device information
        """
        try:
            # For Seestar devices at port 5555, we know they have eventbus
            if device_info.port == 5555 and "seestar" in device_info.name.lower():
                logger.info(f"Setting up Seestar event bridge for {device_id}")
                
                # Note: The actual eventbus connection happens in seestar_alp
                # We'll hook into it through the telescope connection
                
                # Store metadata for this device
                await self.event_manager.set_device_metadata(
                    device_id,
                    {
                        "name": device_info.name,
                        "type": "Seestar",
                        "unique_id": device_info.unique_id,
                        "supports_events": True,
                    }
                )
                
                logger.info(f"Seestar event bridge ready for {device_id}")
                
        except Exception as e:
            logger.error(f"Failed to set up Seestar event bridge: {e}")
            
    async def handle_seestar_event(self, device_id: str, event_data: dict) -> None:
        """Handle an event from Seestar.
        
        This is called by the telescope tools when they receive events.
        
        Args:
            device_id: Device identifier
            event_data: Raw event data from Seestar
        """
        try:
            # Add the event to the stream
            await self.event_manager.add_event(device_id, event_data)
            
            # Log specific event types we care about
            event_type = event_data.get("Event", "Unknown")
            
            if event_type == "PiStatus":
                # System status update
                if "battery_capacity" in event_data:
                    logger.info(
                        f"Seestar battery: {event_data['battery_capacity']}%",
                        device_id=device_id
                    )
                    
            elif event_type == "GotoComplete":
                # Movement completed
                logger.info(
                    f"Seestar goto completed",
                    device_id=device_id,
                    ra=event_data.get("ra"),
                    dec=event_data.get("dec")
                )
                
            elif event_type == "ViewChanged":
                # View state changed
                logger.info(
                    f"Seestar view changed",
                    device_id=device_id,
                    state=event_data.get("state")
                )
                
        except Exception as e:
            logger.error(f"Failed to handle Seestar event: {e}", device_id=device_id)
            
    def setup_event_loop(self):
        """Set up the event loop for async operations."""
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "No async event loop available — Seestar event streaming disabled. "
                "Events will not be forwarded to MCP subscribers."
            )
            self._event_loop = None
            
    def handle_sync_event(self, device_id: str, event_data: dict):
        """Handle events from synchronous context (blinker callbacks).
        
        This bridges sync blinker events to async MCP event system.
        """
        if self._event_loop:
            # Schedule the async handler
            asyncio.run_coroutine_threadsafe(
                self.handle_seestar_event(device_id, event_data),
                self._event_loop
            )
        else:
            # No event loop, log warning
            logger.warning(
                "No event loop available for Seestar event",
                device_id=device_id,
                event_type=event_data.get("Event")
            )