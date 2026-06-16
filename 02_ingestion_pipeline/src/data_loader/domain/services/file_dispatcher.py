"""File dispatcher using Registry pattern."""

from shared.domain import BaseFileModel, FileSource
from data_loader.domain.ports.downloader import Downloader
from data_loader.domain.models.download_response import DownloadResponse
from shared.utils.logging import log_success


class FileDispatcher:
    """
    Registry-based dispatcher.
    Maps FileSource → Downloader implementation.
    No if/elif chain — add new source by registering it.
    """

    def __init__(self):
        self._registry: dict[FileSource, Downloader] = {}

    def register(self, source: FileSource, downloader: Downloader) -> None:
        """
        Register a downloader for a source type.

        Args:
            source: FileSource enum value
            downloader: Downloader implementation
        """
        self._registry[source] = downloader
        log_success(f"Registered downloader for {source.value}")

    def download(self, file: BaseFileModel, dest_path: str, **kwargs) -> list[DownloadResponse]:
        """
        Look up registry and call the appropriate downloader.

        Args:
            file: File to download
            dest_path: Local destination path
            **kwargs: Downloader-specific parameters forwarded to
                Downloader.download (and parse_param).

        Returns:
            List of DownloadResponse objects with file id, local path, and status

        Raises:
            ValueError: If source is not registered
        """
        handler = self._registry.get(file.original)
        if handler is None:
            registered_sources = [s.value for s in self._registry.keys()]
            raise ValueError(
                f"No downloader registered for source: {file.original.value}. "
                f"Registered sources: {registered_sources}"
            )
        return handler.download(file, dest_path, **kwargs)

    def get_file_info(self, source: FileSource,**kwargs) -> BaseFileModel:
        """
        get file info from source

        Args:
            source: FileSource enum value
            source_path: Source-specific path (folder ID, S3 prefix, etc.)

        Returns:
            List of file models

        Raises:
            ValueError: If source is not registered
        """
        handler = self._registry.get(source)
        if handler is None:
            registered_sources = [s.value for s in self._registry.keys()]
            raise ValueError(
                f"No downloader registered for source: {source.value}. "
                f"Registered sources: {registered_sources}"
            )
        folder_name = kwargs.get("file_id")
        print(folder_name)
        return handler.get_file_info(**kwargs)

    def is_registered(self, source: FileSource) -> bool:
        """Check if a source is registered."""
        return source in self._registry

    def get_registered_sources(self) -> list[str]:
        """Get list of registered source names."""
        return [s.value for s in self._registry.keys()]
    def regist_all(self) -> None:
        """Register all downloader sources from application downloaders."""
        from data_loader.application.downloaders.api_downloader import ApiDownloader
        from data_loader.application.downloaders.google_drive_downloader import (
            GoogleDriveDownloader,
        )
        from data_loader.application.downloaders.s3_downloader import S3Downloader

        self.register(FileSource.GOOGLE_DRIVE, GoogleDriveDownloader())
        self.register(FileSource.S3, S3Downloader())
        self.register(FileSource.API, ApiDownloader())
        
