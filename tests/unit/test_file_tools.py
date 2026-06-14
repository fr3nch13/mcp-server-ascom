"""Unit tests for Seestar SMB file access tools."""

from unittest.mock import MagicMock, patch

import pytest

from ascom_mcp.tools.files import SeestarFileTools


class TestSeestarFileTools:
    """Test SeestarFileTools class."""

    @pytest.fixture
    def tools(self):
        """Create SeestarFileTools instance."""
        return SeestarFileTools()

    @pytest.fixture
    def mock_smb_conn(self):
        """Mock SMB connection."""
        conn = MagicMock()
        conn.connect = MagicMock()
        conn.close = MagicMock()
        return conn

    @pytest.fixture
    def mock_smb_file(self):
        """Mock SMB file entry."""
        entry = MagicMock()
        entry.filename = "test_file.fits"
        entry.isDirectory = False
        entry.file_size = 1024
        entry.last_write_time = 1718000000.0  # float timestamp
        return entry

    @pytest.fixture
    def mock_smb_dir(self):
        """Mock SMB directory entry."""
        entry = MagicMock()
        entry.filename = "MyWorks"
        entry.isDirectory = True
        entry.file_size = 0
        entry.last_write_time = 1718000000.0
        return entry

    @pytest.mark.asyncio
    async def test_list_files_root_success(
        self, tools, mock_smb_conn, mock_smb_dir, mock_smb_file
    ):
        """Test listing root directory returns files and directories."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            mock_smb_conn.listPath.return_value = [mock_smb_dir, mock_smb_file]

            result = await tools.list_files("/")

        assert result["success"] is True
        assert result["path"] == "/"
        assert len(result["directories"]) == 1
        assert len(result["files"]) == 1
        assert result["directories"][0]["name"] == "MyWorks"
        assert result["files"][0]["name"] == "test_file.fits"
        assert result["total_dirs"] == 1
        assert result["total_files"] == 1

    @pytest.mark.asyncio
    async def test_list_files_subdirectory_success(
        self, tools, mock_smb_conn, mock_smb_file
    ):
        """Test listing a subdirectory returns files."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            mock_smb_conn.listPath.return_value = [mock_smb_file]

            result = await tools.list_files("/MyWorks/Solar_photo")

        assert result["success"] is True
        assert result["path"] == "/MyWorks/Solar_photo"
        assert len(result["files"]) == 1
        assert result["files"][0]["size"] == 1024

    @pytest.mark.asyncio
    async def test_list_files_connection_failure(self, tools, mock_smb_conn):
        """Test graceful failure when SMB connection fails."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            mock_smb_conn.connect.side_effect = ConnectionError("Connection refused")

            result = await tools.list_files("/")

        assert result["success"] is False
        assert "error" in result
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_list_files_path_prefix_added(
        self, tools, mock_smb_conn, mock_smb_file
    ):
        """Test that paths without leading slash get normalized."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            mock_smb_conn.listPath.return_value = [mock_smb_file]

            result = await tools.list_files("MyWorks")

        assert result["success"] is True
        assert result["path"] == "/MyWorks"

    @pytest.mark.asyncio
    async def test_download_file_success(self, tools, mock_smb_conn):
        """Test downloading a file saves it locally."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            fake_data = b"FITS header and data here\x00\x01\x02"
            mock_smb_conn.retrieveFile = MagicMock(
                side_effect=lambda share, path, stream: stream.write(fake_data)
            )

            result = await tools.download_file("/MyWorks/Sun/test.fits")

        assert result["success"] is True
        assert result["filename"] == "test.fits"
        assert result["file_type"] == "fits"
        assert result["size_bytes"] == len(fake_data)
        assert result["size_mb"] == round(len(fake_data) / (1024 * 1024), 2)
        assert "save_path" in result
        assert result["save_path"].endswith(".fits")

    @pytest.mark.asyncio
    async def test_download_file_jpg(self, tools, mock_smb_conn):
        """Test downloading a JPG file."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            fake_data = b"\xff\xd8\xff\xe0"  # JPEG header
            mock_smb_conn.retrieveFile = MagicMock(
                side_effect=lambda share, path, stream: stream.write(fake_data)
            )

            result = await tools.download_file("/MyWorks/Solar_photo/solar.jpg")

        assert result["success"] is True
        assert result["file_type"] == "jpg"
        assert result["save_path"].endswith(".jpg")

    @pytest.mark.asyncio
    async def test_download_file_empty(self, tools, mock_smb_conn):
        """Test graceful handling of empty files."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            mock_smb_conn.retrieveFile = MagicMock(
                side_effect=lambda share, path, stream: None
            )

            result = await tools.download_file("/MyWorks/empty.fits")

        assert result["success"] is False
        assert (
            "empty" in result["error"].lower() or "empty" in result["message"].lower()
        )

    @pytest.mark.asyncio
    async def test_download_file_offline(self, tools, mock_smb_conn):
        """Test graceful failure when telescope is offline."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            mock_smb_conn.connect.side_effect = TimeoutError("No response")

            result = await tools.download_file("/MyWorks/test.fits")

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_storage_info_success(self, tools, mock_smb_conn, mock_smb_dir):
        """Test storage info returns session directories."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            # Root listing returns session dirs
            solar_dir = MagicMock()
            solar_dir.filename = "Solar_photo"
            solar_dir.isDirectory = True
            solar_dir.file_size = 0
            solar_dir.last_write_time = 1718000000.0

            mock_smb_conn.listPath.side_effect = [
                [solar_dir],  # Ping check in _ensure_connected
                [solar_dir],  # Root listing
                [  # Solar_photo listing
                    MagicMock(
                        filename="img1.jpg",
                        isDirectory=False,
                        file_size=100,
                        last_write_time=0,
                    )
                ],
            ]

            result = await tools.get_storage_info()

        assert result["success"] is True
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["date"] == "Solar_photo"
        assert result["sessions"][0]["files"] == 1

    @pytest.mark.asyncio
    async def test_storage_info_offline(self, tools, mock_smb_conn):
        """Test storage info fails gracefully offline."""
        with patch("smb.SMBConnection.SMBConnection", return_value=mock_smb_conn):
            mock_smb_conn.connect.side_effect = ConnectionError("No route to host")

            result = await tools.get_storage_info()

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_reconnect_on_stale_connection(self, tools, mock_smb_conn):
        """Test reconnection when the SMB connection is stale."""
        second_conn = MagicMock()
        second_conn.connect = MagicMock()
        second_conn.listPath.return_value = []

        with patch(
            "smb.SMBConnection.SMBConnection", side_effect=[mock_smb_conn, second_conn]
        ):
            # First call works
            await tools.list_files("/")

            # Simulate stale connection on second call
            mock_smb_conn.listPath.side_effect = Exception("stale")

            result = await tools.list_files("/")

        assert result["success"] is True
