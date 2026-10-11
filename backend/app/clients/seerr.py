"""Seerr/Overseerr (optional): who requested what, and when."""
from __future__ import annotations

from ..i18n import L
from .base import ServiceError, get_json, ts


def _cfg(cfg: dict):
    if not cfg.get("url") or not cfg.get("api_key"):
        raise ServiceError(L("URL or API key is missing", "URL eller API-nøkkel mangler"))
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}


def status(cfg: dict) -> dict:
    base, h = _cfg(cfg)
    st = get_json(f"{base}/api/v1/status", headers=h, retries=0)
    return {"version": st.get("version"), "app": "Seerr"}


def fetch_requests(cfg: dict) -> list[tuple]:
    base, h = _cfg(cfg)
    out, skip = [], 0
    while True:
        data = get_json(f"{base}/api/v1/request", params={"take": 100, "skip": skip, "filter": "all"}, headers=h)
        results = data.get("results", []) or []
        for r in results:
            media = r.get("media") or {}
            who = r.get("requestedBy") or {}
            out.append((r["id"], r.get("type") or media.get("mediaType"), media.get("tmdbId"), media.get("tvdbId"),
                        who.get("displayName") or who.get("plexUsername") or who.get("username"),
                        ts(r.get("createdAt")), r.get("status"), who.get("plexUsername"),
                        str(media["ratingKey"]) if media.get("ratingKey") else None))
        skip += len(results)
        total = (data.get("pageInfo") or {}).get("results", 0)
        if not results or skip >= total:
            return out
