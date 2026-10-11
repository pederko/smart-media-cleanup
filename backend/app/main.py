"""FastAPI app: the JSON API under /api and the built web UI.

Every response goes through LocalizedJSONResponse, which turns bilingual messages into the
language the browser asked for (X-Lang header from the UI, or Accept-Language).
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (actions, arrsetup, db, downloads, dupes, jobs, plexcheck, posters, quality, releases, settings, setup, swaps, sync,
               updates, views)
from .analysis import engine
from .i18n import L, AppError, LocalizedJSONResponse, lang_var, localize, parse_lang, text

VERSION = os.environ.get("SMC_VERSION", "1.1.0")
STATIC = Path(os.environ.get("SMC_STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))
NO_SCHEDULER = os.environ.get("SMC_DISABLE_SCHEDULER") == "1"
logging.basicConfig(level=os.environ.get("SMC_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # do not log every API call
log = logging.getLogger("smc")


@asynccontextmanager
async def lifespan(_app):
    db.init()
    actions.init()
    swaps.init()
    found = settings.ensure_libraries()
    if found:
        log.info("Libraries: %s", ", ".join(f"{l['name']} ({l['kind']}) -> {l['host_path']}" for l in found))
    jobs.start(schedule=not NO_SCHEDULER)
    with db.conn() as c:
        if not db.kv_get(c, "first_start"):
            db.kv_set(c, "first_start", time.time())
            if not NO_SCHEDULER and settings.get()["libraries"]:
                jobs.enqueue("refresh")
    yield


app = FastAPI(title="Smart Media Cleanup", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json",
              lifespan=lifespan, default_response_class=LocalizedJSONResponse)


# ------------------------------------------------------------ middleware: language and optional login
_USER = os.environ.get("SMC_USERNAME", "admin")
_PASS = os.environ.get("SMC_PASSWORD", "")


@app.middleware("http")
async def language_and_auth(request: Request, call_next):
    lang_var.set(parse_lang(request.headers.get("x-lang") or request.headers.get("accept-language")))
    if _PASS and request.url.path != "/api/health":
        hdr = request.headers.get("authorization", "")
        ok = False
        if hdr.lower().startswith("basic "):
            try:
                u, _, p = base64.b64decode(hdr[6:]).decode().partition(":")
                ok = secrets.compare_digest(u, _USER) and secrets.compare_digest(p, _PASS)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Smart Media Cleanup"'})
    return await call_next(request)


@app.exception_handler(AppError)
async def app_error(_request: Request, e: AppError):
    return LocalizedJSONResponse({"detail": e.msg}, status_code=e.status)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, e: StarletteHTTPException):
    return LocalizedJSONResponse({"detail": e.detail}, status_code=e.status_code, headers=getattr(e, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, e: RequestValidationError):
    return LocalizedJSONResponse({"detail": L("Invalid request", "Ugyldig forespørsel"), "errors": json.loads(json.dumps(e.errors(), default=str))},
                                 status_code=422)


def _not_found(what_en: str, what_nb: str):
    raise HTTPException(404, L(f"{what_en} not found", f"Fant ikke {what_nb}"))


# ------------------------------------------------------------ helpers
def _j(v, default=None):
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


def _capacity() -> dict:
    s = settings.get()
    out = {"source": None}
    for lib in s["libraries"]:
        p = lib.get("container_path")
        if p and os.path.isdir(p):
            st = os.statvfs(p)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            out = {"source": "statvfs", "path": lib["host_path"], "total": total, "free": free, "used": total - free}
            break
    with db.conn() as c:
        tn = db.kv_get(c, "truenas")
    if tn and tn.get("pool", {}).get("size"):
        p = tn["pool"]
        out["pool"] = {"name": p["name"], "size": p["size"], "allocated": p["allocated"], "free": p["free"],
                       "status": p.get("status"), "fetched": tn.get("fetched")}
        out["root_snapshots"] = tn.get("root_snapshots")
    return out


def _sugg_row(r: dict) -> dict:
    r = dict(r)
    for k, d in (("reasons", []), ("consequences", []), ("components", []), ("history", {}), ("requests", [])):
        r[k] = _j(r.get(k), d)
    return r


SUGG_SELECT = """
SELECT s.*, t.name AS title_name, t.year, t.kind AS title_kind, t.library, t.monitored, t.best_resolution,
       t.radarr_id, t.sonarr_id, t.size AS title_size, t.requested_by, t.requested_at, t.requests
