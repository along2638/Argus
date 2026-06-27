"""Tests for MinIO client module."""

from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO

import pytest

from app.services.minio_client import MinIOService


class TestMinIOService:
    """Test MinIOService class."""

    def test_get_client_creates_once(self):
        """Test client is created once and reused."""
        MinIOService._client = None
        with patch("app.services.minio_client.Minio") as mock_minio:
            mock_minio.return_value = MagicMock()
            client1 = MinIOService.get_client()
            client2 = MinIOService.get_client()
            assert client1 is client2
            mock_minio.assert_called_once()

    def test_close_resets_client(self):
        """Test close resets the client."""
        MinIOService._client = MagicMock()
        MinIOService.close()
        assert MinIOService._client is None

    def test_get_image_url(self):
        """Test URL generation."""
        MinIOService._client = None
        url = MinIOService.get_image_url("2024/01/01/cam-1/test.jpg")
        assert "2024/01/01/cam-1/test.jpg" in url
        assert "http://" in url

    @pytest.mark.asyncio
    async def test_ensure_bucket_exists(self):
        """Test ensure_bucket when bucket already exists."""
        mock_client = MagicMock()
        mock_client.bucket_exists = MagicMock(return_value=True)
        MinIOService._client = mock_client

        await MinIOService.ensure_bucket()

        mock_client.bucket_exists.assert_called_once()
        mock_client.make_bucket.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_bucket_creates(self):
        """Test ensure_bucket creates bucket when missing."""
        mock_client = MagicMock()
        mock_client.bucket_exists = MagicMock(return_value=False)
        mock_client.make_bucket = MagicMock()
        MinIOService._client = mock_client

        await MinIOService.ensure_bucket()

        mock_client.make_bucket.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_success(self):
        """Test successful image upload."""
        mock_client = MagicMock()
        mock_client.put_object = MagicMock()
        MinIOService._client = mock_client

        result = await MinIOService.upload_image(b"fake image bytes", "cam-1")

        assert result is not None
        assert "cam-1" in result
        mock_client.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_retry_on_failure(self):
        """Test upload retries on S3Error."""
        from minio.error import S3Error
        from unittest.mock import MagicMock as MockResponse

        mock_resp = MockResponse()
        mock_resp.status = 404

        mock_client = MagicMock()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise S3Error(response=mock_resp, code="NoSuchKey", message="Temporary failure", resource="/test", request_id="req-1", host_id="host-1")

        mock_client.put_object = side_effect
        MinIOService._client = mock_client

        result = await MinIOService.upload_image(b"fake image", "cam-1", max_retries=3)

        assert result is not None

    @pytest.mark.asyncio
    async def test_upload_all_retries_fail(self):
        """Test upload returns None when all retries fail."""
        from minio.error import S3Error
        from unittest.mock import MagicMock as MockResponse

        mock_resp = MockResponse()
        mock_resp.status = 500

        mock_client = MagicMock()
        mock_client.put_object = MagicMock(side_effect=S3Error(response=mock_resp, code="InternalError", message="Persistent failure", resource="/test", request_id="req-1", host_id="host-1"))
        MinIOService._client = mock_client

        result = await MinIOService.upload_image(b"fake image", "cam-1", max_retries=2)

        assert result is None
