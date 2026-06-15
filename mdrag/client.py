"""MediaWiki API client: one polite, resilient session per wiki host.

Handles the things that break naive scrapers:
  - descriptive User-Agent with a contact (MediaWiki policy)
  - maxlag for Wikimedia hosts (back off when their DB is busy)
  - retry with exponential backoff on 429 / 503 / transient network errors
  - a minimum delay between requests to the same host
"""

from __future__ import annotations

import time
import logging
from typing import Any, Dict, Optional

import requests

from . import __version__

log = logging.getLogger("mdrag.client")


class MediaWikiClient:
    def __init__(
        self,
        api_url: str,
        contact: str,
        *,
        use_maxlag: bool = False,
        maxlag: int = 5,
        request_delay_seconds: float = 1.0,
        max_retries: int = 5,
        backoff_base_seconds: float = 2.0,
        timeout_seconds: int = 30,
    ) -> None:
        self.api_url = api_url
        self.use_maxlag = use_maxlag
        self.maxlag = maxlag
        self.request_delay = request_delay_seconds
        self.max_retries = max_retries
        self.backoff_base = backoff_base_seconds
        self.timeout = timeout_seconds

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    f"MarvelDCRAG/{__version__} "
                    f"(personal research project; {contact})"
                )
            }
        )
        self._last_request_ts = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_ts
        wait = self.request_delay - elapsed
        if wait > 0:
            time.sleep(wait)

    def get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """GET against the API with retries. Returns parsed JSON dict."""
        params = dict(params)
        params.setdefault("format", "json")
        params.setdefault("formatversion", "2")
        if self.use_maxlag:
            params["maxlag"] = self.maxlag

        attempt = 0
        while True:
            attempt += 1
            self._throttle()
            try:
                resp = self.session.get(
                    self.api_url, params=params, timeout=self.timeout
                )
                self._last_request_ts = time.time()

                # Honor explicit rate-limit / overload signals.
                if resp.status_code in (429, 503):
                    raise _Retryable(f"HTTP {resp.status_code}")

                resp.raise_for_status()
                data = resp.json()

                # maxlag rejections come back 200 with an error body.
                if isinstance(data, dict) and data.get("error", {}).get("code") == "maxlag":
                    raise _Retryable("maxlag")

                return data

            except (_Retryable, requests.RequestException) as exc:
                if attempt > self.max_retries:
                    log.error("giving up after %d attempts: %s", attempt, exc)
                    raise
                sleep_for = self.backoff_base ** attempt
                log.warning(
                    "request failed (%s); retry %d/%d in %.1fs",
                    exc, attempt, self.max_retries, sleep_for,
                )
                time.sleep(sleep_for)


class _Retryable(Exception):
    """Internal marker for conditions worth retrying."""
