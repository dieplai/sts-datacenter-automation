"""Google Drive service integration."""

import json
import os
from pathlib import Path
from typing import Any

from shared.infrastructure.setting import GoogleDriveSetting
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
from tqdm import tqdm

from shared.utils.logging import info, log_success


DEFAULT_GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _is_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _get_google_drive_scopes() -> list[str]:
    raw_scopes = os.getenv("GOOGLE_DRIVE_SCOPES")
    if not raw_scopes:
        return DEFAULT_GOOGLE_DRIVE_SCOPES

    return [
        scope.strip()
        for scope in raw_scopes.replace(",", " ").split()
        if scope.strip()
    ]


def _get_google_token_path(credentials_file: Path) -> Path:
    return Path(
        os.getenv(
            "GOOGLE_TOKEN_PATH",
            str(credentials_file.with_name(f"{credentials_file.stem}.token.json")),
        )
    )


def generate_google_oauth_token(
    credentials_file: str | Path,
    token_path: str | Path | None = None,
    scopes: list[str] | None = None,
    *,
    host: str = "localhost",
    bind_addr: str | None = None,
    port: int = 0,
    open_browser: bool = True,
) -> OAuthCredentials:
    """Run interactive OAuth once and persist the generated token."""
    credentials_path = Path(credentials_file)
    token_file = Path(token_path) if token_path else _get_google_token_path(credentials_path)
    expected_scopes = scopes or _get_google_drive_scopes()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path),
        expected_scopes,
    )
    creds = flow.run_local_server(
        host=host,
        bind_addr=bind_addr,
        port=port,
        open_browser=open_browser,
        access_type="offline",
        prompt="consent",
    )

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    return creds


