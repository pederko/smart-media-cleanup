"""Deleting through Radarr and Sonarr (optional, off by default).

Safety model:
  * Titles are never deleted on disk by the app – deletion goes through the Radarr/Sonarr API,
    so they stay in sync and do not download the title again.
  * Must be switched on under Settings → Deletion.
  * Protected titles (library, tags, Plex labels, paths) are always refused.
  * Two steps: plan (what happens, how much is freed) and execute. Execute requires the plan's
    token, so exactly what was shown is executed – not a newer analysis.
  * Right before each deletion the title is fetched again from Radarr/Sonarr and compared with
    the analysis (still exists, same folder). A mismatch stops that deletion.
  * Every action is logged in the `actions` table and in `audit`.
"""
from __future__ import annotations

import hashlib
import logging
import time

import httpx

from . import db, jobs, settings
from .analysis import engine
from .clients.base import ServiceError
from .i18n import L, ActionError, Conflict, Forbidden, fmt, store, text

log = logging.getLogger("smc.actions")
TIMEOUT = httpx.Timeout(180.0, connect=10.0)  # indexer searches in Radarr/Sonarr can be slow

# Status values in the actions log
DONE, FAILED, SKIPPED = "done", "failed", "skipped"

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, suggestion_id TEXT,
  title_key TEXT, title TEXT, action TEXT, service TEXT, status TEXT, detail TEXT, bytes INTEGER);
