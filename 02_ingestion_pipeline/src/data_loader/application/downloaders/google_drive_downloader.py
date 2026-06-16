"""Google Drive downloader implementation."""

import os
from datetime import datetime

from data_loader.domain.models.google_drive_file import GoogleDriveFile
from data_loader.domain.models.download_response import DownloadResponse
from shared.infrastructure.mongo.repositories.google_drive_file_repository import GoogleDriveFileRepository
from shared.domain.base_file_model import FileDownloadStatus
from shared.infrastructure.service import google_drive_service
from shared.utils.logging import debug, info, log_success, log_error

class GoogleDriveDownloader:
    """Implementation of Downloader for Google Drive."""
    def __init__(self):
        self.repo = GoogleDriveFileRepository()

    def download(self, file: GoogleDriveFile, dest_path: str, **kwargs) -> list[DownloadResponse]:
        """
        Download a file or folder from Google Drive.

        Args:
            file: GoogleDriveFile model
            dest_path: Local destination path
            **kwargs: Additional downloader-specific parameters

        Returns:
            List of DownloadResponse objects with file id, local path, and status
        """
        mode = str(kwargs.get("mode", "skip")).lower()
        local_path = self._resolve_file_dest_path(file.name, dest_path)
        responses: list[DownloadResponse] = []
        self._download_handler(file, local_path, responses, mode=mode)
        

        return responses

    def _download_handler(
        self,
        file_model: GoogleDriveFile,
        dest_path: str,
        responses: list[DownloadResponse],
        mode: str = "skip",
    ) -> str:
        """
        Recursively handle downloading files or folders from Google Drive.
        
        Args:
            file_model: File metadata dict from Google Drive API
            dest_path: Local destination path
            responses: List to accumulate DownloadResponse objects
            
        Returns:
            Local file or directory path
        """
            
        # Check if it's a folder
        if file_model.mime_type == "application/vnd.google-apps.folder":
            # Create folder and download all children recursively
            os.makedirs(dest_path, exist_ok=True)
            
            files_metadata = google_drive_service.list_files(file_id=file_model.drive_file_id)
            debug(f"Raw metadata files number: {len(files_metadata)}")
            
            if len(files_metadata) != 0:    
                for child_metadata in files_metadata:
                    child_file = GoogleDriveFile._to_model(child_metadata)
                    if not self._is_csv_file(child_file):
                        info(
                            "Skip non-CSV Google Drive file "
                            f"{child_file.name} ({child_file.mime_type})"
                        )
                        continue
                    child_dest_path = os.path.join(dest_path, child_file.name)
                    self._download_handler(child_file, child_dest_path, responses, mode=mode)
            
            log_success(f"Downloaded folder {file_model.name} to {dest_path}")
            return dest_path

        
        # Case: single file
        try:
            if not self._is_csv_file(file_model):
                info(
                    "Skip non-CSV Google Drive file "
                    f"{file_model.name} ({file_model.mime_type})"
                )
                return dest_path

            local_path = dest_path
            is_exists = os.path.exists(local_path)
            should_replace = mode == "replace"
            download_path = local_path
            replace_temp_path = None
            if should_replace and is_exists:
                if os.path.isfile(local_path):
                    replace_temp_path = f"{local_path}.download"
                    if os.path.exists(replace_temp_path):
                        os.remove(replace_temp_path)
                    download_path = replace_temp_path
                    info(f"Replace mode: downloading new file for {local_path}")
                else:
                    raise RuntimeError(
                        f"Replace mode expected a file but found non-file path: {local_path}"
                    )

            if is_exists == False or should_replace:
                downloaded_path = google_drive_service.download_file(
                    file_model.drive_file_id, download_path
                )
                if replace_temp_path is not None:
                    os.replace(downloaded_path, local_path)
                    info(f"Replace mode: replaced old local file {local_path}")
                else:
                    local_path = downloaded_path

                info("Convert Data to Model")
                file_response: GoogleDriveFile = file_model.model_copy(
                    update={
                        "dest_path": local_path,
                        "date_download": datetime.now(),
                        "download_status": FileDownloadStatus.SUCCESS,
                    }
                )
                info(f"Finish download file {file_model.name}")
                self.repo.upsert_by_drive_file_id(file_response)
            else:
                info(f"Skip existing file {file_model.name} at {local_path}")

            # Create and append DownloadResponse
            download_response = DownloadResponse(
                id=file_model.drive_file_id or "",
                local_path=local_path,
                file_download_status=FileDownloadStatus.SUCCESS,
            )
            responses.append(download_response)
            log_success(f"Downloaded file {file_model.name} from Google Drive to {local_path}")
        except Exception as e:
            file_response = file_model.model_copy(
                update={
                    "date_download": datetime.now(),
                    "download_status": FileDownloadStatus.FAILED,
                }
            )
            debug(f"Failed to download file {file_model.name}: {str(e)}")
            self.repo.upsert_by_drive_file_id(file_response)

            # Create and append DownloadResponse with FAILED status
            download_response = DownloadResponse(
                id=file_model.drive_file_id or "",
                local_path="",
                file_download_status=FileDownloadStatus.FAILED,
            )
            responses.append(download_response)
            log_error(f"Failed to download file {file_model.name}: {str(e)}")


    def get_file_info(self, **kwargs) -> GoogleDriveFile:
        # parse parameter from **kwargs — dùng `or` để bỏ qua empty string
        file_id = kwargs.get("file_id") or kwargs.get("folder_id")
    
        # fallback theo folder name
        if file_id is None:
            file_name = kwargs.get("file_name", kwargs.get("folder_name",None))
            if file_name == None:
                raise Exception("file name and file id cannot None")
            file_id = google_drive_service.get_folder_by_name(kwargs)

        file_metadata = google_drive_service.get_file_metadata(file_id)
        return GoogleDriveFile._to_model(file_metadata)

    
    
    def _resolve_file_dest_path(self, file_name: str, dest_path: str) -> str:
        """Resolve a valid file path for a Drive file download."""
        if dest_path.endswith(os.sep) or os.path.isdir(dest_path):
            os.makedirs(dest_path, exist_ok=True)
            return os.path.join(dest_path, file_name)

        dest_name = os.path.basename(dest_path)
        if dest_name == file_name or os.path.splitext(dest_name)[1]:
            os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
            return dest_path

        os.makedirs(dest_path, exist_ok=True)
        return os.path.join(dest_path, file_name)

    @staticmethod
    def _is_csv_file(file_model: GoogleDriveFile) -> bool:
        """Return True for CSV files only."""
        file_name = (file_model.name or "").lower()
        mime_type = (file_model.mime_type or "").lower()
        return file_name.endswith(".csv") or mime_type == "text/csv"
