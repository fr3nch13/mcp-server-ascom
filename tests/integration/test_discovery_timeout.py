"""Integration tests for device discovery and timeout behavior."""

import asyncio
import os
import time
from unittest.mock import patch

import pytest
from ascom_mcp.devices.manager import DeviceManager


class TestDiscoveryTimeout:
    """Test discovery timeout and optimization strategies."""

    @pytest.mark.asyncio
    async def test_discovery_with_skip_udp(self):
        """Test that ASCOM_SKIP_UDP_DISCOVERY actually skips UDP discovery."""
        # Set environment to skip UDP
        with patch.dict(os.environ, {"ASCOM_SKIP_UDP_DISCOVERY": "true"}):
            manager = DeviceManager()
            await manager.initialize()
            
            start_time = time.time()
            devices = await manager.discover_devices(timeout=5.0)
            elapsed = time.time() - start_time
            
            # Should be fast (< 1 second) if UDP is skipped
            assert elapsed < 1.0, f"Discovery took {elapsed:.2f}s, should be < 1s with UDP skipped"
            
    @pytest.mark.asyncio
    async def test_known_devices_prepopulation(self):
        """Test that ASCOM_KNOWN_DEVICES pre-populates without discovery."""
        # Set known devices
        known_devices = "localhost:5555:seestar_alp,localhost:4700:simulator"
        with patch.dict(os.environ, {"ASCOM_KNOWN_DEVICES": known_devices}):
            manager = DeviceManager()
            await manager.initialize()
            
            # Check if devices are available without discovery
            available = await manager.get_available_devices()
            device_names = [d["name"] for d in available]
            
            assert "seestar_alp" in device_names or "seestar_alp (Known)" in device_names
            assert "simulator" in device_names or "simulator (Known)" in device_names
            
    @pytest.mark.asyncio 
    async def test_discovery_timeout_behavior(self):
        """Test that discovery respects timeout parameter."""
        manager = DeviceManager()
        await manager.initialize()
        
        # Test with very short timeout
        start_time = time.time()
        devices = await manager.discover_devices(timeout=0.5)
        elapsed = time.time() - start_time
        
        # Should complete within timeout + small margin
        assert elapsed < 1.0, f"Discovery didn't respect timeout, took {elapsed:.2f}s"
        
    @pytest.mark.asyncio
    async def test_concurrent_discovery_protection(self):
        """Test that concurrent discovery calls are properly handled."""
        manager = DeviceManager()
        await manager.initialize()
        
        # Start multiple discoveries concurrently
        tasks = [
            manager.discover_devices(timeout=2.0) for _ in range(3)
        ]
        
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start_time
        
        # All should get the same result
        assert all(results[0] == r for r in results[1:])
        
        # Should not take 3x the time (serialized)
        assert elapsed < 3.0, f"Concurrent discoveries took {elapsed:.2f}s"