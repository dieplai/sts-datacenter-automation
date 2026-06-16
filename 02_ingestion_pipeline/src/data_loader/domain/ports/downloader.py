"""Downloader port (interface) definition."""

from typing import Protocol
from shared.domain import BaseFileModel
from data_loader.domain.models.download_response import DownloadResponse


class Downloader(Protocol):
    """
    Contract that every downloader must implement.
    Domain does not know the concrete implementation.
    """

    def download(self, file: BaseFileModel, dest_path: str, **kwargs) -> list[DownloadResponse]:
        """
        Download a file from source to local destination.

        Args:
            file: File model with source-specific metadata
            dest_path: Local destination path
            **kwargs: Additional downloader-specific parameters

        Returns:
            List of DownloadResponse objects with file id, local path, and status
        """
        ...

    def get_file_info(self, **kwargs) -> BaseFileModel:
        """
        List all files from source path.

        Args:
            **kwargs: Downloader-specific parameters (e.g. source_path,
                file_id, folder_name, headers).

        Returns:
            List of file models from the source
        """
        ...
