from pathlib import Path
from pydantic import field_validator

from shared.infrastructure.setting.base_setting import AppBaseSetting

class GoogleDriveSetting(AppBaseSetting):
    google_credentials_path: str
    google_drive_export_folder_id: str = ""

    @field_validator("google_credentials_path", mode="before")
    @classmethod
    def resolve_path(cls, v) -> str:
        if v is None:
            return v

        path = Path(v)

        # nếu đã là absolute thì giữ nguyên
        if path.is_absolute():
            return str(path)

        # tránh tạo instance mới mỗi lần
        base_path = cls.PROJECT_ROOT

        return str(base_path / path)
