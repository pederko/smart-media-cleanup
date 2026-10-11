"""Sletting via Radarr og Sonarr (valgfritt, av som standard).

Sikkerhetsmodell:
  * Appen sletter aldri filer selv – mediemappene er skrivebeskyttet. All sletting går via
    Radarr/Sonarr sitt API, slik at de holder oversikten og ikke laster ned igjen.
  * Må slås på under Innstillinger → Sletting.
  * Beskyttede titler (bibliotek, tagger, Plex-etiketter, stier) avvises alltid.
  * To steg: plan (hva skjer, hvor mye frigjøres) og utførelse. Utførelsen krever planens
    token, så det som utføres er nøyaktig det som ble vist – ikke en nyere analyse.
  * Rett før hver sletting hentes tittelen på nytt fra Radarr/Sonarr og sammenlignes med
    analysen (finnes fortsatt, samme mappe). Avvik stopper den enkelte slettingen.
  * Hver handling loggføres i tabellen `actions` og i `audit`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time

import httpx

from . import db, jobs, settings
from .analysis import engine
from .clients.base import ServiceError

log = logging.getLogger("smc.actions")
TIMEOUT = httpx.Timeout(180.0, connect=10.0)  # indekssøk i Radarr/Sonarr kan ta lang tid

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, suggestion_id TEXT,
  title_key TEXT, title TEXT, action TEXT, service TEXT, status TEXT, detail TEXT, bytes INTEGER);
"""


class ActionError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.get().get("actions", {}).get("enabled", False))


# ------------------------------------------------------------------ plan

def _describe(s: dict, t: dict | None) -> dict:
    """Hva kan gjøres med dette forslaget, og hvordan."""
    base = {"id": s["id"], "label": s["label"], "location": s["location"], "kind": s["kind"],
            "risk": s["risk"], "savings": s["savings"], "title_key": s["title_key"]}
    if t is None:
        return {**base, "executable": False, "reason": "Ikke knyttet til Radarr/Sonarr – gjøres manuelt."}
    if t["protected"]:
        return {**base, "executable": False, "reason": f"Beskyttet: {t['protect_reason']}"}
    if s["kind"] == "delete_title" and t["radarr_id"] is not None:
        return {**base, "executable": True, "service": "radarr", "target": t["radarr_id"],
                "how": "Slettes i Radarr med filer. Filmen fjernes fra Radarr."}
    if s["kind"] == "delete_title" and t["sonarr_id"] is not None:
        return {**base, "executable": True, "service": "sonarr", "target": t["sonarr_id"],
                "how": "Slettes i Sonarr med filer. Serien fjernes fra Sonarr."}
    if s["kind"] == "delete_season" and t["sonarr_id"] is not None:
        season = int(s["scope"].split(":", 1)[1])
        return {**base, "executable": True, "service": "sonarr", "target": t["sonarr_id"], "season": season,
                "how": f"Sesong {season} avovervåkes i Sonarr, deretter slettes episodefilene."}
    reasons = {
        "replace": "Erstatning gjøres ved å endre kvalitetsprofil i Radarr/Sonarr.",
        "remove_versions": "Ekstra versjoner er ikke administrert av Radarr/Sonarr – fjernes manuelt.",
        "remove_copy": "Identiske kopier er ikke administrert av Radarr/Sonarr – fjernes manuelt.",
        "download": "Nedlastinger fjernes i qBittorrent.",
    }
    return {**base, "executable": False,
            "reason": reasons.get(s["kind"], "Ikke administrert av Radarr/Sonarr – gjøres manuelt.")}


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
                items.append({"id": i, "label": "?", "executable": False,
                              "reason": "Forslaget finnes ikke lenger (ny analyse er kjørt)."})
                continue
            s = sugg[i]
            items.append(_describe(s, titles.get(s["title_key"])))
        # Sesong og hel serie for samme serie: hel serie dekker sesongen
        whole = {it["target"] for it in items if it.get("executable") and it["kind"] == "delete_title"
                 and it["service"] == "sonarr"}
        for it in items:
            if it.get("executable") and it["kind"] == "delete_season" and it["target"] in whole:
                it["executable"], it["reason"] = False, "Dekkes av sletting av hele serien."
        exe = [it["id"] for it in items if it["executable"]]
        sv = engine.selection_savings(c, exe)
        token = _token(items, c)
    return {"enabled": enabled(), "items": items, "executable": len(exe), "freed": sv["freed"],
            "held": sv["held"], "token": token}


# ------------------------------------------------------------------ utførelse

def _arr(svc: str):
    cfg = settings.get()["services"][svc]
    if not cfg.get("url") or not cfg.get("api_key"):
        raise ActionError(f"{svc} er ikke konfigurert")
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}


def _req(method: str, url: str, headers: dict, **kw) -> httpx.Response:
    try:
        with httpx.Client(timeout=TIMEOUT) as cl:
            r = cl.request(method, url, headers=headers, **kw)
    except httpx.HTTPError as e:
        raise ActionError(f"Ingen kontakt: {e}") from e
    if r.status_code == 404:
        raise ActionError("Finnes ikke lenger i " + ("Radarr" if "/movie" in url else "Sonarr"))
    if r.status_code >= 400:
        raise ActionError(f"{r.status_code}: {r.text[:300]}")
    return r


