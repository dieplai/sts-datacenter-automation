"""HTTP API downloader implementation."""

from datetime import datetime
from typing import Optional
from data_loader.domain.models.api_file import ApiFile
from data_loader.domain.models.download_response import DownloadResponse
from shared.domain.base_file_model import FileDownloadStatus
from shared.infrastructure.service import http_api_service


class ApiDownloader:
    """Implementation of Downloader for HTTP APIs."""

    def download(self, file: ApiFile, dest_path: str, **kwargs) -> list[DownloadResponse]:
        """
        Download a file from an HTTP API endpoint.

        Args:
            file: ApiFile model
            dest_path: Local destination path
            **kwargs: Optional parameters (headers)

        Returns:
            List of DownloadResponse objects
        """
        try:
            headers = self._parse_download_params(**kwargs)
            local_path = http_api_service.download_file(
                file.endpoint_url, dest_path, headers=headers
            )
            from shared.utils.logging import log_success
            log_success(f"Downloaded file {file.file_id} from API to {local_path}")
            
            response = DownloadResponse(
                id=file.file_id or "",
                local_path=local_path,
                file_download_status=FileDownloadStatus.SUCCESS,
            )
            return [response]
        except Exception as e:
            from shared.utils.logging import log_error
            log_error(f"Failed to download file {file.file_id} from API: {str(e)}")
            
            response = DownloadResponse(
                id=file.file_id or "",
                local_path="",
                file_download_status=FileDownloadStatus.FAILED,
            )
            return [response]

    def list_files(self, source_path: str, **kwargs) -> list[ApiFile]:
        """
        List files from an API endpoint.
        The API endpoint should return JSON with a list of file objects.

        Expected JSON format:
        {
            "files": [
                {
                    "file_id": "file_1",
                    "name": "document.pdf",
                    "url": "https://api.example.com/files/file_1",
                    "created_at": "2024-01-01T00:00:00"
                }
            ]
        }

        Args:
            source_path: API endpoint URL
            **kwargs: Optional parameters (headers)

        Returns:
            List of ApiFile models
        """
        headers = self._parse_list_params(**kwargs)
        response = http_api_service.get(source_path, headers=headers)

        files = []
        files_data = response.get("files", [])

        for file_data in files_data:
            file = ApiFile(
                file_id=file_data.get("file_id", ""),
                name=file_data.get("name", ""),
                date_create=datetime.fromisoformat(
                    file_data.get("created_at", datetime.now().isoformat())
                ),
                original="api",
                endpoint_url=file_data.get("url", source_path),
                content_type=file_data.get("content_type"),
                request_params=file_data.get("params", {}),
            )
            files.append(file)

        from shared.utils.logging import log_success
        log_success(f"Listed {len(files)} files from API endpoint {source_path}")
        return files

    def _parse_download_params(self, **kwargs) -> Optional[dict]:
        """
        Parse kwargs into download parameters.

        Args:
            **kwargs: Raw parameters

        Returns:
            Parsed headers dict or None
        """
        return kwargs.get("headers", None)

    def _parse_list_params(self, **kwargs) -> Optional[dict]:
        """
        Parse kwargs into list_files parameters.

        Args:
            **kwargs: Raw parameters

        Returns:
            Parsed headers dict or None
        """
        return kwargs.get("headers", None)
