"""FastAPI-app. Kun lesende endepunkter mot media; ingen sletting finnes i denne versjonen."""
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
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import actions, db, dupes, jobs, posters, settings, sync, updates, views
from .analysis import engine

VERSION = os.environ.get("SMC_VERSION", "0.7.1")
STATIC = Path(os.environ.get("SMC_STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))
logging.basicConfig(level=os.environ.get("SMC_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_app):
    db.init()
    actions.init()
    jobs.start(schedule=os.environ.get("SMC_DISABLE_SCHEDULER") != "1")
    with db.conn() as c:
        if not db.kv_get(c, "first_start"):
            db.kv_set(c, "first_start", time.time())
            if os.environ.get("SMC_DISABLE_SCHEDULER") != "1":
                jobs.enqueue("refresh")
    yield


logging.getLogger("httpx").setLevel(logging.WARNING)  # ikke logg hvert API-kall

app = FastAPI(title="Smart Media Cleanup", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json",
              lifespan=lifespan)


# ------------------------------------------------------------ valgfri innlogging
_USER = os.environ.get("SMC_USERNAME", "admin")
_PASS = os.environ.get("SMC_PASSWORD", "")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
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


# ------------------------------------------------------------ hjelpere
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
        out["datasets"] = tn.get("datasets")
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


# ------------------------------------------------------------ endepunkter
@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION, "read_only": not actions.enabled()}


class ActionRequest(BaseModel):
    ids: list[str]
    token: str | None = None


@app.post("/api/actions/plan")
def actions_plan(req: ActionRequest):
    return actions.plan(req.ids)


@app.post("/api/actions/execute")
def actions_execute(req: ActionRequest):
    try:
        return actions.execute(req.ids, req.token or "")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/actions/history")
def actions_history():
    return {"items": actions.history(), "enabled": actions.enabled()}


@app.get("/api/poster/{key:path}")
def poster(key: str):
    p = posters.get(key)
    if not p:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=3600"})
    return FileResponse(p, media_type=posters.media_type(p),
                        headers={"Cache-Control": "public, max-age=604800"})


@app.get("/api/update")
def update_status(refresh: bool = False):
    return updates.check(force=True) if refresh else updates.status()


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
            "running": jobs.overlay(db.rows(c, "SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY id")),
        }


_overview_cache: dict = {}


@app.get("/api/overview")
def overview():
    s = settings.get()
    with db.conn() as c:
        key = (json.dumps(db.kv_get(c, "last_analysis")), json.dumps(db.kv_get(c, "last_scan")),
               json.dumps(s["analysis"]), json.dumps(s["libraries"]))
    if _overview_cache.get("key") == key:
        return {**_overview_cache["value"], "capacity": _capacity()}
    value = _overview(s)
    _overview_cache.update(key=key, value=value)
    return value


def _overview(s: dict):
    min_score = s["analysis"]["min_score"]
    with db.conn() as c:
        libs = db.rows(c, """SELECT library, SUM(a) AS alloc, SUM(sz) AS size, SUM(n) AS files FROM (
                                SELECT library, MAX(alloc) a, MAX(size) sz, COUNT(*) n FROM files GROUP BY library, dev, inode)
                             GROUP BY library ORDER BY alloc DESC""")
        lib_cfg = {l["name"]: l for l in s["libraries"]}
        for l in libs:
            cfg = lib_cfg.get(l["library"], {})
            l.update({"kind": cfg.get("kind"), "protected": cfg.get("protected"), "host_path": cfg.get("host_path")})
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
        defs = [("Aldri sett", "last_played IS NULL", ()),
                (f"> {stale[2]} mnd", "last_played < ?", (now - stale[2] * m,)),
                (f"{stale[1]}–{stale[2]} mnd", "last_played >= ? AND last_played < ?", (now - stale[2] * m, now - stale[1] * m)),
                (f"{stale[0]}–{stale[1]} mnd", "last_played >= ? AND last_played < ?", (now - stale[1] * m, now - stale[0] * m)),
                (f"< {stale[0]} mnd", "last_played >= ?", (now - stale[0] * m,))]
        for label, where, params in defs:
            r = c.execute(f"SELECT COUNT(*), COALESCE(SUM(alloc),0), "
                          f"SUM(kind='movie'), SUM(kind='series') FROM titles WHERE {where}", params).fetchone()
            buckets.append({"label": label, "count": r[0], "bytes": r[1], "movies": r[2] or 0, "series": r[3] or 0})
        rare = c.execute("SELECT COUNT(*), COALESCE(SUM(alloc),0) FROM titles WHERE play_count BETWEEN 1 AND 2").fetchone()

        ids = [r[0] for r in c.execute("SELECT id FROM suggestions WHERE score >= ?", (min_score,))]
        total = engine.selection_savings(c, ids)
        by_kind = []
        for kind, in c.execute("SELECT DISTINCT kind FROM suggestions WHERE score >= ?", (min_score,)).fetchall():
            kids = [r[0] for r in c.execute("SELECT id FROM suggestions WHERE kind=? AND score >= ?", (kind, min_score))]
            sv = engine.selection_savings(c, kids)
            by_kind.append({"kind": kind, "count": len(kids), "freed": sv["freed"]})
        by_risk = []
        for risk in ("lav", "middels", "høy"):
            rids = [r[0] for r in c.execute("SELECT id FROM suggestions WHERE risk=? AND score >= ?", (risk, min_score))]
            by_risk.append({"risk": risk, "count": len(rids), "freed": engine.selection_savings(c, rids)["freed"]})

        largest_movies = db.rows(c, "SELECT key,name,year,alloc,best_resolution,play_count,last_played,library FROM titles WHERE kind='movie' ORDER BY alloc DESC LIMIT 10")
        largest_series = db.rows(c, "SELECT key,name,year,alloc,video_count,play_count,last_played,library FROM titles WHERE kind='series' ORDER BY alloc DESC LIMIT 10")
        largest_files = db.rows(c, """SELECT f.path, f.size, f.library, f.ext, ft.title_key, t.name AS title_name
                                      FROM files f LEFT JOIN file_title ft ON ft.path=f.path
                                      LEFT JOIN titles t ON t.key=ft.title_key ORDER BY f.size DESC LIMIT 10""")
        resolution = db.rows(c, """SELECT COALESCE(best_resolution,'Ukjent') AS res, COUNT(*) AS count, SUM(alloc) AS bytes
                                   FROM titles WHERE kind='movie' GROUP BY res ORDER BY bytes DESC""")
        top = [_sugg_row(r) for r in db.rows(c, SUGG_SELECT + " WHERE s.score >= ? ORDER BY s.score DESC, s.savings DESC LIMIT 12", (min_score,))]
        history_start = c.execute("SELECT MIN(date) FROM plays").fetchone()[0]
        return {
            "capacity": _capacity(), "libraries": libs, "counts": counts, "watch_buckets": buckets,
            "rarely_watched": {"count": rare[0], "bytes": rare[1]},
            "savings": {**total, "min_score": min_score, "by_kind": by_kind, "by_risk": by_risk},
            "largest_movies": largest_movies, "largest_series": largest_series, "largest_files": largest_files,
            "resolution": resolution, "top_suggestions": top, "history_start": history_start,
            "last_analysis": db.kv_get(c, "last_analysis"), "last_scan": db.kv_get(c, "last_scan"),
        }


SORTS = {"score": "s.score", "savings": "s.savings", "size": "s.size", "name": "COALESCE(t.name, s.label)",
         "last_played": "t.last_played", "risk": "CASE s.risk WHEN 'lav' THEN 0 WHEN 'middels' THEN 1 ELSE 2 END"}


@app.get("/api/suggestions")
def suggestions(q: str = "", kind: str = "", risk: str = "", library: str = "", requested_by: str = "",
                min_score: float | None = None,
                sort: str = "score", order: str = "desc", limit: int = 100, offset: int = 0):
    s = settings.get()
    where, params = ["1=1"], []
    if q:
        where.append("(s.label LIKE ? OR t.name LIKE ? OR s.location LIKE ?)")
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
    where.append("s.score >= ?")
    params.append(ms)
    col = SORTS.get(sort, "s.score")
    direction = "ASC" if order == "asc" else "DESC"
    limit = max(1, min(limit, 1000))
    with db.conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM suggestions s LEFT JOIN titles t ON t.key=s.title_key WHERE {' AND '.join(where)}", params).fetchone()[0]
        rows = db.rows(c, SUGG_SELECT + f" WHERE {' AND '.join(where)} ORDER BY {col} {direction} NULLS LAST, s.savings DESC LIMIT ? OFFSET ?",
                       params + [limit, offset])
        ids = [r[0] for r in c.execute(f"SELECT s.id FROM suggestions s LEFT JOIN titles t ON t.key=s.title_key WHERE {' AND '.join(where)}", params)]
        filtered = engine.selection_savings(c, ids)
    return {"total": total, "items": [_sugg_row(r) for r in rows], "filtered_savings": filtered}


@app.get("/api/suggestions/{sid}")
def suggestion(sid: str):
    with db.conn() as c:
        r = db.rows(c, SUGG_SELECT + " WHERE s.id=?", (sid,))
        if not r:
            raise HTTPException(404, "Fant ikke forslaget")
        files = db.rows(c, """SELECT sf.path, sf.claim, f.size, f.alloc, f.nlink, f.mtime, f.is_video, f.is_extra,
                                     ft.season, ft.episode
                              FROM suggestion_files sf JOIN files f ON f.path=sf.path
                              LEFT JOIN file_title ft ON ft.path=sf.path
                              WHERE sf.suggestion_id=? ORDER BY f.size DESC""", (sid,))
        overlaps = db.rows(c, """SELECT DISTINCT s2.id, s2.label, s2.kind, s2.action FROM suggestion_files a
                                 JOIN suggestion_files b ON a.path=b.path AND b.suggestion_id<>a.suggestion_id
                                 JOIN suggestions s2 ON s2.id=b.suggestion_id WHERE a.suggestion_id=?""", (sid,))
    return {**_sugg_row(r[0]), "files": files, "overlaps": overlaps}


class Selection(BaseModel):
    ids: list[str]


@app.post("/api/selection")
def selection(sel: Selection):
    with db.conn() as c:
        res = engine.selection_savings(c, sel.ids[:5000])
        ph = ",".join("?" * len(sel.ids[:5000])) or "''"
        res["items"] = db.rows(c, f"SELECT id,label,location,savings,risk,kind FROM suggestions WHERE id IN ({ph})", sel.ids[:5000])
    return res


@app.get("/api/titles")
def titles(q: str = "", kind: str = "", library: str = "", protected: str = "", requested_by: str = "",
           sort: str = "alloc",
           order: str = "desc", limit: int = 100, offset: int = 0):
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
            raise HTTPException(404, "Fant ikke tittelen")
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


@app.get("/api/requesters")
def requesters():
    """Per bruker i Seerr: hva er etterspurt, hvor mye plass, og hvor mye har de ikke sett selv."""
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
    items = sorted(out.values(), key=lambda e: -e["bytes"])
    return {"items": items, "seerr": last_sync}


@app.get("/api/library/{kind}")
def library(kind: str, view: str = "all", q: str = "", sort: str = "score", order: str = "desc",
            limit: int = 100, offset: int = 0):
    if kind not in ("movie", "series"):
        raise HTTPException(404, "Ukjent bibliotektype")
    return views.library(kind, view, q, sort, order, limit, offset)


@app.get("/api/requesters/{name}")
def requester_detail(name: str, view: str = "all", sort: str = "requested", order: str = "desc"):
    return views.requester(name, view, sort, order)


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
    try:
        return dupes.execute([g.model_dump() for g in req.groups], req.token or "")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


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
                                     ft.title_key, t.name AS title_name, t.play_count, t.last_played
                              FROM files f LEFT JOIN file_title ft ON ft.path=f.path LEFT JOIN titles t ON t.key=ft.title_key
                              WHERE {' AND '.join(where)} ORDER BY f.size DESC LIMIT ? OFFSET ?""",
                       params + [max(1, min(limit, 1000)), offset])
    return {"total": total, "total_bytes": total_bytes, "items": rows}


@app.get("/api/jobs")
def list_jobs():
    with db.conn() as c:
        return {"items": jobs.overlay(db.rows(c, "SELECT id,kind,status,progress,message,started,finished,error,log FROM jobs ORDER BY id DESC LIMIT 50")),
                "kinds": jobs.KINDS}


@app.post("/api/jobs/{kind}")
def start_job(kind: str):
    if kind not in jobs.KINDS:
        raise HTTPException(400, "Ukjent jobbtype")
    return jobs.enqueue(kind)


@app.get("/api/settings")
def get_settings():
    return settings.masked()


@app.put("/api/settings")
async def put_settings(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Ugyldig innhold")
    new = settings.save(body)
    with db.conn() as c:
        db.audit(c, "settings_saved", {"keys": sorted(body.keys())})
    return settings.masked(new)


@app.post("/api/services/{name}/test")
async def test_service(name: str, request: Request):
    if name not in sync.STATUS_FUNCS:
        raise HTTPException(404, "Ukjent tjeneste")
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


@app.get("/api/export/suggestions.csv")
def export_csv(min_score: float = 0):
    with db.conn() as c:
        rows = db.rows(c, SUGG_SELECT + " WHERE s.score >= ? ORDER BY s.score DESC", (min_score,))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["score", "risiko", "handling", "tittel", "plassering", "frigjøres_GB", "avspillinger", "sist_sett", "begrunnelse"])
    for r in rows:
        h = _j(r["history"], {})
        comps = _j(r["components"], [])
        w.writerow([r["score"], r["risk"], r["action"], r["label"], r["location"], round((r["savings"] or 0) / 1024 ** 3, 2),
                    h.get("plays"), time.strftime("%Y-%m-%d", time.localtime(h["last_played"])) if h.get("last_played") else "",
                    " | ".join(f"{x['label']} ({x['points']:+}): {x['detail']}" for x in comps)])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=oppryddingsforslag.csv"})


# ------------------------------------------------------------ frontend
if (STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    index = STATIC / "index.html"
    if index.is_file():
        f = STATIC / full_path
        if full_path and f.is_file() and STATIC in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(index)
    return JSONResponse({"detail": "Frontend er ikke bygget. API: /api/docs"}, status_code=404)
