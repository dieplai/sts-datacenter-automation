"""AWS S3 service integration."""

from typing import Any, Optional
from shared.infrastructure.setting import S3Setting
from shared.utils.logging import log_success


class S3Service:
    """
    Singleton AWS S3 client.
    Manages S3 operations for downloading and managing objects.
    """

    _instance: "S3Service | None" = None
    _client: Any = None

    def __new__(cls) -> "S3Service":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize S3 client."""
        try:
            import boto3

            setting = S3Setting()
            self._client = boto3.client(
                "s3",
                region_name=setting.s3_region,
                aws_access_key_id=setting.aws_access_key_id,
                aws_secret_access_key=setting.aws_secret_access_key,
            )
            log_success("Connected to AWS S3 successfully")
        except ImportError:
            raise ImportError("boto3 not installed. Install: pip install boto3")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize S3 service: {e}")

    @property
    def client(self) -> Any:
        """Get the S3 client instance."""
        if self._client is None:
            raise RuntimeError("S3 client not initialized")
        return self._client

    def download_file(self, bucket: str, key: str, dest_path: str) -> str:
        """
        Download a file from S3.

        Args:
            bucket: S3 bucket name
            key: S3 object key (path)
            dest_path: Local destination path

        Returns:
            Local file path
        """
        try:
            import os

            os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
            self.client.download_file(bucket, key, dest_path)
            return dest_path
        except Exception as e:
            raise RuntimeError(f"Failed to download file from S3: {e}")

    def list_objects(
        self, bucket: str, prefix: str = "", max_results: int = 1000
    ) -> list[dict]:
        """
        List objects in an S3 bucket.

        Args:
            bucket: S3 bucket name
            prefix: Optional prefix to filter objects
            max_results: Maximum number of results

        Returns:
            List of object metadata dictionaries
        """
        try:
            response = self.client.list_objects_v2(
                Bucket=bucket, Prefix=prefix, MaxKeys=max_results
            )
            return response.get("Contents", [])
        except Exception as e:
            raise RuntimeError(f"Failed to list objects from S3: {e}")

    def get_object_metadata(self, bucket: str, key: str) -> dict:
        """Get metadata for a specific S3 object."""
        try:
            response = self.client.head_object(Bucket=bucket, Key=key)
            return {
                "key": key,
                "size": response.get("ContentLength"),
                "etag": response.get("ETag"),
                "last_modified": response.get("LastModified"),
                "content_type": response.get("ContentType"),
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get S3 object metadata: {e}")

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful for testing)."""
        cls._instance = None
        cls._client = None


# Convenient global reference
s3_service = S3Service()
