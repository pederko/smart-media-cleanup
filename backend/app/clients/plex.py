"""Plex Media Server. Kun lesing. JSON via Accept-header, paginering med X-Plex-Container-*."""
from __future__ import annotations

import json
from typing import Callable

from .base import ServiceError, get_json

PAGE = 500


def _cfg(cfg: dict) -> tuple[str, dict]:
    if not cfg.get("url") or not cfg.get("token"):
        raise ServiceError("URL eller token mangler")
    return cfg["url"].rstrip("/"), {"X-Plex-Token": cfg["token"], "Accept": "application/json"}


def status(cfg: dict) -> dict:
    base, h = _cfg(cfg)
    mc = get_json(f"{base}/identity", headers=h, retries=0).get("MediaContainer", {})
    return {"version": mc.get("version"), "app": "Plex Media Server"}


def _paged(base: str, h: dict, path: str, params: dict) -> list[dict]:
    out, start = [], 0
    while True:
        p = dict(params, **{"X-Plex-Container-Start": start, "X-Plex-Container-Size": PAGE})
        mc = get_json(f"{base}{path}", params=p, headers=h).get("MediaContainer", {})
        items = mc.get("Metadata", []) or []
        out.extend(items)
        total = mc.get("totalSize", mc.get("size", 0))
        start += len(items)
        if not items or start >= total:
            return out


def _parts(item: dict, map_path: Callable) -> list[tuple]:
    rows = []
    for media in item.get("Media", []) or []:
        for part in media.get("Part", []) or []:
            if part.get("file"):
                rows.append((map_path(part["file"]), str(item["ratingKey"]), str(media.get("id")),
                             part.get("size"), media.get("videoResolution"), media.get("videoCodec"),
                             media.get("bitrate")))
    return rows


def _labelled_keys(base: str, h: dict, section: str, type_: int, wanted: set[str]) -> dict[str, list[str]]:
    """ratingKey -> beskyttelsesetiketter. Bruker filter-endepunktet, som er stabilt på tvers av versjoner."""
    if not wanted:
        return {}
    try:
        dirs = get_json(f"{base}/library/sections/{section}/label", headers=h).get("MediaContainer", {}).get("Directory", [])
    except ServiceError:
        return {}
    out: dict[str, list[str]] = {}
    for d in dirs or []:
        if str(d.get("title", "")).lower() in wanted:
            for it in _paged(base, h, f"/library/sections/{section}/all", {"type": type_, "label": d["key"]}):
                out.setdefault(str(it["ratingKey"]), []).append(d["title"])
    return out


def fetch(cfg: dict, map_path: Callable, protect_labels: list[str],
          progress: Callable[[float, str], None] | None = None) -> tuple[list[tuple], list[tuple], list[dict]]:
    base, h = _cfg(cfg)
    wanted = {x.lower() for x in protect_labels}
    sections = get_json(f"{base}/library/sections", headers=h).get("MediaContainer", {}).get("Directory", [])
    items, parts, libs = [], [], []
    for i, sec in enumerate(sections):
        key, stype, title = str(sec["key"]), sec.get("type"), sec.get("title")
        libs.append({"key": key, "title": title, "type": stype,
                     "locations": [map_path(l.get("path")) for l in sec.get("Location", [])]})
        if progress:
            progress(i / max(1, len(sections)), f"Plex: {title}")
        if stype == "movie":
            labels = _labelled_keys(base, h, key, 1, wanted)
            for m in _paged(base, h, f"/library/sections/{key}/all", {"type": 1}):
                rk = str(m["ratingKey"])
                items.append((rk, "movie", m.get("title"), m.get("year"), None, None, None,
                              m.get("addedAt"), title, json.dumps(labels.get(rk, []))))
                parts.extend(_parts(m, map_path))
        elif stype == "show":
            labels = _labelled_keys(base, h, key, 2, wanted)
            for s in _paged(base, h, f"/library/sections/{key}/all", {"type": 2}):
                rk = str(s["ratingKey"])
                items.append((rk, "show", s.get("title"), s.get("year"), None, None, None,
                              s.get("addedAt"), title, json.dumps(labels.get(rk, []))))
            for e in _paged(base, h, f"/library/sections/{key}/all", {"type": 4}):
                items.append((str(e["ratingKey"]), "episode", e.get("title"), e.get("year"),
                              str(e.get("grandparentRatingKey")), e.get("parentIndex"), e.get("index"),
                              e.get("addedAt"), title, "[]"))
                parts.extend(_parts(e, map_path))
    return items, parts, libs
