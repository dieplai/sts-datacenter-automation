"""Data extraction — UI click + CDP capture + optional httpx API path."""
from .detail_capture import DetailCapture
from .http_fetcher import ProHttpClient
from .async_fetcher import fetch_many, fetch_many_async

__all__ = [
    "DetailCapture",
    "ProHttpClient",
    "fetch_many",
    "fetch_many_async",
]
