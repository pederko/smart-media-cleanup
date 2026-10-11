"""Find smaller versions through the interactive search of Radarr/Sonarr against the indexers (read only).

Radarr:  GET /api/v3/release?movieId=…
Sonarr:  GET /api/v3/release?seriesId=…&seasonNumber=… (season packs)
Results are filtered (must be noticeably smaller than what is on disk), ranked with an explainable
score and cached for 30 minutes to spare the indexers.
"""
from __future__ import annotations

import json
import re
import time

from . import db, settings
from .actions import _arr, _req
from .i18n import L, ActionError, fmt

NO_SEEDERS = L("No seeders", "Ingen delere")

GB = 1024 ** 3
CACHE_SECONDS = 30 * 60
# Rejections that only mean «this is not an upgrade» – expected when looking for smaller files
EXPECTED_REJECTION = re.compile(r"upgrade|preference|cutoff|already meets|existing file|not wanted in .*profile", re.I)
PROFILE_REJECTION = re.compile(r"not wanted in .*profile", re.I)


def _current(c, t: dict, season: int | None) -> tuple[int, int]:
    """(current size of the video files, number of episodes) for the title/season."""
    sql = """SELECT f.alloc, f.size, ft.season, ft.episode FROM file_title ft JOIN files f ON f.path=ft.path
             WHERE ft.title_key=? AND f.is_video=1 AND f.is_extra=0"""
    rows = db.rows(c, sql, (t["key"],))
    if season is not None:
        rows = [r for r in rows if r["season"] == season]
    if t["kind"] == "movie" and rows:
        return max(r["alloc"] or r["size"] for r in rows), 1
    return sum(r["alloc"] or r["size"] for r in rows), len({r["episode"] for r in rows if r["episode"] is not None}) or len(rows)


def _score(r: dict, current: int, target: int) -> tuple[float, list, list]:
    reasons, warnings = [], []
    size = r["size"]
    ratio = 1 - size / current
    pts = 40 * ratio
    reasons.append(fmt("{p:.0f} % smaller than today", "{p:.0f} % mindre enn i dag", p=ratio * 100))
    res = r["resolution"] or 0
    if res == 1080:
        pts += 20
        reasons.append("1080p")
    elif res >= 2160:
        pts += 15
        reasons.append(L("Keeps 4K", "Beholder 4K"))
    elif res == 720:
        pts += 5
        warnings.append(L("Only 720p", "Bare 720p"))
    elif res:
        warnings.append(fmt("Low resolution ({r}p)", "Lav oppløsning ({r}p)", r=res))
    if target and 0.5 * target <= size <= 1.6 * target:
        pts += 10
        reasons.append(L("Close to the target size", "Nær målstørrelsen"))
    if r["protocol"] == "torrent":
        s = r["seeders"] or 0
        if s >= 20:
            pts += 15
            reasons.append(fmt("{s} seeders", "{s} delere", s=s))
        elif s >= 5:
            pts += 10
            reasons.append(fmt("{s} seeders", "{s} delere", s=s))
        elif s >= 1:
            pts += 3
            warnings.append(fmt("Only {s} seeder(s)", "Bare {s} deler(e)", s=s))
        else:
            pts -= 30
            warnings.append(NO_SEEDERS)
    elif r["protocol"] == "usenet":
        pts += 10
        reasons.append("Usenet")
    cf = r["custom_format_score"] or 0
    if cf > 0:
        pts += 5
        reasons.append(fmt("Custom format +{cf}", "Egendefinert format +{cf}", cf=cf))
    elif cf < 0:
        pts -= 10
        warnings.append(fmt("Custom format {cf}", "Egendefinert format {cf}", cf=cf))
    for rej in r["rejections"]:
        if PROFILE_REJECTION.search(rej):
            pts -= 5
            warnings.append(L("The quality is not in the quality profile – the profile must be changed",
                              "Kvaliteten er ikke med i kvalitetsprofilen – profilen må endres"))
        elif not EXPECTED_REJECTION.search(rej):
            pts -= 15
            warnings.append(rej)
    if (r["age_days"] or 0) > 3000:
        pts -= 5
        warnings.append(L("Very old release", "Svært gammel utgivelse"))
    uniq = []
    for w in warnings:
        if w not in uniq:
            uniq.append(w)
    return round(max(0.0, min(100.0, pts)), 1), reasons, uniq


