"""File repository port (interface) definition."""

from typing import Protocol
from shared.domain import BaseFileModel


class FileRepository(Protocol):
    """
    Contract for persisting file metadata.
    Domain defines interface; Infrastructure implements it.
    """

    def save(self, file: BaseFileModel) -> str:
        """
        Save file metadata.

        Args:
            file: File model to persist

        Returns:
            File ID
        """
        ...

    def find_by_id(self, file_id: str) -> BaseFileModel | None:
        """Find a file by ID."""
        ...

    def find_all(self) -> list[BaseFileModel]:
        """Find all files."""
        ...

    def find_by_source(self, source: str) -> list[BaseFileModel]:
        """Find files by source type."""
        ...

    def delete_by_id(self, file_id: str) -> bool:
        """Delete a file by ID."""
        ...
