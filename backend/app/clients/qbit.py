"""qBittorrent Web API (optional). Used to see which torrents still seed, set seeding limits and
remove torrents whose content is already imported. Writes only happen from arrsetup after an
explicit confirmation."""
from __future__ import annotations

import httpx

from ..i18n import L, fmt
from .base import TIMEOUT, ServiceError

# What qBittorrent does when a torrent reaches its seeding limit (app/preferences max_ratio_act)
STOP, REMOVE, SUPER_SEED, REMOVE_WITH_FILES = 0, 1, 2, 3


class Client:
    def __init__(self, cfg: dict):
        if not cfg.get("url"):
            raise ServiceError(L("URL is missing", "URL mangler"))
        self.base = cfg["url"].rstrip("/")
        self.http = httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"Referer": self.base})
        try:
            r = self.http.post(f"{self.base}/api/v2/auth/login",
                               data={"username": cfg.get("username") or "", "password": cfg.get("password") or ""})
        except httpx.HTTPError as e:
            self.http.close()
            raise ServiceError(fmt("No connection to qBittorrent: {e}", "Ingen kontakt med qBittorrent: {e}",
                                   e=f"{type(e).__name__}: {e}")) from e
        if r.status_code == 403 or (r.status_code == 200 and r.text.strip() == "Fails."):
            self.http.close()
            raise ServiceError(L("qBittorrent refused the username or password (or the IP is banned after failed attempts)",
                                 "qBittorrent avviste brukernavn eller passord (eller IP-en er utestengt etter mislykkede forsøk)"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.http.close()

    def _call(self, method: str, path: str, **kw):
        try:
            r = self.http.request(method, f"{self.base}/api/v2/{path}", **kw)
        except httpx.HTTPError as e:
            raise ServiceError(fmt("No connection to qBittorrent: {e}", "Ingen kontakt med qBittorrent: {e}",
                                   e=f"{type(e).__name__}: {e}")) from e
        if r.status_code >= 400:
            raise ServiceError(fmt("qBittorrent answered {c} on {p}: {b}", "qBittorrent svarte {c} på {p}: {b}",
                                   c=r.status_code, p=path, b=r.text[:200]), code=r.status_code)
        return r

    def version(self) -> str:
        return self._call("GET", "app/version").text.strip()

    def preferences(self) -> dict:
        return self._call("GET", "app/preferences").json()

    def set_preferences(self, prefs: dict) -> None:
        import json
        self._call("POST", "app/setPreferences", data={"json": json.dumps(prefs)})

    def torrents(self) -> list[dict]:
        return self._call("GET", "torrents/info").json()

    def set_share_limits(self, hashes: list[str], ratio: float, seeding_minutes: int, inactive_minutes: int = -2) -> None:
        # -2 = use the global limit, -1 = no limit. qBittorrent 4.6+/5 also takes inactiveSeedingTimeLimit.
        self._call("POST", "torrents/setShareLimits", data={
            "hashes": "|".join(hashes), "ratioLimit": ratio, "seedingTimeLimit": seeding_minutes,
            "inactiveSeedingTimeLimit": inactive_minutes})

    def stop(self, hashes: list[str]) -> None:
        """«Stop» in qBittorrent 5, «Pause» in 4.x."""
        try:
            self._call("POST", "torrents/stop", data={"hashes": "|".join(hashes)})
        except ServiceError as e:
            if getattr(e, "code", None) != 404:
                raise
            self._call("POST", "torrents/pause", data={"hashes": "|".join(hashes)})

    def delete(self, hashes: list[str], delete_files: bool) -> None:
        self._call("POST", "torrents/delete", data={"hashes": "|".join(hashes),
                                                    "deleteFiles": "true" if delete_files else "false"})


def status(cfg: dict) -> dict:
    with Client(cfg) as c:
        return {"version": c.version(), "app": "qBittorrent"}
