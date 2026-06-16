"""Unit tests for Google Drive service authentication helpers."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from google.auth.exceptions import RefreshError


google_drive_service_module = importlib.import_module(
    "shared.infrastructure.service.google_drive_service"
)


def test_oauth_invalid_grant_removes_token_and_reauthorizes(
    monkeypatch, tmp_path: Path
):
    credentials_path = tmp_path / "client_secret.json"
    token_path = tmp_path / "client_secret.token.json"
    scopes = google_drive_service_module.DEFAULT_GOOGLE_DRIVE_SCOPES

    credentials_path.write_text(json.dumps({"installed": {}}), encoding="utf-8")
    token_path.write_text(json.dumps({"scopes": scopes}), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(token_path))
    monkeypatch.setenv("GOOGLE_ALLOW_INTERACTIVE_AUTH", "1")

    calls: dict[str, object] = {}

    class ExpiredCredentials:
        expired = True
        refresh_token = "refresh-token"
        valid = False

        def refresh(self, request):
            raise RefreshError(
                "invalid_grant: Token has been expired or revoked."
            )

    class NewCredentials:
        valid = True

        def to_json(self) -> str:
            return json.dumps({"token": "new-token", "scopes": scopes})

    class FakeFlow:
        def run_local_server(self, **kwargs):
            calls["run_local_server_kwargs"] = kwargs
            calls["port"] = kwargs["port"]
            return NewCredentials()

    def fake_from_authorized_user_file(path: str, requested_scopes: list[str]):
        calls["authorized_user_file"] = path
        calls["authorized_user_scopes"] = requested_scopes
        return ExpiredCredentials()

    def fake_from_client_secrets_file(path: str, requested_scopes: list[str]):
        calls["client_secrets_file"] = path
        calls["client_secret_scopes"] = requested_scopes
        return FakeFlow()

    monkeypatch.setattr(
        google_drive_service_module.OAuthCredentials,
        "from_authorized_user_file",
        fake_from_authorized_user_file,
    )
    monkeypatch.setattr(
        google_drive_service_module.InstalledAppFlow,
        "from_client_secrets_file",
        fake_from_client_secrets_file,
    )

    service = object.__new__(google_drive_service_module.GoogleDriveService)
    creds = service._load_oauth_credentials(credentials_path)

    assert isinstance(creds, NewCredentials)
    assert calls["authorized_user_file"] == str(token_path)
    assert calls["authorized_user_scopes"] == scopes
    assert calls["client_secrets_file"] == str(credentials_path)
    assert calls["client_secret_scopes"] == scopes
    assert calls["port"] == 0
    assert calls["run_local_server_kwargs"]["access_type"] == "offline"
    assert calls["run_local_server_kwargs"]["prompt"] == "consent"
    assert json.loads(token_path.read_text(encoding="utf-8"))["token"] == "new-token"


def test_oauth_invalid_grant_fails_fast_without_interactive_auth(
    monkeypatch, tmp_path: Path
):
    credentials_path = tmp_path / "client_secret.json"
    token_path = tmp_path / "client_secret.token.json"
    scopes = google_drive_service_module.DEFAULT_GOOGLE_DRIVE_SCOPES

    credentials_path.write_text(json.dumps({"installed": {}}), encoding="utf-8")
    token_path.write_text(json.dumps({"scopes": scopes}), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(token_path))
    monkeypatch.delenv("GOOGLE_ALLOW_INTERACTIVE_AUTH", raising=False)

    class ExpiredCredentials:
        expired = True
        refresh_token = "refresh-token"
        valid = False

        def refresh(self, request):
            raise RefreshError(
                "invalid_grant: Token has been expired or revoked."
            )

    monkeypatch.setattr(
        google_drive_service_module.OAuthCredentials,
        "from_authorized_user_file",
        lambda path, requested_scopes: ExpiredCredentials(),
    )

    service = object.__new__(google_drive_service_module.GoogleDriveService)

    with pytest.raises(RuntimeError, match="scripts/google_drive_auth.py"):
        service._load_oauth_credentials(credentials_path)

    assert not token_path.exists()
