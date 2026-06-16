"""Data Loader domain ports (interfaces)."""

from data_loader.domain.ports.downloader import Downloader
from data_loader.domain.ports.file_repository import FileRepository

__all__ = ["Downloader", "FileRepository"]
