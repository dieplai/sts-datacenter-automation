from datetime import datetime, timezone

from data_loader.domain.models.google_drive_file import GoogleDriveFile
from data_loader.infrastructure.repositories.google_drive_file_repository import GoogleDriveFileRepository
from shared.domain.base_file_model import FileDownloadStatus, FileSource


def main() -> None:
    """Run a simple CRUD demo for GoogleDriveFileRepository."""
    repo = GoogleDriveFileRepository()

    file = GoogleDriveFile(
        name="change_repo_test.pdf",
        date_create=datetime.now(timezone.utc),
        date_download=None,
        dest_path=None,
        original=FileSource.GOOGLE_DRIVE,
        download_status=FileDownloadStatus.SUCCESS,
        drive_file_id="gdrive_demo_001",
        mime_type="application/pdf",
        parent_folder="root",
        size_bytes=2048,
    )
    kwargs ={
        "download_status":FileDownloadStatus.SUCCESS
    }
    # print("=== CREATE / UPSERT ===")
    # saved_id = repo.insert_one(file)
    # print(f"Saved file with id: {saved_id}")

    # print("\n=== READ BY ID ===")
    found = repo.find_one(_id = '69fab6334e8bcb73bca2cf04')
    print(found)

    # print("\n=== READ ALL ===")
    # result = repo.find_many(**kwargs)
    # for item in result :


    # print("\n=== UPDATE ===")
    # updated_file = found.model_copy(
    #     update={
    #         "name": "change_repo_test_v2.pdf",
    #         "date_create": datetime.now(tz=timezone.utc),
    #         "date_download": datetime.now(tz=timezone.utc) + timedelta(seconds=10),
    #         "dest_path": "/tmp/updated/change_repo_test_v2.pdf",
    #         "original": FileSource.GOOGLE_DRIVE,
    #         "drive_file_id": "gdrive_demo_001_updated",
    #         "mime_type": "application/xlsx",
    #         "parent_folder": "updated_root_folder",
    #         "size_bytes": 4096,
    #         "download_status": "success"
    #     }
            
    # )
    # repo.update_one(updated_file)

    # print("\n=== DELETE ===")
    deleted = repo.delete_one(_id = found.file_id)
    print(f"Deleted: {deleted}")


if __name__ == "__main__":
    main()
