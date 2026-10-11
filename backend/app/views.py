"""Sammensatte visninger: bibliotek (filmer/serier) og Seerr-brukere.

Datamengden er noen tusen titler, så filtrering/sortering gjøres i Python over ferdige
analyseresultater – enkelt å lese og raskt nok.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict

from . import db, settings
from .analysis import engine

MONTH = 30.44 * 86400
ACTION_ORDER = ["delete_title", "delete_season", "replace", "remove_versions", "remove_copy"]


def _j(v, d):
    try:
        return json.loads(v) if v else d
    except Exception:
        return d


def _titles(c, kind: str | None = None, requester: str | None = None) -> list[dict]:
    where, params = ["1=1"], []
    if kind:
        where.append("kind=?")
        params.append(kind)
    if requester:
        where.append("EXISTS (SELECT 1 FROM json_each(requests) j WHERE json_extract(j.value,'$.by')=?)")
        params.append(requester)
    rows = db.rows(c, f"""SELECT key, kind, name, year, library, folder, radarr_id, sonarr_id, monitored, added,
                                 protected, protect_reason, alloc, file_count, video_count, play_count, last_played,
                                 users_count, recent_users_count, best_resolution, requested_by, requested_at, requests,
                                 seasons
                          FROM titles WHERE {' AND '.join(where)}""", params)
    for r in rows:
        r["requests"] = _j(r["requests"], [])
        r["seasons"] = _j(r["seasons"], {})
    return rows


def _suggestions_by_title(c, keys: list[str] | None = None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for s in db.rows(c, "SELECT id, kind, title_key, scope, action, label, score, risk, savings FROM suggestions "
                        "WHERE title_key IS NOT NULL ORDER BY score DESC"):
        if keys is None or s["title_key"] in keys:
            out[s["title_key"]].append(s)
    return out


def _attach(t: dict, sugg: list[dict], min_score: float) -> dict:
    visible = [s for s in sugg if s["score"] >= min_score]
    best = visible[0] if visible else None
    t["best"] = best
    t["suggestion_count"] = len(visible)
    t["delete_id"] = next((s["id"] for s in sugg if s["kind"] == "delete_title"), None)
    t["delete_savings"] = next((s["savings"] for s in sugg if s["kind"] == "delete_title"), 0)
    return t


def _months_since(ts):
    return None if not ts else (time.time() - ts) / MONTH


def _match(t: dict, view: str) -> bool:
    m = _months_since(t["last_played"])
    if view == "suggested":
        return t["best"] is not None
    if view == "never":
        return not t["play_count"]
    if view == "low_risk":
        return bool(t["best"]) and t["best"]["kind"] == "delete_title" and t["best"]["risk"] == "lav"
    if view.startswith("stale"):
        n = int(view[5:])
        return bool(t["play_count"]) and m is not None and m >= n
    if view == "protected":
        return bool(t["protected"])
    if view == "requested":
        return bool(t["requests"])
    if view == "4k":
        return t["best_resolution"] == "4K"
    if view == "watched_recently":
        return m is not None and m < 12
    return True


SORTS = {
    "size": lambda t: t["alloc"] or 0,
    "name": lambda t: (t["name"] or "").lower(),
    "last_played": lambda t: t["last_played"] or 0,
    "plays": lambda t: t["play_count"] or 0,
    "added": lambda t: t["added"] or 0,
    "score": lambda t: t["best"]["score"] if t["best"] else -1,
    "savings": lambda t: t["best"]["savings"] if t["best"] else -1,
}


def library(kind: str, view: str = "all", q: str = "", sort: str = "score", order: str = "desc",
            limit: int = 100, offset: int = 0) -> dict:
    s = settings.get()
    min_score = s["analysis"]["min_score"]
    stale = sorted(s["analysis"]["stale_months"])
    with db.conn() as c:
        titles = _titles(c, kind)
        by_title = _suggestions_by_title(c)
        for t in titles:
            _attach(t, by_title.get(t["key"], []), min_score)

        # ---------- oppsummering (uavhengig av filter)
        def agg(items):
            return {"count": len(items), "bytes": sum(t["alloc"] or 0 for t in items)}
        never = [t for t in titles if not t["play_count"]]
        stale_buckets = []
        for n in stale:
            items = [t for t in titles if t["play_count"] and (_months_since(t["last_played"]) or 0) >= n]
            stale_buckets.append({"months": n, **agg(items)})
        suggested = [t for t in titles if t["best"]]
        ids_by_kind: dict[str, list[str]] = defaultdict(list)
        all_ids = []
        for t in titles:
            for sg in by_title.get(t["key"], []):
                if sg["score"] >= min_score:
                    ids_by_kind[sg["kind"]].append(sg["id"])
                    all_ids.append(sg["id"])
        actions = []
        for k in ACTION_ORDER:
            if ids_by_kind.get(k):
                sv = engine.selection_savings(c, ids_by_kind[k])
                actions.append({"kind": k, "count": len(ids_by_kind[k]), "freed": sv["freed"]})
        total = engine.selection_savings(c, all_ids)["freed"] if all_ids else 0
        # Sikre slettinger: aldri sett / ikke sett på lenge, lav risiko
        low = [sg["id"] for t in titles for sg in by_title.get(t["key"], [])
               if sg["kind"] == "delete_title" and sg["risk"] == "lav" and sg["score"] >= min_score]
        low_freed = engine.selection_savings(c, low)["freed"] if low else 0
        top = sorted((t for t in suggested if (t["best"]["savings"] or 0) > 0), key=lambda t: -t["best"]["score"])[:6]
        summary = {
            "kind": kind, **agg(titles), "never": agg(never), "stale": stale_buckets,
            "protected": agg([t for t in titles if t["protected"]]),
            "suggested": agg(suggested), "freed": total, "actions": actions,
            "low_risk_delete": {"count": len(low), "freed": low_freed},
            "requested": agg([t for t in titles if t["requests"]]),
            "four_k": agg([t for t in titles if t["best_resolution"] == "4K"]),
            "top": [_slim(t) for t in top], "min_score": min_score,
        }

    # ---------- liste
    items = [t for t in titles if _match(t, view)]
    if q:
        ql = q.lower()
        items = [t for t in items if ql in (t["name"] or "").lower()]
    key = SORTS.get(sort, SORTS["score"])
    items.sort(key=key, reverse=(order != "asc"))
    page = items[offset:offset + max(1, min(limit, 1000))]
    return {"summary": summary, "total": len(items), "total_bytes": sum(t["alloc"] or 0 for t in items),
            "items": [_slim(t) for t in page]}


def _slim(t: dict) -> dict:
    keep = ("key", "kind", "name", "year", "library", "alloc", "video_count", "play_count", "last_played",
            "users_count", "recent_users_count", "added", "protected", "protect_reason", "best_resolution",
            "monitored", "radarr_id", "sonarr_id", "requests", "best", "suggestion_count", "delete_id",
            "delete_savings", "seasons")
    return {k: t.get(k) for k in keep}


def requester(name: str, view: str = "all", sort: str = "requested", order: str = "desc") -> dict:
    s = settings.get()
    min_score = s["analysis"]["min_score"]
    with db.conn() as c:
        titles = _titles(c, requester=name)
        by_title = _suggestions_by_title(c, [t["key"] for t in titles])
        for t in titles:
            _attach(t, by_title.get(t["key"], []), min_score)
            mine = [r for r in t["requests"] if r.get("by") == name]
            t["requested_at_by_user"] = max((r.get("at") or 0 for r in mine), default=0) or None
            t["watched_by_user"] = any(r.get("watched") for r in mine)

        def agg(items):
            return {"count": len(items), "bytes": sum(t["alloc"] or 0 for t in items)}
        unwatched = [t for t in titles if not t["watched_by_user"]]
        never = [t for t in titles if not t["play_count"]]
        old_unwatched = [t for t in unwatched if (_months_since(t["requested_at_by_user"]) or 0) >= 12]
        del_ids = [t["delete_id"] for t in unwatched if t["delete_id"] and not t["protected"]]
        freed = engine.selection_savings(c, del_ids)["freed"] if del_ids else 0
        summary = {
            "name": name, **agg(titles),
            "movies": agg([t for t in titles if t["kind"] == "movie"]),
            "series": agg([t for t in titles if t["kind"] == "series"]),
            "watched_by_user": agg([t for t in titles if t["watched_by_user"]]),
            "unwatched_by_user": agg(unwatched),
            "unwatched_older_than_12m": agg(old_unwatched),
            "never_watched": agg(never),
            "unwatched_delete": {"count": len(del_ids), "freed": freed},
            "first_request": min((t["requested_at_by_user"] for t in titles if t["requested_at_by_user"]), default=None),
            "last_request": max((t["requested_at_by_user"] or 0 for t in titles), default=None),
        }
    views = {
        "all": lambda t: True,
        "unwatched": lambda t: not t["watched_by_user"],
        "unwatched_old": lambda t: not t["watched_by_user"] and (_months_since(t["requested_at_by_user"]) or 0) >= 12,
        "never": lambda t: not t["play_count"],
        "watched": lambda t: t["watched_by_user"],
    }
    items = [t for t in titles if views.get(view, views["all"])(t)]
    sorts = {**SORTS, "requested": lambda t: t["requested_at_by_user"] or 0}
    items.sort(key=sorts.get(sort, sorts["requested"]), reverse=(order != "asc"))
    out = []
    for t in items:
        d = _slim(t)
        d["requested_at_by_user"] = t["requested_at_by_user"]
        d["watched_by_user"] = t["watched_by_user"]
        out.append(d)
    return {"summary": summary, "total": len(out), "items": out}
