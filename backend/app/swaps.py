"""Bytt til en mindre versjon – «last ned først, bytt etterpå».

1. start():  Radarr/Sonarr henter valgt utgivelse (POST /release). Den store filen blir liggende.
2. poll():   følger nedlastingskøen. Når nedlastingen er ferdig og bare venter fordi den «ikke er en
             oppgradering», hentes manuell import-forslag for nedlastingen. Har filene ingen andre
             avvisninger enn «ikke en oppgradering», slettes den gamle filen via Radarr/Sonarr og den
             nye importeres (ManualImport). Ellers stopper byttet med en forklaring – ingenting slettes.
3. Etterpå (valgfritt): avovervåk tittelen eller bytt kvalitetsprofil, så Radarr/Sonarr ikke
   «oppgraderer» tilbake.

Tilstander: venter → laster_ned → klar → importerer → ferdig | feilet | trenger_hjelp | avbrutt
"""
from __future__ import annotations

import json
import logging
import re
import time

from . import db, settings
from .actions import ActionError, _arr, _req, enabled as actions_enabled

log = logging.getLogger("smc.swaps")
UPGRADE_REJECTION = re.compile(r"upgrade|preference|cutoff|existing file|not wanted in .*profile", re.I)
ACTIVE = ("venter", "laster_ned", "klar", "importerer")

SCHEMA = """
CREATE TABLE IF NOT EXISTS swaps(id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, updated REAL, title_key TEXT,
  title TEXT, service TEXT, arr_id INTEGER, season INTEGER, release_title TEXT, guid TEXT, indexer_id INTEGER,
  release_size INTEGER, old_size INTEGER, after_swap TEXT, state TEXT, message TEXT, download_id TEXT,
  progress REAL, log TEXT);
"""


def init() -> None:
    with db.conn() as c:
        c.executescript(SCHEMA)


def _log(c, sid: int, state: str, message: str, **extra) -> None:
    row = c.execute("SELECT log FROM swaps WHERE id=?", (sid,)).fetchone()
    entries = json.loads(row[0] or "[]") if row else []
    entries.append({"ts": time.time(), "state": state, "message": message})
    sets = {"state": state, "message": message, "updated": time.time(), "log": json.dumps(entries[-50:], ensure_ascii=False), **extra}
    c.execute(f"UPDATE swaps SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", [*sets.values(), sid])
    db.audit(c, "swap", {"id": sid, "state": state, "message": message})


def quality_profiles(service: str) -> list[dict]:
    base, h = _arr(service)
    return [{"id": p["id"], "name": p["name"]} for p in _req("GET", f"{base}/api/v3/qualityprofile", h).json()]


