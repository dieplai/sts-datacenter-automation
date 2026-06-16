"""Generate a Google Drive OAuth token for local/Airflow runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


@dataclass(frozen=True)
class FunctionGoogleDriveAuthCommand:
    credentials_path: str | Path | None = None
    token_path: str | Path | None = None
    scopes: list[str] | None = None
    open_browser: bool = True


GoogleDriveAuthCommand = FunctionGoogleDriveAuthCommand


class GoogleDriveAuthCommandHandler:
    project_root = Path(__file__).resolve().parents[1]
    default_scopes = ["https://www.googleapis.com/auth/drive.readonly"]

    def handle(self, command: GoogleDriveAuthCommand) -> Credentials:
        """Load, refresh, or create Google OAuth credentials."""
        root_credentials = self.project_root / "client_secret.json"
        token_dir_credentials = self.project_root / "google_tokens" / "client_secret.json"
        default_credentials = root_credentials
        if not root_credentials.exists() and token_dir_credentials.exists():
            default_credentials = token_dir_credentials

        credentials_file = Path(
            command.credentials_path
            or os.getenv("GOOGLE_CREDENTIALS_PATH")
            or default_credentials
        )
        token_file = Path(
            command.token_path
            or os.getenv("GOOGLE_TOKEN_PATH")
            or self.project_root / "google_tokens" / "client_secret.token.json"
        )
        scopes = command.scopes or self.default_scopes

        creds = None
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), scopes)

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                token_file.unlink(missing_ok=True)
                creds = None

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_file),
                scopes,
            )
            creds = flow.run_local_server(
                port=0,
                open_browser=command.open_browser,
                access_type="offline",
                prompt="consent",
            )

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds


def main() -> None:
    handler = GoogleDriveAuthCommandHandler()
    creds = handler.handle(FunctionGoogleDriveAuthCommand())
    print(f"Token valid: {creds.valid}")


if __name__ == "__main__":
    main()
