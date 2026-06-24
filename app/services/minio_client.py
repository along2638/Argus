import asyncio
import base64
import uuid
from datetime import datetime, timezone
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MinIOService:
    """Async MinIO client wrapper for image storage."""

    _client: Optional[Minio] = None

    @classmethod
    def get_client(cls) -> Minio:
        """Get or create MinIO client."""
        if cls._client is None:
            cls._client = Minio(
                endpoint=settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
            logger.info("minio_client_created", endpoint=settings.MINIO_ENDPOINT)
        return cls._client

    @classmethod
    async def ensure_bucket(cls) -> None:
        """Ensure the bucket exists."""
        client = cls.get_client()
        bucket_name = settings.MINIO_BUCKET

        try:
            exists = await asyncio.to_thread(client.bucket_exists, bucket_name)
            if not exists:
                await asyncio.to_thread(client.make_bucket, bucket_name)
                logger.info("minio_bucket_created", bucket=bucket_name)
            else:
                logger.debug("minio_bucket_exists", bucket=bucket_name)
        except S3Error as e:
            logger.error("minio_bucket_error", error=str(e))
            raise

    @classmethod
    async def upload_image(
        cls,
        image_bytes: bytes,
        stream_id: str,
        content_type: str = "image/jpeg",
        max_retries: int = 3,
    ) -> Optional[str]:
        """Upload image to MinIO with retry logic.

        Returns:
            MinIO object key on success, None on failure (with base64 fallback logged)
        """
        client = cls.get_client()
        bucket_name = settings.MINIO_BUCKET

        # Generate object key: {YYYY}/{MM}/{DD}/{stream_id}/{timestamp}_{uuid}.jpg
        now = datetime.now(tz=timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        object_key = f"{now.year}/{now.month:02d}/{now.day:02d}/{stream_id}/{timestamp}_{uuid.uuid4().hex[:8]}.jpg"

        for attempt in range(max_retries):
            try:
                from io import BytesIO

                data_stream = BytesIO(image_bytes)
                await asyncio.to_thread(
                    client.put_object,
                    bucket_name,
                    object_key,
                    data_stream,
                    len(image_bytes),
                    content_type,
                )
                logger.info(
                    "image_uploaded",
                    bucket=bucket_name,
                    object_key=object_key,
                    size_bytes=len(image_bytes),
                )
                return object_key
            except S3Error as e:
                logger.warning(
                    "image_upload_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))

        # All retries failed - log base64 as fallback
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        logger.error(
            "image_upload_failed_fallback",
            stream_id=stream_id,
            image_base64_preview=b64_image[:100] + "...",
            image_size_bytes=len(image_bytes),
        )
        return None

    @classmethod
    def get_image_url(cls, object_key: str) -> str:
        """Get the full URL for an image object."""
        protocol = "https" if settings.MINIO_SECURE else "http"
        return f"{protocol}://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET}/{object_key}"

    @classmethod
    def close(cls) -> None:
        """Release MinIO client resources."""
        cls._client = None
        logger.info("minio_client_closed")


# Singleton instance
minio_service = MinIOService()
