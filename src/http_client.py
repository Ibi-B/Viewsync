"""Small HTTP client with bounded retries."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class FetchError(RuntimeError):
    """Raised when a source request cannot be completed."""


def fetch_json(
    url: str,
    *,
    timeout_seconds: float = 20,
    retries: int = 2,
    headers: dict[str, str] | None = None,
) -> Any:
    """Fetch and decode JSON, retrying transient failures."""

    request_headers = {
        "Accept": "application/json",
        "User-Agent": "Viewsync/0.1 (+https://github.com/Ibi-B/Viewsync)",
    }
    if headers:
        request_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if response.status != 200:
                    raise FetchError(f"HTTP {response.status} for {url}")
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, FetchError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(2 ** attempt)

    raise FetchError(f"Failed to fetch {url}: {last_error}")