def _same_folder(service_path: str | None, folder: str) -> bool:
    return (settings.map_service_path(service_path) or "").rstrip("/") == (folder or "").rstrip("/")


def _do_radarr_movie(it: dict, t: dict) -> str:
    base, h = _arr("radarr")
    movie = _req("GET", f"{base}/api/v3/movie/{it['target']}", h).json()
    if not _same_folder(movie.get("path"), t["folder"]):
        raise ActionError(f"Mappen i Radarr ({movie.get('path')}) stemmer ikke med analysen – kjør ny oppdatering først")
    _req("DELETE", f"{base}/api/v3/movie/{it['target']}", h,
         params={"deleteFiles": "true", "addImportExclusion": "false"})
    return f"Slettet «{movie.get('title')}» med filer i Radarr"


def _do_sonarr_series(it: dict, t: dict) -> str:
    base, h = _arr("sonarr")
    series = _req("GET", f"{base}/api/v3/series/{it['target']}", h).json()
    if not _same_folder(series.get("path"), t["folder"]):
        raise ActionError(f"Mappen i Sonarr ({series.get('path')}) stemmer ikke med analysen – kjør ny oppdatering først")
    _req("DELETE", f"{base}/api/v3/series/{it['target']}", h,
         params={"deleteFiles": "true", "addImportListExclusion": "false"})
    return f"Slettet serien «{series.get('title')}» med filer i Sonarr"


def _do_sonarr_season(it: dict, t: dict) -> str:
    base, h = _arr("sonarr")
    sid, sn = it["target"], it["season"]
    series = _req("GET", f"{base}/api/v3/series/{sid}", h).json()
    if not _same_folder(series.get("path"), t["folder"]):
        raise ActionError(f"Mappen i Sonarr ({series.get('path')}) stemmer ikke med analysen – kjør ny oppdatering først")
    # 1) Avovervåk sesongen først, så Sonarr ikke henter den igjen
    changed = False
    for season in series.get("seasons", []):
        if season.get("seasonNumber") == sn and season.get("monitored"):
            season["monitored"] = False
            changed = True
    if changed:
        _req("PUT", f"{base}/api/v3/series/{sid}", h, json=series)
    # 2) Slett sesongens episodefiler
    files = _req("GET", f"{base}/api/v3/episodefile", h, params={"seriesId": sid}).json()
    ids = [f["id"] for f in files if f.get("seasonNumber") == sn]
    if ids:
        _req("DELETE", f"{base}/api/v3/episodefile/bulk", h, json={"episodeFileIds": ids})
    return (f"Sesong {sn} av «{series.get('title')}»: " + ("avovervåket, " if changed else "") +
            f"{len(ids)} episodefil(er) slettet i Sonarr")


def execute(ids: list[str], token: str) -> dict:
    if not enabled():
        raise PermissionError("Sletting er slått av under Innstillinger")
    p = plan(ids)
    if p["token"] != token:
        raise ValueError("Utvalget eller analysen er endret siden oppsummeringen ble vist. Åpne oppsummeringen på nytt.")
    results = []
    with db.conn() as c:
        titles = {t["key"]: t for t in db.rows(c, "SELECT * FROM titles")}
    for it in p["items"]:
        if not it.get("executable"):
            results.append({"id": it["id"], "label": it["label"], "status": "hoppet over", "detail": it.get("reason")})
            continue
        t = titles.get(it["title_key"])
        try:
            if t is None or t["protected"]:
                raise ActionError("Tittelen er beskyttet eller finnes ikke lenger")
            if it["kind"] == "delete_title" and it["service"] == "radarr":
                detail = _do_radarr_movie(it, t)
            elif it["kind"] == "delete_title":
                detail = _do_sonarr_series(it, t)
            else:
                detail = _do_sonarr_season(it, t)
            status = "utført"
        except (ActionError, ServiceError) as e:
            detail, status = str(e), "feilet"
        except Exception as e:  # uventet – loggfør og fortsett med neste
            log.exception("Sletting feilet")
            detail, status = f"{type(e).__name__}: {e}", "feilet"
        with db.conn() as c:
            c.execute("INSERT INTO actions(ts,suggestion_id,title_key,title,action,service,status,detail,bytes) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (time.time(), it["id"], it["title_key"], it["label"], it["kind"], it.get("service"),
                       status, detail, it["savings"] if status == "utført" else 0))
            db.audit(c, "delete", {"suggestion": it["id"], "title": it["label"], "status": status, "detail": detail})
        results.append({"id": it["id"], "label": it["label"], "status": status, "detail": detail})
    done = [r for r in results if r["status"] == "utført"]
    if done:
        jobs.enqueue("refresh")  # oppdater tallene etter slettingen
    with db.conn() as c:
        freed = engine.selection_savings(c, [r["id"] for r in done])["freed"] if done else 0
    return {"results": results, "done": len(done), "failed": sum(r["status"] == "feilet" for r in results),
            "freed_estimate": freed}


def history(limit: int = 200) -> list[dict]:
    with db.conn() as c:
        return db.rows(c, "SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,))


def init() -> None:
    with db.conn() as c:
        c.executescript(SCHEMA)


__all__ = ["plan", "execute", "history", "enabled", "init", "json"]
