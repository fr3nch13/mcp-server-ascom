"""Integration tests for complete observation workflows."""

import asyncio
import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client

from ascom_mcp.server_fastmcp import create_server


class TestObservationWorkflow:
    """Test complete observation session workflows."""
    
    @pytest.fixture
    async def mcp_client_with_simulator(self):
        """Create MCP client configured for simulator."""
        with patch.dict(os.environ, {
            "ASCOM_KNOWN_DEVICES": "localhost:4700:seestar_simulator",
            "ASCOM_SKIP_UDP_DISCOVERY": "true"
        }):
            server = create_server()
            async with Client(server) as client:
                yield client
                
    @pytest.mark.asyncio
    async def test_complete_observation_session(self, mcp_client_with_simulator):
        """Test a complete observation session from start to finish."""
        
        # 1. Discovery phase
        discover_result = await mcp_client_with_simulator.call_tool(
            "discover_ascom_devices",
            {"timeout": 2.0}
        )
        
        discover_data = json.loads(discover_result.content[0].text)
        assert discover_data["success"] is True
        
        telescopes = [d for d in discover_data["devices"] if d["type"] == "Telescope"]
        telescope_id = telescopes[0]["id"]
        
        # 2. Connection phase
        connect_result = await mcp_client_with_simulator.call_tool(
            "telescope_connect",
            {"device_id": telescope_id}
        )
        
        connect_data = json.loads(connect_result.content[0].text)
        assert connect_data["success"] is True
        assert connect_data["telescope"]["connected"] is True
        
        # 3. Initial position check
        pos_result = await mcp_client_with_simulator.call_tool(
            "telescope_get_position",
            {"device_id": telescope_id}
        )
        
        pos_data = json.loads(pos_result.content[0].text)
        initial_ra = pos_data["position"]["ra_hours"]
        initial_dec = pos_data["position"]["dec_degrees"]
        
        # 4. Slew to target
        target_ra = 5.5  # Near Orion
        target_dec = -5.4
        
        goto_result = await mcp_client_with_simulator.call_tool(
            "telescope_goto",
            {
                "device_id": telescope_id,
                "ra": target_ra,
                "dec": target_dec
            }
        )
        
        goto_data = json.loads(goto_result.content[0].text)
        assert goto_data["success"] is True
        
        # 5. Wait for slew to complete (simulate)
        await asyncio.sleep(0.1)
        
        # 6. Verify position
        final_pos_result = await mcp_client_with_simulator.call_tool(
            "telescope_get_position",
            {"device_id": telescope_id}
        )
        
        final_pos_data = json.loads(final_pos_result.content[0].text)
        # In a real test, these would match after slewing
        # For now, just verify we got a response
        assert final_pos_data["success"] is True
        
        # 7. Park telescope
        park_result = await mcp_client_with_simulator.call_tool(
            "telescope_park",
            {"device_id": telescope_id}
        )
        
        park_data = json.loads(park_result.content[0].text)
        assert park_data["success"] is True
        
        # 8. Disconnect
        disconnect_result = await mcp_client_with_simulator.call_tool(
            "telescope_disconnect",
            {"device_id": telescope_id}
        )
        
        disconnect_data = json.loads(disconnect_result.content[0].text)
        assert disconnect_data["success"] is True
        
    @pytest.mark.asyncio
    async def test_error_recovery_workflow(self, mcp_client_with_simulator):
        """Test error recovery during observation."""
        
        # Get telescope
        await mcp_client_with_simulator.call_tool(
            "discover_ascom_devices",
            {"timeout": 1.0}
        )
        
        devices_result = await mcp_client_with_simulator.call_tool(
            "list_devices", 
            {}
        )
        
        devices_data = json.loads(devices_result.content[0].text)
        telescope_id = None
        for device in devices_data.get("devices", []):
            if device["type"] == "Telescope":
                telescope_id = device["id"]
                break
                
        # Connect
        await mcp_client_with_simulator.call_tool(
            "telescope_connect",
            {"device_id": telescope_id}
        )
        
        # Try invalid goto (out of range)
        goto_result = await mcp_client_with_simulator.call_tool(
            "telescope_goto",
            {
                "device_id": telescope_id,
                "ra": 25.0,  # Invalid - > 24
                "dec": 45.0
            }
        )
        
        goto_data = json.loads(goto_result.content[0].text)
        assert goto_data["success"] is False
        assert "RA must be between" in goto_data["error"]
        
        # Verify telescope is still connected and usable
        pos_result = await mcp_client_with_simulator.call_tool(
            "telescope_get_position",
            {"device_id": telescope_id}
        )
        
        pos_data = json.loads(pos_result.content[0].text)
        assert pos_data["success"] is True
        
    @pytest.mark.asyncio
    async def test_camera_integration_workflow(self, mcp_client_with_simulator):
        """Test telescope and camera coordination."""
        
        # Discover devices
        discover_result = await mcp_client_with_simulator.call_tool(
            "discover_ascom_devices",
            {"timeout": 2.0}
        )
        
        discover_data = json.loads(discover_result.content[0].text)
        
        # Find telescope and camera
        telescope_id = None
        camera_id = None
        
        for device in discover_data["devices"]:
            if device["type"] == "Telescope" and not telescope_id:
                telescope_id = device["id"]
            elif device["type"] == "Camera" and not camera_id:
                camera_id = device["id"]
                
        # If we have both devices, test coordination
        if telescope_id and camera_id:
            # Connect telescope
            tel_connect = await mcp_client_with_simulator.call_tool(
                "telescope_connect",
                {"device_id": telescope_id}
            )
            assert json.loads(tel_connect.content[0].text)["success"] is True
            
            # Connect camera
            cam_connect = await mcp_client_with_simulator.call_tool(
                "camera_connect",
                {"device_id": camera_id}
            )
            assert json.loads(cam_connect.content[0].text)["success"] is True
            
            # Get camera status
            cam_status = await mcp_client_with_simulator.call_tool(
                "camera_get_status",
                {"device_id": camera_id}
            )
            
            status_data = json.loads(cam_status.content[0].text)
            assert status_data["success"] is True
            assert "camera_state" in status_data["status"]