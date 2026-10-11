"""Quality: an overview of large movies and seasons that can be swapped for smaller versions,
with search and swap for many titles at once.

Candidates: movies in Radarr whose largest video file is over the limit, and seasons in Sonarr whose
episodes are over the limit on average. Search results are reused from the cache of releases.search.
The swap itself is done by swaps.start – one at a time, with the same safeguards.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

from . import db, settings, swaps
from .i18n import L, ActionError, AppError

GB = 1024 ** 3


def _best(cached: dict | None) -> dict | None:
    if not cached:
        return None
    rel = next((r for r in cached.get("releases", []) if r.get("recommended")), None)
    out = {"searched": cached.get("searched"), "smaller": cached.get("smaller", 0), "total": cached.get("total", 0)}
    if rel:
        out["release"] = {k: rel.get(k) for k in ("title", "size", "savings", "quality", "resolution", "guid", "indexer_id",
                                                  "seeders", "protocol", "indexer", "score")}
    return out


def candidates(kind: str = "", min_movie_gb: float | None = None, min_episode_gb: float | None = None,
               q: str = "", unwatched: bool = False, sort: str = "savings") -> dict:
    a = settings.get()["analysis"]
    mm = (min_movie_gb if min_movie_gb is not None else a["large_movie_gb"]) * GB
    me = (min_episode_gb if min_episode_gb is not None else a["large_episode_gb"]) * GB
    tm, te = a["target_movie_gb"] * GB, a["target_episode_gb"] * GB
    with db.conn() as c:
        titles = {t["key"]: t for t in db.rows(c, """SELECT key, kind, name, year, library, radarr_id, sonarr_id, protected,
                    protect_reason, best_resolution, play_count, last_played, users_count, monitored, requests
                    FROM titles WHERE (radarr_id IS NOT NULL OR sonarr_id IS NOT NULL)""")}
        files = db.rows(c, """SELECT ft.title_key, ft.season, f.alloc, f.size FROM file_title ft JOIN files f ON f.path=ft.path
                              WHERE f.is_video=1 AND f.is_extra=0""")
        swaps_active = defaultdict(list)
        for s in db.rows(c, "SELECT id, title_key, season, state, message, progress FROM swaps ORDER BY id DESC"):
            swaps_active[(s["title_key"], s["season"])].append(s)
        cache = {r[0]: r[1] for r in c.execute("SELECT key, value FROM kv WHERE key LIKE 'releases:%'")}
    groups: dict[tuple, list] = defaultdict(list)
    for f in files:
        t = titles.get(f["title_key"])
        if not t:
            continue
        season = f["season"] if t["sonarr_id"] is not None else None
        if t["sonarr_id"] is not None and season is None:
            continue
        groups[(t["key"], season)].append(f)
    items = []
    for (key, season), fs in groups.items():
        t = titles[key]
        size = sum(f["alloc"] or f["size"] for f in fs)
        if t["radarr_id"] is not None:
            biggest = max(f["size"] for f in fs)
            if biggest < mm:
                continue
            est = max(0, size - tm)
        else:
            avg = size / len(fs)
            if avg < me:
                continue
            est = max(0, size - te * len(fs))
        if est <= 0:
            continue
        raw = cache.get(f"releases:{key}:{season}")
        try:
            cached = json.loads(raw) if raw else None
        except ValueError:
            cached = None
        sw = swaps_active.get((key, season), [])
        items.append({
            "id": f"{key}|{'' if season is None else season}", "key": key, "season": season, "kind": t["kind"],
            "name": t["name"], "year": t["year"], "library": t["library"], "resolution": t["best_resolution"],
            "files": len(fs), "size": size, "estimate": est, "play_count": t["play_count"], "last_played": t["last_played"],
            "users_count": t["users_count"], "monitored": t["monitored"], "protected": bool(t["protected"]),
            "protect_reason": t["protect_reason"], "requests": json.loads(t["requests"] or "[]"),
            "search": _best(cached), "swap": sw[0] if sw else None,
        })
    if kind in ("movie", "series"):
        items = [i for i in items if i["kind"] == kind]
    if q:
        items = [i for i in items if q.lower() in i["name"].lower()]
    if unwatched:
        items = [i for i in items if not i["play_count"]]
    def gain(i):
        r = (i["search"] or {}).get("release")
        return r["savings"] if r else i["estimate"]
    keyf = {"savings": gain, "size": lambda i: i["size"], "name": lambda i: i["name"].lower(),
            "watched": lambda i: i["last_played"] or 0}
    items.sort(key=keyf.get(sort, gain), reverse=sort not in ("name", "watched"))
    searched = [i for i in items if i["search"]]
    found = [i for i in searched if (i["search"] or {}).get("release")]
    summary = {"count": len(items), "size": sum(i["size"] for i in items), "estimate": sum(i["estimate"] for i in items),
               "searched": len(searched), "found": len(found),
               "found_savings": sum(i["search"]["release"]["savings"] for i in found),
               "protected": sum(i["protected"] for i in items),
               "active_swaps": sum(1 for i in items if i["swap"] and i["swap"]["state"] in swaps.ACTIVE)}
    return {"items": items, "summary": summary,
            "limits": {"movie_gb": mm / GB, "episode_gb": me / GB, "target_movie_gb": a["target_movie_gb"],
                       "target_episode_gb": a["target_episode_gb"]}}


def start_many(items: list[dict], after_swap: str = "none") -> dict:
    """Start several swaps. Each goes through swaps.start with all safeguards; an error does not stop the others."""
    if len(items) > 50:
        raise ActionError(L("At most 50 swaps at a time", "Maks 50 bytter om gangen"))
    results = []
    for it in items:
        try:
            sw = swaps.start(it["key"], it["guid"], int(it["indexer_id"]), it.get("season"), after_swap)
            results.append({"key": it["key"], "season": it.get("season"), "ok": True, "swap_id": sw["id"]})
        except AppError as e:
            if e.status == 403:
                raise
            results.append({"key": it["key"], "season": it.get("season"), "ok": False, "error": e.msg})
        except Exception as e:  # network etc.
            results.append({"key": it["key"], "season": it.get("season"), "ok": False, "error": str(e)})
        time.sleep(0.2)
    return {"results": results, "started": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results)}
