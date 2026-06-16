"""Data Loader application entry-points."""

from shared.domain import FileSource
from data_loader.domain.services.file_dispatcher import FileDispatcher
from data_loader.domain.models.download_response import DownloadResponse
from shared.domain.base_file_model import BaseFileModel
from shared.utils.logging import info




def run_data_loader(
    source: str,
    execution_date: str,
    dest_path: str,
    mode: str = "skip",
    **kwargs,
) -> list[DownloadResponse]:
    """
    Entry-point for Data Loader.
    Pure Python — does not know about Airflow or any framework.
    All dependencies are wired here.

    Args:
        source: File source type (google_drive, s3, api)
        execution_date: Execution date string (YYYY-MM-DD)
        dest_path: Local directory to save files
        mode: Download mode. Use "replace" to re-download and replace
            existing local files.
        **kwargs: Source-specific parameters forwarded to the downloader's
            list_files / download / parse_param (e.g. source_path, file_id,
            folder_name, headers).

    Returns:
        List of DownloadResponse objects with file id, local path, and status
    """
    # try:
        # Wire dependencies (Dependency Injection)
    dispatcher = FileDispatcher()
    dispatcher.regist_all()


    # Map source string to enum
    source_enum = FileSource(source)
    
    # List files from source
    info(f"Starting data load from {source} @ {execution_date}")
    file_info:BaseFileModel = dispatcher.get_file_info(source_enum,**kwargs)
    responses = dispatcher.download(
        file=file_info,
        dest_path=dest_path,
        mode=mode,
        **kwargs,
    )
    return responses

    # except Exception as e:
    #     error_msg = f"Data loader failed: {str(e)}"
    #     log_error(error_msg)


if __name__ == "__main__":
    run_data_loader(
        source=FileSource.GOOGLE_DRIVE.value,
        execution_date="2026-05-01",
        dest_path="tests/data",
        file_id ="1s65CZOPLT-WMGxbxMTKXl72aIBf14Kqn"
    )
