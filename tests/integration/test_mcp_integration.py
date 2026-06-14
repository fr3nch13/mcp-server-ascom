"""Integration tests for MCP server with real simulators."""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import Client

from ascom_mcp.server_fastmcp import create_server


class TestMCPIntegration:
    """Test MCP server integration with simulators."""

    @pytest.fixture
    async def mcp_client(self):
        """Create MCP client with simulator configuration."""
        # Configure for simulator
        with patch.dict(os.environ, {
            "ASCOM_KNOWN_DEVICES": "localhost:4700:seestar_simulator",
            "ASCOM_SKIP_UDP_DISCOVERY": "true"
        }):
            server = create_server()
            async with Client(server) as client:
                yield client

    @pytest.mark.asyncio
    async def test_discover_simulator(self, mcp_client):
        """Test discovering simulator through MCP."""
        result = await mcp_client.call_tool(
            "discover_ascom_devices",
            {"timeout": 1.0}
        )
        
        data = json.loads(result.content[0].text)
        assert data["success"] is True
        
        # Should find simulator
        devices = data["devices"]
        simulator = next((d for d in devices if "simulator" in d["name"].lower()), None)
        assert simulator is not None
        
    @pytest.mark.asyncio
    async def test_connect_and_goto(self, mcp_client):
        """Test complete connect and goto workflow."""
        # First discover
        discover_result = await mcp_client.call_tool(
            "discover_ascom_devices",
            {"timeout": 1.0}
        )
        
        # Find telescope
        data = json.loads(discover_result.content[0].text)
        telescopes = [d for d in data["devices"] if d["type"] == "Telescope"]
        assert len(telescopes) > 0
        
        telescope_id = telescopes[0]["id"]
        
        # Connect
        connect_result = await mcp_client.call_tool(
            "telescope_connect",
            {"device_id": telescope_id}
        )
        
        connect_data = json.loads(connect_result.content[0].text)
        assert connect_data["success"] is True
        
        # Get position
        pos_result = await mcp_client.call_tool(
            "telescope_get_position", 
            {"device_id": telescope_id}
        )
        
        pos_data = json.loads(pos_result.content[0].text)
        assert pos_data["success"] is True
        assert "position" in pos_data
        
        # Test goto - this is where async/await issues would manifest
        goto_result = await mcp_client.call_tool(
            "telescope_goto",
            {
                "device_id": telescope_id,
                "ra": 10.0,
                "dec": 45.0
            }
        )
        
        goto_data = json.loads(goto_result.content[0].text)
        assert goto_data["success"] is True
        assert goto_data["status"]["target_ra"] == 10.0
        assert goto_data["status"]["target_dec"] == 45.0
        
    @pytest.mark.asyncio
    async def test_error_propagation(self, mcp_client):
        """Test that errors propagate correctly through MCP."""
        # Try to connect to non-existent device
        with pytest.raises(Exception) as exc_info:
            await mcp_client.call_tool(
                "telescope_connect",
                {"device_id": "nonexistent_device"}
            )
        
        # Should get meaningful error
        assert "not found" in str(exc_info.value).lower()
        
    @pytest.mark.asyncio
    async def test_concurrent_operations(self, mcp_client):
        """Test concurrent MCP operations."""
        import asyncio
        
        # Discover first
        await mcp_client.call_tool("discover_ascom_devices", {"timeout": 1.0})
        
        # Run multiple operations concurrently
        tasks = [
            mcp_client.call_tool("list_devices", {}),
            mcp_client.call_tool("list_devices", {}),
            mcp_client.call_tool("list_devices", {})
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        for result in results:
            data = json.loads(result.content[0].text)
            assert data["success"] is True