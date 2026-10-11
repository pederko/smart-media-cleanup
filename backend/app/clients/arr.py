"""Radarr og Sonarr. Kun GET-kall. Begge bruker /api/v3 (også Sonarr v4)."""
from __future__ import annotations

import json
from typing import Callable

from .base import ServiceError, get_json, ts


def _cfg(cfg: dict) -> tuple[str, dict]:
    if not cfg.get("url") or not cfg.get("api_key"):
        raise ServiceError("URL eller API-nøkkel mangler")
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}


def status(cfg: dict) -> dict:
    base, h = _cfg(cfg)
    st = get_json(f"{base}/api/v3/system/status", headers=h, retries=0)
    return {"version": st.get("version"), "app": st.get("appName")}


def _tag_names(base: str, h: dict) -> dict[int, str]:
    return {t["id"]: t.get("label", "") for t in get_json(f"{base}/api/v3/tag", headers=h)}


def _quality(f: dict) -> tuple[str | None, str | None, str | None]:
    q = (f.get("quality") or {}).get("quality") or {}
    mi = f.get("mediaInfo") or {}
    res = q.get("resolution")
    resolution = f"{res}p" if res else mi.get("resolution")
    return q.get("name"), resolution, mi.get("videoCodec")


def fetch_radarr(cfg: dict, map_path: Callable[[str | None], str | None]) -> list[tuple]:
    base, h = _cfg(cfg)
    tags = _tag_names(base, h)
    out = []
    for m in get_json(f"{base}/api/v3/movie", headers=h):
        mf = m.get("movieFile") or {}
        qname, res, codec = _quality(mf) if mf else (None, None, None)
        out.append((
            m["id"], m.get("title"), m.get("year"), m.get("tmdbId"), map_path(m.get("path")),
            1 if m.get("monitored") else 0, ts(m.get("added")),
            json.dumps([tags.get(t, str(t)) for t in m.get("tags", [])]),
            1 if m.get("hasFile") else 0, map_path(mf.get("path")), mf.get("size"),
            qname, res, codec, ts(mf.get("dateAdded")),
        ))
    return out


def fetch_sonarr(cfg: dict, map_path: Callable[[str | None], str | None],
                 progress: Callable[[float, str], None] | None = None) -> tuple[list[tuple], list[tuple]]:
    base, h = _cfg(cfg)
    tags = _tag_names(base, h)
    series_rows, file_rows = [], []
    series = get_json(f"{base}/api/v3/series", headers=h)
    for i, s in enumerate(series):
        seasons = {str(x["seasonNumber"]): bool(x.get("monitored")) for x in s.get("seasons", [])}
        series_rows.append((
            s["id"], s.get("title"), s.get("year"), s.get("tvdbId"), map_path(s.get("path")),
            1 if s.get("monitored") else 0, ts(s.get("added")),
            json.dumps([tags.get(t, str(t)) for t in s.get("tags", [])]),
            json.dumps(seasons), s.get("status"),
        ))
        for f in get_json(f"{base}/api/v3/episodefile", params={"seriesId": s["id"]}, headers=h):
            qname, res, codec = _quality(f)
            file_rows.append((f["id"], s["id"], f.get("seasonNumber"), map_path(f.get("path")),
                              f.get("size"), qname, res, codec, ts(f.get("dateAdded"))))
        if progress and i % 10 == 0:
            progress(i / max(1, len(series)), f"Sonarr: {i}/{len(series)} serier")
    return series_rows, file_rows