FROM suggestions s LEFT JOIN titles t ON t.key = s.title_key
"""
RECOMMENDED_SCORE = 50


class IdsRequest(BaseModel):
    ids: list[str]
    token: str | None = None


class KeysRequest(BaseModel):
    keys: list[str]
    token: str | None = None


class PathsRequest(BaseModel):
    paths: list[str]
    token: str | None = None


# ------------------------------------------------------------ status, overview, setup
@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION, "read_only": not actions.enabled()}


@app.get("/api/status")
def status():
    with db.conn() as c:
        return {
            "version": VERSION,
            "read_only": not actions.enabled(),
            "actions_enabled": actions.enabled(),
            "files_enabled": dupes.enabled(),
            "writable": dupes.writable_libraries(),
            "services": db.kv_get(c, "service_status", {}),
            "last_sync": db.kv_get(c, "last_sync"),
            "last_scan": db.kv_get(c, "last_scan"),
            "last_full_scan": db.kv_get(c, "last_full_scan"),
            "last_analysis": db.kv_get(c, "last_analysis"),
            "libraries": len(settings.get()["libraries"]),
            "running": jobs.overlay(db.rows(c, "SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY id")),
            "active_swaps": c.execute(f"SELECT COUNT(*) FROM swaps WHERE state IN ({','.join('?' * len(swaps.ACTIVE))})",
                                      swaps.ACTIVE).fetchone()[0],
        }


@app.get("/api/setup")
def setup_status():
    return setup.status()


@app.post("/api/setup/detect-libraries")
def setup_detect():
    """Replace the configured libraries with the ones found under /media (keeps kind/protection by name)."""
    old = {l["name"]: l for l in settings.get()["libraries"]}
    found = settings.detect_libraries()
    for l in found:
        if l["name"] in old:
            l.update({k: old[l["name"]][k] for k in ("kind", "protected") if k in old[l["name"]]})
    s = settings.get()
    s["libraries"] = found
    settings.save(s)
    return settings.masked()


_overview_cache: dict = {}


@app.get("/api/overview")
def overview():
    s = settings.get()
    with db.conn() as c:
        key = (json.dumps(db.kv_get(c, "last_analysis")), json.dumps(db.kv_get(c, "last_scan")),
               json.dumps(db.kv_get(c, "last_sync")), json.dumps(s["analysis"]), json.dumps(s["libraries"]))
    if _overview_cache.get("key") == key:
        return {**_overview_cache["value"], "capacity": _capacity()}
    value = _overview(s)
    _overview_cache.update(key=key, value=value)
    return value


def _freed_for_kinds(c, kinds: tuple, min_score: float) -> int:
    ids = [r[0] for r in c.execute(f"SELECT id FROM suggestions WHERE kind IN ({','.join('?' * len(kinds))}) AND score >= ?",
                                   (*kinds, min_score))]
    return engine.selection_savings(c, ids)["freed"] if ids else 0


def _overview(s: dict):
    min_score = s["analysis"]["min_score"]
    with db.conn() as c:
        libs = db.rows(c, """SELECT library, SUM(a) AS alloc, SUM(sz) AS size, SUM(n) AS files FROM (
                                SELECT library, MAX(alloc) a, MAX(size) sz, COUNT(*) n FROM files GROUP BY library, dev, inode)
                             GROUP BY library ORDER BY alloc DESC""")
        lib_cfg = {l["name"]: l for l in s["libraries"]}
        order = list(lib_cfg)
        for l in libs:
            cfg = lib_cfg.get(l["library"], {})
            l.update({"kind": cfg.get("kind"), "protected": cfg.get("protected"), "host_path": cfg.get("host_path"),
                      "index": order.index(l["library"]) if l["library"] in order else len(order)})
        counts = {
            "movies": c.execute("SELECT COUNT(*) FROM titles WHERE kind='movie'").fetchone()[0],
            "series": c.execute("SELECT COUNT(*) FROM titles WHERE kind='series'").fetchone()[0],
            "episodes": c.execute("""SELECT COUNT(*) FROM (SELECT DISTINCT ft.title_key, ft.season, ft.episode
                                     FROM file_title ft JOIN files f ON f.path=ft.path
                                     JOIN titles t ON t.key=ft.title_key
                                     WHERE t.kind='series' AND f.is_video=1 AND f.is_extra=0 AND ft.episode IS NOT NULL)""").fetchone()[0],
            "files": c.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "protected": c.execute("SELECT COUNT(*) FROM titles WHERE protected=1").fetchone()[0],
        }
        now = time.time()
        stale = sorted(s["analysis"]["stale_months"])
        m = 30.44 * 86400
        buckets = []
        defs = [("never", L("Never watched", "Aldri sett"), "last_played IS NULL", ()),
                ("gt", L(f"> {stale[2]} months", f"> {stale[2]} mnd"), "last_played < ?", (now - stale[2] * m,)),
                ("mid2", L(f"{stale[1]}–{stale[2]} months", f"{stale[1]}–{stale[2]} mnd"), "last_played >= ? AND last_played < ?",
                 (now - stale[2] * m, now - stale[1] * m)),
                ("mid1", L(f"{stale[0]}–{stale[1]} months", f"{stale[0]}–{stale[1]} mnd"), "last_played >= ? AND last_played < ?",
                 (now - stale[1] * m, now - stale[0] * m)),
                ("recent", L(f"< {stale[0]} months", f"< {stale[0]} mnd"), "last_played >= ?", (now - stale[0] * m,))]
        for code, label, where, params in defs:
            r = c.execute(f"SELECT COUNT(*), COALESCE(SUM(alloc),0), SUM(kind='movie'), SUM(kind='series') "
                          f"FROM titles WHERE {where}", params).fetchone()
            buckets.append({"code": code, "label": label, "count": r[0], "bytes": r[1], "movies": r[2] or 0, "series": r[3] or 0})

        ids = [r[0] for r in c.execute("SELECT id FROM suggestions WHERE score >= ?", (min_score,))]
        total = engine.selection_savings(c, ids)
        rec_score = max(min_score, RECOMMENDED_SCORE)
        rec_ids = [r[0] for r in c.execute("SELECT id FROM suggestions WHERE score >= ? AND risk <> 'high'", (rec_score,))]
        recommended = engine.selection_savings(c, rec_ids)
        by_kind = []
        for (kind,) in c.execute("SELECT DISTINCT kind FROM suggestions WHERE score >= ?", (min_score,)).fetchall():
            kids = [r[0] for r in c.execute("SELECT id FROM suggestions WHERE kind=? AND score >= ?", (kind, min_score))]
            by_kind.append({"kind": kind, "count": len(kids), "freed": engine.selection_savings(c, kids)["freed"]})
        by_risk = []
        for risk in ("low", "medium", "high"):
            rids = [r[0] for r in c.execute("SELECT id FROM suggestions WHERE risk=? AND score >= ?", (risk, min_score))]
            by_risk.append({"risk": risk, "count": len(rids), "freed": engine.selection_savings(c, rids)["freed"]})
        delete_count = c.execute("SELECT COUNT(*) FROM suggestions WHERE kind IN ('delete_title','delete_season') "
                                 "AND score >= ? AND risk <> 'high'", (rec_score,)).fetchone()[0]
        delete_freed = _freed_for_kinds(c, ("delete_title", "delete_season"), rec_score)
        dup = c.execute("SELECT COUNT(*), COALESCE(SUM(reclaimable),0) FROM duplicate_groups WHERE kind <> 'hardlink' "
                        "AND reclaimable > 0").fetchone()
        top = [_sugg_row(r) for r in db.rows(c, SUGG_SELECT + " WHERE s.score >= ? AND s.risk <> 'high' "
                                                              "ORDER BY s.score DESC, s.savings DESC LIMIT 8", (rec_score,))]
        history_start = c.execute("SELECT MIN(date) FROM plays").fetchone()[0]
        last_analysis = db.kv_get(c, "last_analysis")
        last_scan = db.kv_get(c, "last_scan")

    # areas – one figure per place where space can be freed
    dl = downloads.overview()["summary"]
    pc = plexcheck.overview()
    qs = quality.candidates()["summary"]
    dl_delete = dl["by_advice"].get("delete") or {}
    areas = {
        "delete": {"count": delete_count, "freed": delete_freed},
        "quality": {"count": qs["count"], "freed": qs["estimate"], "found": qs["found_savings"]},
        "duplicates": {"count": dup[0], "freed": dup[1]},
        "downloads": {"count": dl_delete.get("count", 0), "freed": dl_delete.get("freed", 0), "total": dl["size"]},
        "plex": {"available": pc.get("available", False),
                 "not_in_plex": (pc.get("summary") or {}).get("not_in_plex", {}),
                 "missing": (pc.get("summary") or {}).get("missing", {})},
    }
    return {
        "capacity": _capacity(), "libraries": libs, "counts": counts, "watch_buckets": buckets,
        "savings": {**total, "min_score": min_score, "by_kind": by_kind, "by_risk": by_risk,
                    "recommended": {**recommended, "min_score": rec_score}},
        "areas": areas, "top_suggestions": top, "history_start": history_start,
        "last_analysis": last_analysis, "last_scan": last_scan,
    }


# ------------------------------------------------------------ suggestions
SORTS = {"score": "s.score", "savings": "s.savings", "size": "s.size", "name": "COALESCE(t.name, s.name)",
         "last_played": "t.last_played", "risk": "CASE s.risk WHEN 'low' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"}


@app.get("/api/suggestions")
def suggestions(q: str = "", kind: str = "", risk: str = "", library: str = "", requested_by: str = "",
                min_score: float | None = None, recommended: bool = False,
                sort: str = "score", order: str = "desc", limit: int = 100, offset: int = 0):
    s = settings.get()
    where, params = ["1=1"], []
    if q:
        where.append("(s.name LIKE ? OR t.name LIKE ? OR s.location LIKE ?)")
        params += [f"%{q}%"] * 3
    if kind:
        ks = kind.split(",")
        where.append(f"s.kind IN ({','.join('?' * len(ks))})")
        params += ks
    if risk:
        rs = risk.split(",")
        where.append(f"s.risk IN ({','.join('?' * len(rs))})")
        params += rs
    if library:
        where.append("t.library = ?")
        params.append(library)
    if requested_by:
        where.append("EXISTS (SELECT 1 FROM json_each(t.requests) j WHERE json_extract(j.value, '$.by') = ?)")
        params.append(requested_by)
    ms = s["analysis"]["min_score"] if min_score is None else min_score
    if recommended:
        ms = max(ms, RECOMMENDED_SCORE)
        where.append("s.risk <> 'high'")
    where.append("s.score >= ?")
    params.append(ms)
    col = SORTS.get(sort, "s.score")
    direction = "ASC" if order == "asc" else "DESC"
    limit = max(1, min(limit, 1000))
    with db.conn() as c:
        cond = " AND ".join(where)
        total = c.execute(f"SELECT COUNT(*) FROM suggestions s LEFT JOIN titles t ON t.key=s.title_key WHERE {cond}", params).fetchone()[0]
        rows = db.rows(c, SUGG_SELECT + f" WHERE {cond} ORDER BY {col} {direction} NULLS LAST, s.savings DESC LIMIT ? OFFSET ?",
                       params + [limit, offset])
        ids = [r[0] for r in c.execute(f"SELECT s.id FROM suggestions s LEFT JOIN titles t ON t.key=s.title_key WHERE {cond}", params)]
        filtered = engine.selection_savings(c, ids)
    return {"total": total, "items": [_sugg_row(r) for r in rows], "filtered_savings": filtered,
            "min_score": ms, "recommended_score": RECOMMENDED_SCORE}


@app.get("/api/suggestions/{sid}")
def suggestion(sid: str):
    with db.conn() as c:
        r = db.rows(c, SUGG_SELECT + " WHERE s.id=?", (sid,))
        if not r:
            _not_found("Suggestion", "forslaget")
        files = db.rows(c, """SELECT sf.path, sf.claim, f.size, f.alloc, f.nlink, f.mtime, f.is_video, f.is_extra,
                                     ft.season, ft.episode
                              FROM suggestion_files sf JOIN files f ON f.path=sf.path
                              LEFT JOIN file_title ft ON ft.path=sf.path
                              WHERE sf.suggestion_id=? ORDER BY f.size DESC""", (sid,))
        overlaps = db.rows(c, """SELECT DISTINCT s2.id, s2.label, s2.name, s2.kind, s2.action FROM suggestion_files a
                                 JOIN suggestion_files b ON a.path=b.path AND b.suggestion_id<>a.suggestion_id
                                 JOIN suggestions s2 ON s2.id=b.suggestion_id WHERE a.suggestion_id=?""", (sid,))
    return {**_sugg_row(r[0]), "files": files, "overlaps": overlaps}


@app.post("/api/selection")
def selection(sel: IdsRequest):
    ids = sel.ids[:5000]
    with db.conn() as c:
        res = engine.selection_savings(c, ids)
        ph = ",".join("?" * len(ids)) or "''"
        res["items"] = db.rows(c, f"SELECT id,label,name,location,savings,risk,kind FROM suggestions WHERE id IN ({ph})", ids)
    return res


@app.get("/api/export/suggestions.csv")
def export_csv(min_score: float = 0):
    with db.conn() as c:
        rows = db.rows(c, SUGG_SELECT + " WHERE s.score >= ? ORDER BY s.score DESC", (min_score,))
    nb = lang_var.get() == "nb"
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";" if nb else ",")
    w.writerow(["score", "risiko", "handling", "tittel", "plassering", "frigjøres_GB", "avspillinger", "sist_sett", "begrunnelse"]
               if nb else ["score", "risk", "action", "title", "location", "freed_GB", "plays", "last_watched", "reasons"])
    for r in rows:
        h = _j(r["history"], {})
        comps = localize(_j(r["components"], []))
        w.writerow([r["score"], r["risk"], text(r["label"]), r.get("name") or r["title_name"] or "", r["location"],
                    round((r["savings"] or 0) / 1024 ** 3, 2), h.get("plays"),
                    time.strftime("%Y-%m-%d", time.localtime(h["last_played"])) if h.get("last_played") else "",
                    " | ".join(f"{x['label']} ({x['points']:+}): {x['detail']}" for x in comps)])
    name = "oppryddingsforslag.csv" if nb else "cleanup-suggestions.csv"
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


# ------------------------------------------------------------ deletion via Radarr/Sonarr
@app.post("/api/actions/plan")
def actions_plan(req: IdsRequest):
    return actions.plan(req.ids)


@app.post("/api/actions/execute")
def actions_execute(req: IdsRequest):
    return actions.execute(req.ids, req.token or "")


@app.get("/api/actions/history")
def actions_history():
    return {"items": actions.history(), "enabled": actions.enabled(), "files_enabled": dupes.enabled()}


# ------------------------------------------------------------ titles, library views, users
@app.get("/api/titles")
def titles(q: str = "", kind: str = "", library: str = "", protected: str = "", requested_by: str = "",
           sort: str = "alloc", order: str = "desc", limit: int = 100, offset: int = 0):
    where, params = ["1=1"], []
    if q:
        where.append("name LIKE ?")
        params.append(f"%{q}%")
    if kind:
        where.append("kind=?")
        params.append(kind)
    if library:
        where.append("library=?")
        params.append(library)
    if protected in ("0", "1"):
        where.append("protected=?")
        params.append(int(protected))
    if requested_by:
        where.append("EXISTS (SELECT 1 FROM json_each(requests) j WHERE json_extract(j.value, '$.by') = ?)")
        params.append(requested_by)
    cols = {"alloc": "alloc", "name": "name", "plays": "play_count", "last_played": "last_played", "added": "added"}
    col = cols.get(sort, "alloc")
    d = "ASC" if order == "asc" else "DESC"
    with db.conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM titles WHERE {' AND '.join(where)}", params).fetchone()[0]
        rows = db.rows(c, f"SELECT * FROM titles WHERE {' AND '.join(where)} ORDER BY {col} {d} NULLS LAST LIMIT ? OFFSET ?",
                       params + [max(1, min(limit, 1000)), offset])
    for r in rows:
        for k in ("plex_keys", "tags", "users", "seasons", "requests"):
            r[k] = _j(r.get(k), [] if k != "seasons" else {})
    return {"total": total, "items": rows}


@app.get("/api/titles/{key:path}")
def title(key: str):
    with db.conn() as c:
        r = db.rows(c, "SELECT * FROM titles WHERE key=?", (key,))
        if not r:
            _not_found("Title", "tittelen")
        t = r[0]
        for k in ("plex_keys", "tags", "users", "seasons", "requests"):
            t[k] = _j(t.get(k), [] if k != "seasons" else {})
        t["files"] = db.rows(c, """SELECT f.path, f.size, f.alloc, f.nlink, f.mtime, f.is_video, f.is_extra, f.ext,
                                          ft.season, ft.episode FROM file_title ft JOIN files f ON f.path=ft.path
                                   WHERE ft.title_key=? ORDER BY ft.season, ft.episode, f.size DESC""", (key,))
        t["suggestions"] = [_sugg_row(x) for x in db.rows(c, SUGG_SELECT + " WHERE s.title_key=? ORDER BY s.score DESC", (key,))]
        plex_keys = t["plex_keys"]
        if plex_keys:
            ph = ",".join("?" * len(plex_keys))
            t["recent_plays"] = db.rows(c, f"""SELECT date, user, title, parent_index, percent FROM plays
                                              WHERE rating_key IN ({ph}) OR grandparent_key IN ({ph})
                                              ORDER BY date DESC LIMIT 50""", plex_keys + plex_keys)
        else:
            t["recent_plays"] = []
    return t


@app.get("/api/library/{kind}")
def library(kind: str, view: str = "all", q: str = "", sort: str = "score", order: str = "desc",
            limit: int = 100, offset: int = 0):
    if kind not in ("movie", "series", "all"):
        _not_found("Library type", "bibliotektypen")
    return views.library(None if kind == "all" else kind, view, q, sort, order, limit, offset)


@app.get("/api/requesters")
def requesters():
    """Per Seerr user: what was requested, how much space, and how much they have not watched themselves."""
    out: dict[str, dict] = {}
    with db.conn() as c:
        rows = db.rows(c, "SELECT key, alloc, play_count, protected, requests FROM titles WHERE requests IS NOT NULL AND requests <> '[]'")
        last_sync = (db.kv_get(c, "service_status", {}) or {}).get("seerr")
    for t in rows:
        seen_here = set()
        for r in _j(t["requests"], []):
            name = r.get("by")
            if not name or name in seen_here:
                continue
            seen_here.add(name)
            e = out.setdefault(name, {"name": name, "titles": 0, "bytes": 0, "not_watched_by_requester": 0,
                                      "not_watched_bytes": 0, "never_watched": 0, "never_watched_bytes": 0,
                                      "last_request": 0})
            e["titles"] += 1
            e["bytes"] += t["alloc"] or 0
            e["last_request"] = max(e["last_request"], r.get("at") or 0)
            if not r.get("watched"):
                e["not_watched_by_requester"] += 1
                e["not_watched_bytes"] += t["alloc"] or 0
            if not t["play_count"]:
                e["never_watched"] += 1
                e["never_watched_bytes"] += t["alloc"] or 0
    return {"items": sorted(out.values(), key=lambda e: -e["bytes"]), "seerr": last_sync}


@app.get("/api/requesters/{name}")
def requester_detail(name: str, view: str = "all", sort: str = "requested", order: str = "desc"):
    return views.requester(name, view, sort, order)


@app.get("/api/poster/{key:path}")
def poster(key: str):
    p = posters.get(key)
    if not p:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=3600"})
    return FileResponse(p, media_type=posters.media_type(p), headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/files/largest")
def largest_files(library: str = "", ext: str = "", min_gb: float = 0, limit: int = 100, offset: int = 0):
    where, params = ["f.size >= ?"], [int(min_gb * 1024 ** 3)]
    if library:
        where.append("f.library=?")
        params.append(library)
    if ext:
        where.append("f.ext=?")
        params.append(ext if ext.startswith(".") else "." + ext)
    with db.conn() as c:
        total, total_bytes = c.execute(f"SELECT COUNT(*), COALESCE(SUM(f.size),0) FROM files f WHERE {' AND '.join(where)}", params).fetchone()
        rows = db.rows(c, f"""SELECT f.path, f.size, f.alloc, f.library, f.ext, f.nlink, f.mtime, f.is_extra,
                                     ft.title_key, t.name AS title_name, t.year, t.play_count, t.last_played,
                                     t.radarr_id, t.sonarr_id, sf.season
                              FROM files f LEFT JOIN file_title ft ON ft.path=f.path LEFT JOIN titles t ON t.key=ft.title_key
                              LEFT JOIN sonarr_files sf ON sf.path=f.path
                              WHERE {' AND '.join(where)} ORDER BY f.size DESC LIMIT ? OFFSET ?""",
                       params + [max(1, min(limit, 1000)), offset])
    return {"total": total, "total_bytes": total_bytes, "items": rows}


# ------------------------------------------------------------ duplicates and downloads
@app.get("/api/duplicates")
def duplicates(kind: str = "", q: str = "", library: str = "", where: str = "", sort: str = "reclaimable",
               order: str = "desc", limit: int = 200, offset: int = 0):
    return dupes.overview(kind, q, library, where, sort, order, limit, offset)


class DupeChoice(BaseModel):
    id: str
    keep: str | None = None


class DupeRequest(BaseModel):
    groups: list[DupeChoice]
    token: str | None = None


@app.post("/api/duplicates/plan")
def duplicates_plan(req: DupeRequest):
    return dupes.plan([g.model_dump() for g in req.groups])


@app.post("/api/duplicates/execute")
def duplicates_execute(req: DupeRequest):
    return dupes.execute([g.model_dump() for g in req.groups], req.token or "")


@app.get("/api/downloads")
def downloads_overview(library: str = "", status: str = "", advice: str = "", q: str = "", sort: str = "size",
                       order: str = "desc"):
    return downloads.overview(library, status, advice, q, sort, order)


@app.post("/api/downloads/plan")
def downloads_plan(req: PathsRequest):
    return downloads.plan(req.paths)


@app.post("/api/downloads/execute")
def downloads_execute(req: PathsRequest):
    return downloads.execute(req.paths, req.token or "")


# ------------------------------------------------------------ smaller versions and swaps
@app.get("/api/releases/{key:path}")
def find_releases(key: str, season: int | None = None, refresh: bool = False):
    return releases.search(key, season, refresh)


@app.get("/api/quality")
def quality_candidates(kind: str = "", min_movie_gb: float | None = None, min_episode_gb: float | None = None,
                       q: str = "", unwatched: bool = False, sort: str = "savings"):
    return quality.candidates(kind, min_movie_gb, min_episode_gb, q, unwatched, sort)


class SwapRequest(BaseModel):
    key: str
    guid: str
    indexer_id: int
    season: int | None = None
    after_swap: str = "none"


class SwapBatchItem(BaseModel):
    key: str
    season: int | None = None
    guid: str
    indexer_id: int


class SwapBatch(BaseModel):
    items: list[SwapBatchItem]
    after_swap: str = "none"


@app.post("/api/swaps")
def swap_start(req: SwapRequest):
    return swaps.start(req.key, req.guid, req.indexer_id, req.season, req.after_swap)


@app.post("/api/swaps/batch")
def swaps_batch(req: SwapBatch):
    return quality.start_many([i.model_dump() for i in req.items], req.after_swap)


@app.get("/api/swaps")
def swap_list(key: str = ""):
    return {"items": swaps.list_swaps(key or None)}


@app.get("/api/swaps/{sid}")
def swap_get(sid: int):
    return swaps.get(sid)


@app.post("/api/swaps/{sid}/poll")
def swap_poll(sid: int):
    swaps.poll(sid)
    return swaps.get(sid)


@app.post("/api/swaps/{sid}/cancel")
def swap_cancel(sid: int):
    return swaps.cancel(sid)


@app.get("/api/quality-profiles/{service}")
def quality_profiles(service: str):
    if service not in ("radarr", "sonarr"):
        _not_found("Service", "tjenesten")
    return {"items": swaps.quality_profiles(service)}


# ------------------------------------------------------------ download rules (Radarr/Sonarr/Seerr/qBittorrent setup)
@app.get("/api/arr-setup")
def arr_setup():
    return arrsetup.overview()


class ChangesRequest(BaseModel):
    changes: list[dict]
    token: str | None = None


@app.post("/api/arr-setup/plan")
def arr_setup_plan(req: ChangesRequest):
    return arrsetup.public(arrsetup.plan(req.changes))


@app.post("/api/arr-setup/execute")
def arr_setup_execute(req: ChangesRequest):
    return arrsetup.execute(req.changes, req.token or "")


@app.get("/api/arr-setup/backups")
def arr_setup_backups():
    return {"items": arrsetup.backups()}


class BackupRequest(BaseModel):
    name: str


@app.post("/api/arr-setup/restore")
def arr_setup_restore(req: BackupRequest):
    return arrsetup.restore(req.name)


# ------------------------------------------------------------ Plex differences and other storage
@app.get("/api/plex-check")
def plex_check(view: str = "not_in_plex", q: str = "", library: str = ""):
    return plexcheck.overview(view, q, library)


class FolderRequest(BaseModel):
    folder: str


@app.post("/api/plex-check/rescan")
def plex_rescan(req: FolderRequest):
    return plexcheck.rescan(req.folder)


@app.post("/api/plex-check/delete/plan")
def plex_check_delete_plan(req: KeysRequest):
    return plexcheck.delete_plan(req.keys)


@app.post("/api/plex-check/delete/execute")
def plex_check_delete_execute(req: KeysRequest):
    return plexcheck.delete_execute(req.keys, req.token or "")


@app.post("/api/plex-check/remove/plan")
def plex_check_remove_plan(req: KeysRequest):
    return plexcheck.plex_remove_plan(req.keys)


@app.post("/api/plex-check/remove/execute")
def plex_check_remove_execute(req: KeysRequest):
    return plexcheck.plex_remove_execute(req.keys, req.token or "")


@app.get("/api/other-storage")
def other_storage():
    return views.other_storage()


# ------------------------------------------------------------ jobs, settings, updates
@app.get("/api/jobs")
def list_jobs():
    with db.conn() as c:
        return {"items": jobs.overlay(db.rows(c, "SELECT id,kind,status,progress,message,started,finished,error,log "
                                                 "FROM jobs ORDER BY id DESC LIMIT 50")),
                "kinds": jobs.KINDS}


@app.post("/api/jobs/{kind}")
def start_job(kind: str):
    if kind not in jobs.KINDS:
        raise HTTPException(400, L("Unknown job type", "Ukjent jobbtype"))
    return jobs.enqueue(kind)


@app.get("/api/settings")
def get_settings():
    return settings.masked()


@app.put("/api/settings")
async def put_settings(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, L("Invalid content", "Ugyldig innhold"))
    new = settings.save(body)
    with db.conn() as c:
        db.audit(c, "settings_saved", {"keys": sorted(body.keys())})
    return settings.masked(new)


@app.post("/api/services/{name}/test")
async def test_service(name: str, request: Request):
    if name not in sync.STATUS_FUNCS:
        _not_found("Service", "tjenesten")
    cfg = dict(settings.get()["services"][name])
    try:
        body = await request.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        for k, v in body.items():
            if v != settings.MASK:
                cfg[k] = v
    return sync.test_service(name, cfg)


@app.get("/api/update")
def update_status(refresh: bool = False):
    return updates.check(force=True) if refresh else updates.status()


# ------------------------------------------------------------ frontend
if (STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, L("Not found", "Finnes ikke"))
    index = STATIC / "index.html"
    if index.is_file():
        f = STATIC / full_path
        if full_path and f.is_file() and STATIC in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(index)
    raise HTTPException(404, L("The web UI is not built. API: /api/docs", "Nettsiden er ikke bygget. API: /api/docs"))
