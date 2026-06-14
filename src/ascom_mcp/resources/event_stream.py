"""
Event stream resource management for ASCOM devices.

Provides real-time event streaming from ASCOM devices (especially Seestar)
through MCP resources with automatic notifications on updates.
"""

import asyncio
import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from ascom_mcp.ascom_logging import StructuredLogger

# Event type definitions
EVENT_TYPES = {
    "PiStatus": "System status updates (battery, temperature)",
    "GotoComplete": "Telescope movement completed",
    "BalanceSensor": "Balance sensor updates",
    "EqModePA": "Polar alignment status",
    "Stack": "Image stacking progress",
    "ViewChanged": "View state changes",
    "MountEvent": "Mount status changes",
}

logger = StructuredLogger("ascom.events")


class EventStreamManager:
    """Manages event streams for ASCOM devices."""

    def __init__(self, buffer_size: int = 100):
        """Initialize event stream manager.
        
        Args:
            buffer_size: Maximum events to keep per device
        """
        self._event_buffers: dict[str, deque] = {}
        self._buffer_size = buffer_size
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._device_metadata: dict[str, dict] = {}
        
    async def add_event(self, device_id: str, event_data: dict) -> None:
        """Add an event to the device's event stream.
        
        Args:
            device_id: Device identifier
            event_data: Raw event data from device
        """
        async with self._lock:
            # Initialize buffer if needed
            if device_id not in self._event_buffers:
                self._event_buffers[device_id] = deque(maxlen=self._buffer_size)
                self._subscribers[device_id] = set()
                
            # Standardize event format
            standardized_event = {
                "timestamp": time.time(),
                "datetime": datetime.now(timezone.utc).isoformat() + "Z",
                "device_id": device_id,
                "event_type": event_data.get("Event", "Unknown"),
                "data": event_data,
            }
            
            # Add to buffer
            self._event_buffers[device_id].append(standardized_event)
            
            # Notify subscribers
            dead_queues = set()
            for queue in self._subscribers[device_id]:
                try:
                    queue.put_nowait(standardized_event)
                except asyncio.QueueFull:
                    # Queue is full, skip this event
                    logger.warning(f"Event queue full for device {device_id}")
                except Exception:
                    # Queue is closed or broken
                    dead_queues.add(queue)
                    
            # Clean up dead queues
            self._subscribers[device_id] -= dead_queues
            
        logger.debug(
            f"Added event for device {device_id}",
            event_type=standardized_event["event_type"],
            buffer_size=len(self._event_buffers[device_id])
        )
            
    async def get_events(
        self, 
        device_id: str, 
        since: Optional[float] = None,
        event_types: Optional[list[str]] = None,
        limit: Optional[int] = None
    ) -> dict:
        """Get events for a device.
        
        Args:
            device_id: Device identifier
            since: Unix timestamp to get events after
            event_types: Filter by specific event types
            limit: Maximum number of events to return
            
        Returns:
            Dictionary with device info and filtered events
        """
        async with self._lock:
            if device_id not in self._event_buffers:
                return {
                    "device_id": device_id,
                    "status": "no_events",
                    "events": [],
                    "metadata": self._device_metadata.get(device_id, {})
                }
                
            # Get all events
            events = list(self._event_buffers[device_id])
            
            # Apply filters
            if since:
                events = [e for e in events if e["timestamp"] > since]
                
            if event_types:
                events = [e for e in events if e["event_type"] in event_types]
                
            # Apply limit (most recent events)
            if limit and len(events) > limit:
                events = events[-limit:]
                
            return {
                "device_id": device_id,
                "status": "active",
                "event_count": len(events),
                "buffer_size": len(self._event_buffers[device_id]),
                "events": events,
                "metadata": self._device_metadata.get(device_id, {}),
                "available_types": list(set(e["event_type"] for e in self._event_buffers[device_id]))
            }
            
    async def subscribe(self, device_id: str, queue_size: int = 100) -> asyncio.Queue:
        """Subscribe to real-time events for a device.
        
        Args:
            device_id: Device identifier
            queue_size: Maximum events to queue
            
        Returns:
            Queue that will receive new events
        """
        queue = asyncio.Queue(maxsize=queue_size)
        
        async with self._lock:
            if device_id not in self._subscribers:
                self._subscribers[device_id] = set()
            self._subscribers[device_id].add(queue)
            
        logger.info(f"New event subscriber for device {device_id}")
        return queue
        
    async def unsubscribe(self, device_id: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from device events.
        
        Args:
            device_id: Device identifier
            queue: Queue to remove from subscribers
        """
        async with self._lock:
            if device_id in self._subscribers:
                self._subscribers[device_id].discard(queue)
                logger.info(f"Removed event subscriber for device {device_id}")
                
    async def set_device_metadata(self, device_id: str, metadata: dict) -> None:
        """Set metadata for a device.
        
        Args:
            device_id: Device identifier
            metadata: Device metadata (name, type, etc.)
        """
        async with self._lock:
            self._device_metadata[device_id] = metadata
            
    async def clear_device_events(self, device_id: str) -> None:
        """Clear all events for a device.
        
        Args:
            device_id: Device identifier
        """
        async with self._lock:
            if device_id in self._event_buffers:
                self._event_buffers[device_id].clear()
                logger.info(f"Cleared events for device {device_id}")
                
    def get_event_types(self) -> dict[str, str]:
        """Get available event types and descriptions."""
        return EVENT_TYPES.copy()