def start(key: str, guid: str, indexer_id: int, season: int | None = None, after_swap: str = "none") -> dict:
    if not actions_enabled():
        raise PermissionError("Bytte krever at sletting via Radarr/Sonarr er slått på under Innstillinger → Sletting")
    from .releases import search  # gjenbruk cachet søk for å finne utgivelsen
    with db.conn() as c:
        t = db.rows(c, "SELECT * FROM titles WHERE key=?", (key,))
        if not t:
            raise ActionError("Fant ikke tittelen")
        t = t[0]
        if t["protected"]:
            raise ActionError(f"Tittelen er beskyttet: {t['protect_reason']}")
        busy = c.execute(f"SELECT id FROM swaps WHERE title_key=? AND IFNULL(season,-1)=? AND state IN ({','.join('?' * len(ACTIVE))})",
                         (key, -1 if season is None else season, *ACTIVE)).fetchone()
        if busy:
            raise ActionError("Det pågår allerede et bytte for denne tittelen")
    res = search(key, season)
    rel = next((r for r in res["releases"] if r["guid"] == guid and r["indexer_id"] == indexer_id), None)
    if not rel:
        raise ActionError("Fant ikke utgivelsen i siste søk – søk på nytt")
    service = res["service"]
    arr_id = t["radarr_id"] if service == "radarr" else t["sonarr_id"]
    base, h = _arr(service)
    _req("POST", f"{base}/api/v3/release", h, json={"guid": guid, "indexerId": indexer_id})
    with db.conn() as c:
        sid = c.execute("""INSERT INTO swaps(created,updated,title_key,title,service,arr_id,season,release_title,guid,
                           indexer_id,release_size,old_size,after_swap,state,message,progress,log)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (time.time(), time.time(), key, t["name"], service, arr_id, season, rel["title"], guid, indexer_id,
                         rel["size"], res["current_size"], after_swap, "venter",
                         f"Sendt til {'Radarr' if service == 'radarr' else 'Sonarr'} – venter på at nedlastingen starter", 0, "[]")).lastrowid
        _log(c, sid, "venter", f"Utgivelsen «{rel['title']}» er sendt til nedlasting. Den store filen blir liggende til byttet.")
    return get(sid)


def get(sid: int) -> dict:
    with db.conn() as c:
        r = db.rows(c, "SELECT * FROM swaps WHERE id=?", (sid,))
    if not r:
        raise ActionError("Fant ikke byttet")
    r = r[0]
    r["log"] = json.loads(r["log"] or "[]")
    return r


def list_swaps(key: str | None = None) -> list[dict]:
    with db.conn() as c:
        rows = db.rows(c, "SELECT * FROM swaps" + (" WHERE title_key=?" if key else "") + " ORDER BY id DESC LIMIT 100",
                       (key,) if key else ())
    for r in rows:
        r["log"] = json.loads(r["log"] or "[]")
    return rows


def cancel(sid: int) -> dict:
    with db.conn() as c:
        _log(c, sid, "avbrutt", "Avbrutt i appen. Nedlastingen kan fortsatt ligge i køen i Radarr/Sonarr – fjern den der om ønskelig.")
    return get(sid)


# ------------------------------------------------------------------ oppfølging

def _queue_item(service: str, base: str, h: dict, sw: dict) -> dict | None:
    params = {"movieId": sw["arr_id"]} if service == "radarr" else {"seriesId": sw["arr_id"]}
    items = _req("GET", f"{base}/api/v3/queue/details", h, params=params).json()
    if sw["download_id"]:
        hit = next((i for i in items if i.get("downloadId") == sw["download_id"]), None)
        if hit:
            return hit
    return next((i for i in items if (i.get("title") or "").lower() == (sw["release_title"] or "").lower()), None)


def _messages(item: dict) -> list[str]:
    out = []
    for m in item.get("statusMessages") or []:
        out += m.get("messages") or []
        if m.get("title") and not m.get("messages"):
            out.append(m["title"])
    return out


def _after(service: str, base: str, h: dict, sw: dict) -> str:
    action = sw["after_swap"] or "none"
    if action == "none":
        return ""
    path = "movie" if service == "radarr" else "series"
    obj = _req("GET", f"{base}/api/v3/{path}/{sw['arr_id']}", h).json()
    if action == "unmonitor":
        if service == "sonarr" and sw["season"] is not None:
            for s in obj.get("seasons", []):
                if s.get("seasonNumber") == sw["season"]:
                    s["monitored"] = False
            note = f"Sesong {sw['season']} er avovervåket"
        else:
            obj["monitored"] = False
            note = "Avovervåket"
    elif action.startswith("profile:"):
        obj["qualityProfileId"] = int(action.split(":", 1)[1])
        note = "Kvalitetsprofil endret"
    else:
        return ""
    _req("PUT", f"{base}/api/v3/{path}/{sw['arr_id']}", h, json=obj)
    return f" {note}, så det ikke byttes tilbake."


def _swap_now(service: str, base: str, h: dict, sw: dict, download_id: str) -> str:
    """Kalles når nedlastingen er ferdig. Sjekker import-forslag, sletter gammel fil, importerer ny."""
    params = {"downloadId": download_id, "filterExistingFiles": "false"}
    params["movieId" if service == "radarr" else "seriesId"] = sw["arr_id"]
    proposals = _req("GET", f"{base}/api/v3/manualimport", h, params=params).json()
    if service == "sonarr" and sw["season"] is not None:
        proposals = [p for p in proposals if (p.get("seasonNumber") == sw["season"]) or
                     any(e.get("seasonNumber") == sw["season"] for e in p.get("episodes") or [])]
    if not proposals:
        raise _NeedsHelp("Fant ingen filer å importere i nedlastingen")
    blocking = []
    for p in proposals:
        for r in p.get("rejections") or []:
            reason = r.get("reason") if isinstance(r, dict) else str(r)
            if not UPGRADE_REJECTION.search(reason or ""):
                blocking.append(f"{p.get('name') or p.get('path')}: {reason}")
    if blocking:
        raise _NeedsHelp("Nedlastingen kan ikke importeres automatisk: " + "; ".join(blocking[:3]))

    # 1) slett gammel fil(er) via Radarr/Sonarr
    if service == "radarr":
        for mf in _req("GET", f"{base}/api/v3/moviefile", h, params={"movieId": sw["arr_id"]}).json():
            _req("DELETE", f"{base}/api/v3/moviefile/{mf['id']}", h)
        files = [{"path": p["path"], "movieId": sw["arr_id"], "quality": p.get("quality"), "languages": p.get("languages") or [],
                  "releaseGroup": p.get("releaseGroup"), "downloadId": download_id, "indexerFlags": p.get("indexerFlags", 0)}
                 for p in proposals]
    else:
        old = [f["id"] for f in _req("GET", f"{base}/api/v3/episodefile", h, params={"seriesId": sw["arr_id"]}).json()
               if f.get("seasonNumber") == sw["season"]]
        if old:
            _req("DELETE", f"{base}/api/v3/episodefile/bulk", h, json={"episodeFileIds": old})
        files = [{"path": p["path"], "seriesId": sw["arr_id"], "seasonNumber": sw["season"],
                  "episodeIds": [e["id"] for e in p.get("episodes") or []], "quality": p.get("quality"),
                  "languages": p.get("languages") or [], "releaseGroup": p.get("releaseGroup"), "downloadId": download_id}
                 for p in proposals]
    # 2) importer den nye
    _req("POST", f"{base}/api/v3/command", h, json={"name": "ManualImport", "importMode": "auto", "files": files})
    return f"Gammel fil slettet og {len(files)} ny(e) fil(er) sendt til import."


class _NeedsHelp(Exception):
    pass


def poll(sid: int | None = None) -> list[dict]:
    """Følger opp aktive bytter. Trygg å kalle ofte."""
    with db.conn() as c:
        q = f"SELECT * FROM swaps WHERE state IN ({','.join('?' * len(ACTIVE))})" + (" AND id=?" if sid else "")
        active = db.rows(c, q, (*ACTIVE, sid) if sid else ACTIVE)
    for sw in active:
        service = sw["service"]
        name = "Radarr" if service == "radarr" else "Sonarr"
        try:
            base, h = _arr(service)
            if sw["state"] == "importerer":
                # ferdig når Radarr/Sonarr har en fil igjen og køelementet er borte
                item = _queue_item(service, base, h, sw)
                if service == "radarr":
                    mv = _req("GET", f"{base}/api/v3/movie/{sw['arr_id']}", h).json()
                    has_file = bool(mv.get("hasFile"))
                else:
                    files = _req("GET", f"{base}/api/v3/episodefile", h, params={"seriesId": sw["arr_id"]}).json()
                    has_file = any(f.get("seasonNumber") == sw["season"] for f in files)
                if has_file and not item:
                    note = _after(service, base, h, sw)
                    with db.conn() as c:
                        _log(c, sw["id"], "ferdig", f"Byttet er fullført i {name}.{note}", progress=1.0)
                elif time.time() - sw["updated"] > 3600:
                    with db.conn() as c:
                        _log(c, sw["id"], "trenger_hjelp", f"Importen er ikke bekreftet etter en time. Sjekk Activity → Queue i {name}.")
                continue
            item = _queue_item(service, base, h, sw)
            if not item:
                if sw["state"] == "venter" and time.time() - sw["created"] > 900:
                    with db.conn() as c:
                        _log(c, sw["id"], "feilet", f"Nedlastingen dukket aldri opp i køen i {name}. Den store filen er ikke rørt.")
                continue
            dl_id = item.get("downloadId")
            size, left = item.get("size") or 0, item.get("sizeleft") or 0
            progress = (1 - left / size) if size else 0
            tstate = (item.get("trackedDownloadState") or "").lower()
            tstatus = (item.get("trackedDownloadStatus") or "").lower()
            msgs = _messages(item)
            if tstate in ("failed", "failedpending") or (item.get("status") or "").lower() in ("failed", "warning") and tstatus == "error":
                with db.conn() as c:
                    _log(c, sw["id"], "feilet", f"Nedlastingen feilet i {name}: {'; '.join(msgs) or item.get('errorMessage') or 'ukjent'}. Den store filen er ikke rørt.",
                         download_id=dl_id)
            elif tstate in ("importpending", "importblocked") or (item.get("status") or "").lower() == "completed":
                if tstate == "importing":
                    continue
                with db.conn() as c:
                    _log(c, sw["id"], "klar", "Nedlastingen er ferdig – kontrollerer filene før byttet", download_id=dl_id, progress=1.0)
                try:
                    detail = _swap_now(service, base, h, sw, dl_id)
                    with db.conn() as c:
                        _log(c, sw["id"], "importerer", detail)
                except _NeedsHelp as e:
                    with db.conn() as c:
                        _log(c, sw["id"], "trenger_hjelp", f"{e}. Den store filen er ikke rørt – importer manuelt i {name} (Activity → Queue).")
            elif tstate == "imported":
                note = _after(service, base, h, sw)
                with db.conn() as c:
                    _log(c, sw["id"], "ferdig", f"{name} importerte den nye filen selv.{note}", progress=1.0)
            else:
                if sw["state"] != "laster_ned" or abs((sw["progress"] or 0) - progress) > 0.05:
                    with db.conn() as c:
                        _log(c, sw["id"], "laster_ned", f"Laster ned ({progress * 100:.0f} %)", download_id=dl_id, progress=round(progress, 3))
        except (ActionError, Exception) as e:  # nettverk o.l. – prøv igjen ved neste oppfølging
            log.warning("Bytte %s: %s", sw["id"], e)
            with db.conn() as c:
                c.execute("UPDATE swaps SET message=?, updated=updated WHERE id=?", (f"Midlertidig feil: {e} (prøver igjen)", sw["id"]))
    return list_swaps()
