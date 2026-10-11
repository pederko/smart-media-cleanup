from __future__ import annotations

import re
import time
from typing import Any

import httpx

from ..i18n import L, AppError, fmt

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class ServiceError(AppError):
    """A service did not answer or answered with an error. Must never crash the app."""
    status = 502


def get_json(url: str, *, params: dict | None = None, headers: dict | None = None,
             retries: int = 2, verify: bool = True) -> Any:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=TIMEOUT, verify=verify, follow_redirects=True) as c:
                r = c.get(url, params=params, headers=headers)
            if r.status_code in (401, 403):
                raise ServiceError(fmt("Authentication refused ({c}) by {h} – check the API key/token",
                                       "Autentisering avvist ({c}) av {h} – sjekk API-nøkkel/token", c=r.status_code, h=_host(url)))
            if r.status_code == 404:
                raise ServiceError(fmt("Endpoint not found: {p} ({c})", "Fant ikke endepunktet {p} ({c})", p=_path(url), c=r.status_code))
            r.raise_for_status()
            return r.json()
        except ServiceError:
            raise
        except (httpx.HTTPError, ValueError) as e:  # network, timeout, invalid JSON
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise ServiceError(fmt("No connection to {h}: {e}", "Ingen kontakt med {h}: {e}", h=_host(url), e=f"{type(last).__name__}: {last}"))


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or url
    except Exception:
        return url


def _path(url: str) -> str:
    try:
        return httpx.URL(url).path
    except Exception:
        return url


def ts(value: Any) -> int | None:
    """ISO-8601 or epoch -> epoch seconds."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    from datetime import datetime
    try:
        v = str(value).replace("Z", "+00:00")
        # Radarr/Sonarr may give 7 decimals; Python accepts at most 6
        v = re.sub(r"\.(\d{6})\d+", r".\1", v)
        dt = datetime.fromisoformat(v)
        if dt.year < 1971:
            return None
        return int(dt.timestamp())
    except Exception:
        return None
