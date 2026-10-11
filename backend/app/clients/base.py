from __future__ import annotations

import re
import time
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class ServiceError(Exception):
    """En tjeneste svarte ikke eller svarte med feil. Skal aldri krasje appen."""


def get_json(url: str, *, params: dict | None = None, headers: dict | None = None,
             retries: int = 2, verify: bool = True) -> Any:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=TIMEOUT, verify=verify, follow_redirects=True) as c:
                r = c.get(url, params=params, headers=headers)
            if r.status_code in (401, 403):
                raise ServiceError(f"Autentisering avvist ({r.status_code}) av {_host(url)} – sjekk API-nøkkel/token")
            if r.status_code == 404:
                raise ServiceError(f"Fant ikke endepunktet {_path(url)} ({r.status_code})")
            r.raise_for_status()
            return r.json()
        except ServiceError:
            raise
        except (httpx.HTTPError, ValueError) as e:  # nettverk, timeout, ugyldig JSON
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise ServiceError(f"Ingen kontakt med {_host(url)}: {type(last).__name__}: {last}")


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
    """ISO-8601 eller epoch -> epoch sekunder."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    from datetime import datetime
    try:
        v = str(value).replace("Z", "+00:00")
        # Radarr/Sonarr kan gi 7 desimaler; Python tåler maks 6
        v = re.sub(r"\.(\d{6})\d+", r".\1", v)
        dt = datetime.fromisoformat(v)
        if dt.year < 1971:
            return None
        return int(dt.timestamp())
    except Exception:
        return None