class GoogleDriveService:
    """
    Singleton Google Drive API client.
    Manages authentication and provides methods for interacting with Google Drive.
    """

    _instance: "GoogleDriveService | None" = None
    _service: Any = None

    def __new__(cls) -> "GoogleDriveService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize Google Drive API client."""
        try:
            setting = GoogleDriveSetting()
            credentials_path = str(setting.google_credentials_path)

            # Verify credentials file exists
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Google credentials file not found: {credentials_path}"
                )

            creds = self._load_credentials(credentials_path)
            self._service = build("drive", "v3", credentials=creds)
            log_success("Connected to Google Drive API successfully")
        except ImportError:
            raise ImportError(
                "Google Drive API libraries not installed. "
                "Install: pip install google-auth-httplib2 google-api-python-client"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Google Drive service: {e}")

    def _load_credentials(self, credentials_path: str) -> Any:
        """Load either service-account credentials or OAuth client credentials."""
        credentials_file = Path(credentials_path)
        credentials_info = json.loads(credentials_file.read_text())

        if credentials_info.get("type") == "service_account":
            return ServiceAccountCredentials.from_service_account_file(
                str(credentials_file),
                scopes=_get_google_drive_scopes(),
            )

        if "installed" in credentials_info or "web" in credentials_info:
            return self._load_oauth_credentials(credentials_file)

        raise ValueError(
            "Unsupported Google credentials format. Expected service account JSON "
            "or OAuth client JSON with 'installed'/'web' key."
        )

    def _load_oauth_credentials(self, credentials_file: Path) -> OAuthCredentials:
        """Load cached OAuth token, refresh it, or create a new token from client secrets."""
        token_path = _get_google_token_path(credentials_file)

        creds = None
        expected_scopes = _get_google_drive_scopes()
        if token_path.exists():
            token_info = json.loads(token_path.read_text())
            expected_scope_set = set(expected_scopes)
            token_scopes = set(token_info.get("scopes") or token_info.get("scope", "").split())
            if token_scopes and token_scopes != expected_scope_set:
                info(
                    "Google OAuth token scopes do not match configured scopes. "
                    "Removing cached token so OAuth can be re-authorized."
                )
                token_path.unlink()
            else:
                creds = OAuthCredentials.from_authorized_user_file(
                    str(token_path),
                    expected_scopes,
                )

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                if not self._is_invalid_grant_error(exc):
                    raise

                info(
                    "Google OAuth token has expired or was revoked. "
                    "Removing cached token so OAuth can be re-authorized."
                )
                token_path.unlink(missing_ok=True)
                creds = None

        if not creds or not creds.valid:
            if _is_enabled(os.getenv("GOOGLE_ALLOW_INTERACTIVE_AUTH")):
                return generate_google_oauth_token(
                    credentials_file,
                    token_path,
                    expected_scopes,
                )

            raise RuntimeError(
                "Google OAuth token is missing, invalid, expired, or revoked. "
                f"Regenerate it from {credentials_file} and save it to {token_path}. "
                "Local command: PYTHONPATH=src uv run python "
                "scripts/google_drive_auth.py"
            )

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        return creds

    @staticmethod
    def _is_invalid_grant_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "invalid_grant" in message or "expired or revoked" in message

    @property
    def service(self) -> Any:
        """Get the Google Drive service instance."""
        if self._service is None:
            raise RuntimeError("Google Drive service not initialized")
        return self._service

    def download_file(
        self, file_id: str, dest_path: str, chunk_size: int = 1024 * 1024
    ) -> str:
        """
        Download a file from Google Drive with streaming to disk.
        Writes data in chunks to avoid memory overflow for large files.
        Shows progress using tqdm progress bar.

        Args:
            file_id: Google Drive file ID
            dest_path: Local destination path
            chunk_size: Size of each chunk to write (default 1MB = 1024*1024 bytes)

        Returns:
            Local file path
        """
        try:
            # Get file metadata to get total size
            file_metadata = self.get_file_metadata(file_id)
            total_size = int(file_metadata.get("size", 0))
            file_name = file_metadata.get("name", "Unknown")

            request = self.service.files().get_media(fileId=file_id)

            # Create destination directory
            is_exist = os.path.exists(dest_path)
            info(f"FIle {dest_path} is exist return path only ")
            if is_exist == False: 
                os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

                # Stream download directly to disk with progress bar
                with open(dest_path, "wb") as f:
                    downloader = MediaIoBaseDownload(f, request, chunksize=chunk_size)

                    with tqdm(total=total_size, unit="B", unit_scale=True, desc=file_name) as pbar:
                        done = False
                        while not done:
                            status, done = downloader.next_chunk()
                            if status:
                                # Update progress bar with bytes downloaded in this chunk
                                bytes_downloaded = int(status.resumable_progress)
                                pbar.update(bytes_downloaded - pbar.n)

            return dest_path
        except Exception as e:
            raise RuntimeError(f"Failed to download file from Google Drive: {e}")
        
    def upload_file(self, file_path: str, folder_id: str) -> str:
        """Upload file lên lại google drive, trả về file_id, sau này test cho thư viện"""
        
        from googleapiclient.http import MediaFileUpload
        
        file_name = Path(file_path).name
        media = MediaFileUpload(file_path, resumable=True)
        file_metadata = {"name": file_name, "parents": [folder_id]}
        uploaded = self.service.files().create(
            body = file_metadata,
            media_body = media,
            fields = "id",
        ).execute()
        
        return uploaded["id"]
        

    def list_files(
        self,
        file_id: str | None = None,
        max_results: int = 100,
    ) -> list[dict]:
        """
        List files in a Google Drive folder.

        Args:
            file_id: Google Drive folder/file ID used as parent container.
            max_results: Maximum number of results to return

        Returns:
            List of file metadata dictionaries
        """
        try:
            info(f"Google Drive file_id: {file_id}")
            query = f"'{file_id}' in parents and trashed=false"
            request = self.service.files().list(
                q=query,
                spaces="drive",
                fields="files(id, name, mimeType, createdTime, modifiedTime, size)",
                pageSize=max_results,
            )
            results = request.execute()
                
            return results.get("files", [])
        except Exception as e:
            raise RuntimeError(f"Failed to list files from Google Drive: {e}")

    def get_file_metadata(self, file_id: str) -> dict:
        """Get metadata for a specific file."""
        try:
            request = self.service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, createdTime, modifiedTime, size, parents",
            )
            return request.execute()
        except Exception as e:
            raise RuntimeError(f"Failed to get file metadata from Google Drive: {e}")
        
    def get_file_by_name(self, name: str) -> dict:
        """
        step1: build_query

        step2: execute_query
            step2.1: call drive api list with query
            step2.2: extract files from response

        step3: validate_result
            step3.1: ensure at least one folder exists
            step3.2: ensure only one folder matches

        step4: return_result
            step4.1: return first folder
        """

        # step1.1 + step1.2 + step1.3: build query
        query = (
            "mimeType='application/vnd.google-apps.folder' "
            f"name='{name}' "
            "and trashed=false"
        )

        # step2.1: call drive api list with query
        results = self.service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="allDrives",
        ).execute()

        # step2.2: extract files from response
        folders = results.get("files", [])

        # step3.1: ensure at least one folder exists
        if not folders:
            raise Exception(f"Khong tim thay folder name '{name}'")


        # step4.1: return first folder
        return folders[0]["id"]

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful for testing)."""
        cls._instance = None
        cls._service = None


class LazyGoogleDriveService:
    """Proxy that initializes Google Drive only when a method is used."""

    def __getattr__(self, name: str) -> Any:
        return getattr(GoogleDriveService(), name)


google_drive_service = LazyGoogleDriveService()
