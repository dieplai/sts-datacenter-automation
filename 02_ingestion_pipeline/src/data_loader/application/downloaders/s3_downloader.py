"""AWS S3 downloader implementation."""

from datetime import datetime
from data_loader.domain.models.s3_file import S3File
from data_loader.domain.models.download_response import DownloadResponse
from shared.domain.base_file_model import FileDownloadStatus
from shared.infrastructure.service import s3_service
from shared.infrastructure.setting import S3Setting


class S3Downloader:
    """Implementation of Downloader for AWS S3."""

    def __init__(self):
        self.setting = S3Setting()

    def download(self, file: S3File, dest_path: str, **kwargs) -> list[DownloadResponse]:
        """
        Download a file from S3.

        Args:
            file: S3File model
            dest_path: Local destination path
            **kwargs: Additional downloader-specific parameters

        Returns:
            List of DownloadResponse objects
        """
        try:
            self._parse_download_params(**kwargs)
            
            local_path = s3_service.download_file(file.bucket, file.key, dest_path)
            from shared.utils.logging import log_success
            log_success(f"Downloaded file {file.file_id} from S3 to {local_path}")
            
            response = DownloadResponse(
                id=file.file_id or "",
                local_path=local_path,
                file_download_status=FileDownloadStatus.SUCCESS,
            )
            return [response]
        except Exception as e:
            from shared.utils.logging import log_error
            log_error(f"Failed to download file {file.file_id} from S3: {str(e)}")
            
            response = DownloadResponse(
                id=file.file_id or "",
                local_path="",
                file_download_status=FileDownloadStatus.FAILED,
            )
            return [response]

    def list_files(self, source_path: str, **kwargs) -> list[S3File]:
        """
        List objects from an S3 bucket/prefix.

        Args:
            source_path: S3 key prefix (bucket/prefix format or just prefix)
            **kwargs: Additional downloader-specific parameters

        Returns:
            List of S3File models
        """
        self._parse_list_params(**kwargs)
        
        # Parse source_path as bucket or bucket/prefix
        if "/" in source_path:
            bucket, prefix = source_path.split("/", 1)
        else:
            bucket = source_path
            prefix = ""

        objects = s3_service.list_objects(bucket, prefix)
        files = []

        for obj in objects:
            # Skip directories (keys ending with /)
            if obj["Key"].endswith("/"):
                continue

            file = S3File(
                file_id=obj["Key"],
                name=obj["Key"].split("/")[-1],
                date_create=obj["LastModified"].replace(tzinfo=None),
                original="s3",
                bucket=bucket,
                key=obj["Key"],
                size_bytes=obj["Size"],
            )
            files.append(file)

        from shared.utils.logging import log_success
        log_success(f"Listed {len(files)} objects from S3 {source_path}")
        return files

    def _parse_download_params(self, **kwargs) -> None:
        """
        Parse kwargs into download parameters.

        Args:
            **kwargs: Raw parameters (currently no specific params needed)
        """
        pass

    def _parse_list_params(self, **kwargs) -> None:
        """
        Parse kwargs into list_files parameters.

        Args:
            **kwargs: Raw parameters (currently no specific params needed)
        """
        pass
