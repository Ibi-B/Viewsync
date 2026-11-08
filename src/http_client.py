"""Small HTTP client with bounded retries and useful failure diagnostics."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class FetchError(RuntimeError):
    """Raised when a source request cannot be completed."""


def response_excerpt(response: Any) -> str:
    try:
        body = response.read(500).decode("utf-8", errors="replace")
    except Exception:
        return ""
    return body[:500]


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
                    raise FetchError(
                        f"HTTP {response.status} for {url}; response={response_excerpt(response)!r}"
                    )

                raw = response.read()
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise FetchError(
                        f"Invalid JSON from {url}: {error}; response={raw[:500]!r}"
                    ) from error

        except urllib.error.HTTPError as error:
            detail = response_excerpt(error)
            last_error = FetchError(
                f"HTTP {error.code} for {url}; response={detail!r}"
            )
        except (urllib.error.URLError, TimeoutError, FetchError) as error:
            last_error = error

        if attempt < retries:
            time.sleep(2 ** attempt)

    raise FetchError(f"Failed to fetch {url}: {last_error}")
