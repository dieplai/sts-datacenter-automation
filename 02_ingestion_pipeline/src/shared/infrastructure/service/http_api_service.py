"""HTTP API service for making requests."""

from typing import Any, Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class HTTPAPIService:
    """
    HTTP API client with retry logic and session management.
    Used for downloading files from HTTP/HTTPS endpoints.
    """

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ):
        from shared.utils.logging import log_success
        self.timeout = timeout
        self.session = self._create_session(max_retries, backoff_factor)
        log_success("Initialized HTTP API service")

    def _create_session(self, max_retries: int, backoff_factor: float) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def download_file(
        self, url: str, dest_path: str, headers: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Download a file from a URL.

        Args:
            url: The URL to download from
            dest_path: Local destination path
            headers: Optional HTTP headers

        Returns:
            Local file path
        """
        try:
            import os

            response = self.session.get(url, timeout=self.timeout, headers=headers)
            response.raise_for_status()

            os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(response.content)

            return dest_path
        except Exception as e:
            raise RuntimeError(f"Failed to download file from {url}: {e}")

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Make a GET request and return JSON response.

        Args:
            url: The URL to request
            params: Query parameters
            headers: Optional HTTP headers

        Returns:
            Parsed JSON response
        """
        try:
            response = self.session.get(
                url, params=params, timeout=self.timeout, headers=headers
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise RuntimeError(f"Failed to GET {url}: {e}")

    def post(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Make a POST request and return JSON response.

        Args:
            url: The URL to request
            data: Form data
            json: JSON body
            headers: Optional HTTP headers

        Returns:
            Parsed JSON response
        """
        try:
            response = self.session.post(
                url, data=data, json=json, timeout=self.timeout, headers=headers
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise RuntimeError(f"Failed to POST {url}: {e}")

    def close(self) -> None:
        """Close the session."""
        from shared.utils.logging import log_success
        self.session.close()
        log_success("Closed HTTP API service")

    def __enter__(self) -> "HTTPAPIService":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# Convenient global reference
http_api_service = HTTPAPIService()