def _parse(raw: dict) -> dict:
    q = (raw.get("quality") or {}).get("quality") or {}
    rej = [x if isinstance(x, str) else (x.get("reason") or str(x)) for x in raw.get("rejections") or []]
    return {
        "title": raw.get("title"), "size": raw.get("size") or 0, "quality": q.get("name"), "resolution": q.get("resolution"),
        "indexer": raw.get("indexer"), "protocol": raw.get("protocol"), "seeders": raw.get("seeders"),
        "leechers": raw.get("leechers"), "age_days": raw.get("age"), "languages": [l.get("name") for l in raw.get("languages") or []],
        "rejected": bool(raw.get("rejected")), "rejections": rej, "custom_format_score": raw.get("customFormatScore"),
        "full_season": raw.get("fullSeason"), "guid": raw.get("guid"), "indexer_id": raw.get("indexerId"),
        "info_url": raw.get("infoUrl"),
    }


def search(key: str, season: int | None = None, refresh: bool = False) -> dict:
    with db.conn() as c:
        rows = db.rows(c, "SELECT * FROM titles WHERE key=?", (key,))
        if not rows:
            raise ActionError(L("Title not found", "Fant ikke tittelen"))
        t = rows[0]
        cache_key = f"releases:{key}:{season}"
        cached = db.kv_get(c, cache_key)
        current, episodes = _current(c, t, season)
    if cached and not refresh and time.time() - cached.get("searched", 0) < CACHE_SECONDS:
        return {**cached, "cached": True}
    a = settings.get()["analysis"]
    if t["radarr_id"] is not None:
        base, h = _arr("radarr")
        raw = _req("GET", f"{base}/api/v3/release", h, params={"movieId": t["radarr_id"]}).json()
        service, target = "radarr", int(a["target_movie_gb"] * GB)
    elif t["sonarr_id"] is not None:
        if season is None:
            raise ActionError(L("Choose a season to search for", "Velg en sesong å søke etter"))
        base, h = _arr("sonarr")
        raw = _req("GET", f"{base}/api/v3/release", h, params={"seriesId": t["sonarr_id"], "seasonNumber": season}).json()
        service, target = "sonarr", int(a["target_episode_gb"] * GB * max(1, episodes))
    else:
        raise ActionError(L("The title is not managed by Radarr/Sonarr, so the indexers cannot be searched from here",
                            "Tittelen administreres ikke av Radarr/Sonarr, så indekserne kan ikke søkes herfra"))

    releases = [_parse(r) for r in raw]
    if service == "sonarr":
        episode_only = sum(1 for r in releases if not r["full_season"])
        releases = [r for r in releases if r["full_season"]]
    else:
        episode_only = 0
    total = len(releases)
    smaller = [r for r in releases if 0 < r["size"] < current * 0.85] if current else []
    for r in smaller:
        r["score"], r["reasons"], r["warnings"] = _score(r, current, target)
        r["savings"] = current - r["size"]
    smaller.sort(key=lambda r: (-r["score"], r["size"]))
    rec = 0
    for r in smaller:
        r["recommended"] = rec < 3 and r["score"] >= 45 and NO_SEEDERS not in r["warnings"]
        rec += r["recommended"]
    result = {"key": key, "title": t["name"], "year": t["year"], "service": service, "season": season,
              "current_size": current, "episodes": episodes, "target": target, "total": total,
              "episode_releases": episode_only, "smaller": len(smaller), "releases": smaller[:60],
              "searched": time.time()}
    with db.conn() as c:
        db.kv_set(c, cache_key, result)
    return {**result, "cached": False}


__all__ = ["search", "json"]