"""

__all__ = ["ActionError", "plan", "execute", "history", "enabled", "init", "log_action"]


def enabled() -> bool:
    return bool(settings.get().get("actions", {}).get("enabled", False))


def log_action(c, *, title: str, action: str, service: str | None, status: str, detail, bytes_: int = 0,
               suggestion_id: str | None = None, title_key: str | None = None) -> None:
    """One row in the user-facing action log (and the audit table)."""
    c.execute("INSERT INTO actions(ts,suggestion_id,title_key,title,action,service,status,detail,bytes) "
              "VALUES(?,?,?,?,?,?,?,?,?)",
              (time.time(), suggestion_id, title_key, title, action, service, status, store(detail),
               bytes_ if status == DONE else 0))
    db.audit(c, action, {"title": title, "status": status, "detail": text(detail, "en")})


# ------------------------------------------------------------------ plan

def _describe(s: dict, t: dict | None) -> dict:
    """What can be done with this suggestion, and how."""
    base = {"id": s["id"], "label": s["label"], "name": s.get("name") or s["location"], "location": s["location"],
            "kind": s["kind"], "risk": s["risk"], "savings": s["savings"], "title_key": s["title_key"]}
    if t is None:
        return {**base, "executable": False,
                "reason": L("Not linked to Radarr/Sonarr – see Downloads or Duplicates.",
                            "Ikke knyttet til Radarr/Sonarr – se Nedlastinger eller Duplikater.")}
    if t["protected"]:
        return {**base, "executable": False, "reason": fmt("Protected: {r}", "Beskyttet: {r}", r=t["protect_reason"])}
    if s["kind"] == "delete_title" and t["radarr_id"] is not None:
        return {**base, "executable": True, "service": "radarr", "target": t["radarr_id"],
                "how": L("Deleted in Radarr with its files. The movie is removed from Radarr.",
                         "Slettes i Radarr med filer. Filmen fjernes fra Radarr.")}
    if s["kind"] == "delete_title" and t["sonarr_id"] is not None:
        return {**base, "executable": True, "service": "sonarr", "target": t["sonarr_id"],
                "how": L("Deleted in Sonarr with its files. The series is removed from Sonarr.",
                         "Slettes i Sonarr med filer. Serien fjernes fra Sonarr.")}
    if s["kind"] == "delete_season" and t["sonarr_id"] is not None:
        season = int(s["scope"].split(":", 1)[1])
        return {**base, "executable": True, "service": "sonarr", "target": t["sonarr_id"], "season": season,
                "how": L(f"Season {season} is unmonitored in Sonarr, then the episode files are deleted.",
                         f"Sesong {season} avovervåkes i Sonarr, deretter slettes episodefilene.")}
    reasons = {
        "replace": L("Use «Find a smaller version» or the Quality page to swap.",
                     "Bruk «Finn mindre versjon» eller siden Bytt kvalitet for å bytte."),
        "remove_versions": L("Extra versions are cleaned up on the Duplicates page.",
                             "Ekstra versjoner ryddes på siden Duplikater."),
        "remove_copy": L("Identical copies are cleaned up on the Duplicates page.",
                         "Identiske kopier ryddes på siden Duplikater."),
        "download": L("Downloads are cleaned up on the Downloads page.", "Nedlastinger ryddes på siden Nedlastinger."),
    }
    return {**base, "executable": False,
            "reason": reasons.get(s["kind"], L("Not managed by Radarr/Sonarr.", "Ikke administrert av Radarr/Sonarr."))}


def _token(items: list[dict], c) -> str:
    h = hashlib.sha256()
    for it in sorted((i for i in items if i["executable"]), key=lambda i: i["id"]):
        h.update(it["id"].encode())
        for (p,) in c.execute("SELECT path FROM suggestion_files WHERE suggestion_id=? ORDER BY path", (it["id"],)):
            h.update(p.encode())
    return h.hexdigest()[:24]


def plan(ids: list[str]) -> dict:
    ids = list(dict.fromkeys(ids))[:500]
    with db.conn() as c:
        ph = ",".join("?" * len(ids)) or "''"
        sugg = {r["id"]: r for r in db.rows(c, f"SELECT * FROM suggestions WHERE id IN ({ph})", ids)}
        keys = [s["title_key"] for s in sugg.values() if s["title_key"]]
        kph = ",".join("?" * len(keys)) or "''"
        titles = {t["key"]: t for t in db.rows(c, f"SELECT * FROM titles WHERE key IN ({kph})", keys)}
        items = []
        for i in ids:
            if i not in sugg:
                items.append({"id": i, "label": "?", "name": "?", "executable": False,
                              "reason": L("The suggestion no longer exists (a new analysis has run).",
                                          "Forslaget finnes ikke lenger (ny analyse er kjørt).")})
                continue
            s = sugg[i]
            items.append(_describe(s, titles.get(s["title_key"])))
        # Season and whole series for the same series: the whole series covers the season
        whole = {it["target"] for it in items if it.get("executable") and it["kind"] == "delete_title"
                 and it["service"] == "sonarr"}
        for it in items:
            if it.get("executable") and it["kind"] == "delete_season" and it["target"] in whole:
                it["executable"], it["reason"] = False, L("Covered by deleting the whole series.",
                                                          "Dekkes av sletting av hele serien.")
        exe = [it["id"] for it in items if it["executable"]]
        sv = engine.selection_savings(c, exe)
        token = _token(items, c)
    return {"enabled": enabled(), "items": items, "executable": len(exe), "freed": sv["freed"],
            "held": sv["held"], "token": token}


# ------------------------------------------------------------------ execute

def _arr(svc: str):
    cfg = settings.get()["services"][svc]
    if not cfg.get("url") or not cfg.get("api_key"):
        raise ActionError(fmt("{svc} is not configured", "{svc} er ikke konfigurert", svc=svc.capitalize()))
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}


def _req(method: str, url: str, headers: dict, **kw) -> httpx.Response:
    svc = "Radarr" if "/movie" in url else "Sonarr" if "/series" in url or "/episode" in url else "Radarr/Sonarr"
    try:
        with httpx.Client(timeout=TIMEOUT) as cl:
            r = cl.request(method, url, headers=headers, **kw)
    except httpx.HTTPError as e:
        raise ActionError(fmt("No connection: {e}", "Ingen kontakt: {e}", e=e)) from e
    if r.status_code == 404:
        raise ActionError(fmt("No longer exists in {svc}", "Finnes ikke lenger i {svc}", svc=svc))
    if r.status_code >= 400:
        raise ActionError(fmt("{svc} answered {code}: {body}", "{svc} svarte {code}: {body}", svc=svc,
                              code=r.status_code, body=r.text[:300]))
    return r


def _same_folder(service_path: str | None, folder: str) -> bool:
    return (settings.map_service_path(service_path) or "").rstrip("/") == (folder or "").rstrip("/")


def _folder_mismatch(svc: str, path: str | None) -> ActionError:
    return ActionError(fmt("The folder in {svc} ({p}) does not match the analysis – run a new refresh first",
                           "Mappen i {svc} ({p}) stemmer ikke med analysen – kjør ny oppdatering først", svc=svc, p=path))


def _do_radarr_movie(it: dict, t: dict) -> dict:
    base, h = _arr("radarr")
    movie = _req("GET", f"{base}/api/v3/movie/{it['target']}", h).json()
    if not _same_folder(movie.get("path"), t["folder"]):
        raise _folder_mismatch("Radarr", movie.get("path"))
    _req("DELETE", f"{base}/api/v3/movie/{it['target']}", h,
         params={"deleteFiles": "true", "addImportExclusion": "false"})
    return fmt("Deleted «{t}» with its files in Radarr", "Slettet «{t}» med filer i Radarr", t=movie.get("title"))


def _do_sonarr_series(it: dict, t: dict) -> dict:
    base, h = _arr("sonarr")
    series = _req("GET", f"{base}/api/v3/series/{it['target']}", h).json()
    if not _same_folder(series.get("path"), t["folder"]):
        raise _folder_mismatch("Sonarr", series.get("path"))
    _req("DELETE", f"{base}/api/v3/series/{it['target']}", h,
         params={"deleteFiles": "true", "addImportListExclusion": "false"})
    return fmt("Deleted the series «{t}» with its files in Sonarr", "Slettet serien «{t}» med filer i Sonarr",
               t=series.get("title"))


def _do_sonarr_season(it: dict, t: dict) -> dict:
    base, h = _arr("sonarr")
    sid, sn = it["target"], it["season"]
    series = _req("GET", f"{base}/api/v3/series/{sid}", h).json()
    if not _same_folder(series.get("path"), t["folder"]):
        raise _folder_mismatch("Sonarr", series.get("path"))
    # 1) Unmonitor the season first, so Sonarr does not fetch it again
    changed = False
    for season in series.get("seasons", []):
        if season.get("seasonNumber") == sn and season.get("monitored"):
            season["monitored"] = False
            changed = True
    if changed:
        _req("PUT", f"{base}/api/v3/series/{sid}", h, json=series)
    # 2) Delete the season's episode files
    files = _req("GET", f"{base}/api/v3/episodefile", h, params={"seriesId": sid}).json()
    ids = [f["id"] for f in files if f.get("seasonNumber") == sn]
    if ids:
        _req("DELETE", f"{base}/api/v3/episodefile/bulk", h, json={"episodeFileIds": ids})
    title = series.get("title")
    return L(f"Season {sn} of «{title}»: " + ("unmonitored, " if changed else "") + f"{len(ids)} episode file(s) deleted in Sonarr",
             f"Sesong {sn} av «{title}»: " + ("avovervåket, " if changed else "") + f"{len(ids)} episodefil(er) slettet i Sonarr")


def execute(ids: list[str], token: str) -> dict:
    if not enabled():
        raise Forbidden(L("Deletion is switched off under Settings → Deletion",
                          "Sletting er slått av under Innstillinger → Sletting"))
    p = plan(ids)
    if p["token"] != token:
        raise Conflict(L("The selection or the analysis has changed since the summary was shown. Open it again.",
                         "Utvalget eller analysen er endret siden oppsummeringen ble vist. Åpne den på nytt."))
    results = []
    with db.conn() as c:
        titles = {t["key"]: t for t in db.rows(c, "SELECT * FROM titles")}
    for it in p["items"]:
        if not it.get("executable"):
            results.append({"id": it["id"], "label": it["label"], "name": it["name"], "status": SKIPPED,
                            "detail": it.get("reason")})
            continue
        t = titles.get(it["title_key"])
        try:
            if t is None or t["protected"]:
                raise ActionError(L("The title is protected or no longer exists", "Tittelen er beskyttet eller finnes ikke lenger"))
            if it["kind"] == "delete_title" and it["service"] == "radarr":
                detail = _do_radarr_movie(it, t)
            elif it["kind"] == "delete_title":
                detail = _do_sonarr_series(it, t)
            else:
                detail = _do_sonarr_season(it, t)
            status = DONE
        except ActionError as e:
            detail, status = e.msg, FAILED
        except ServiceError as e:
            detail, status = str(e), FAILED
        except Exception as e:  # unexpected – log it and continue with the next one
            log.exception("Deletion failed")
            detail, status = f"{type(e).__name__}: {e}", FAILED
        with db.conn() as c:
            log_action(c, title=it["name"], action=it["kind"], service=it.get("service"), status=status, detail=detail,
                       bytes_=it["savings"], suggestion_id=it["id"], title_key=it["title_key"])
        results.append({"id": it["id"], "label": it["label"], "name": it["name"], "status": status, "detail": detail})
    done = [r for r in results if r["status"] == DONE]
    if done:
        jobs.enqueue("refresh")  # update the numbers after deleting
    with db.conn() as c:
        freed = engine.selection_savings(c, [r["id"] for r in done])["freed"] if done else 0
    return {"results": results, "done": len(done), "failed": sum(r["status"] == FAILED for r in results),
            "freed_estimate": freed}


def history(limit: int = 300) -> list[dict]:
    with db.conn() as c:
        return db.rows(c, "SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,))


def init() -> None:
    with db.conn() as c:
        c.executescript(SCHEMA)
        # 1.0: status values in English
        c.execute("UPDATE actions SET status='done' WHERE status='utført'")
        c.execute("UPDATE actions SET status='failed' WHERE status='feilet'")
        c.execute("UPDATE actions SET status='skipped' WHERE status='hoppet over'")
