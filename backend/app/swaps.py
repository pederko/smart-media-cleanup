"""Swap to a smaller version – «download first, swap afterwards».

1. start():  Radarr/Sonarr grabs the chosen release (POST /release). The large file stays.
2. poll():   follows the download queue. When the download is finished and only waits because it is
             «not an upgrade», the manual import proposals for the download are fetched. If the files
             have no rejections other than «not an upgrade», the old file is deleted through
             Radarr/Sonarr and the new one is imported (ManualImport). Otherwise the swap stops with
             an explanation – nothing is deleted.
3. Afterwards (optional): unmonitor the title or change the quality profile, so Radarr/Sonarr do
   not «upgrade» back.

States: waiting → downloading → ready → importing → done | failed | needs_help | cancelled
"""
from __future__ import annotations

import json
import logging
import re
import time

from .clients import arr
from . import db
from .actions import _arr, _req, enabled as actions_enabled
from .i18n import L, ActionError, Forbidden, fmt, store

log = logging.getLogger("smc.swaps")
UPGRADE_REJECTION = re.compile(r"upgrade|preference|cutoff|existing file|not wanted in .*profile", re.I)
ACTIVE = ("waiting", "downloading", "ready", "importing")
LEGACY_STATES = {"venter": "waiting", "laster_ned": "downloading", "klar": "ready", "importerer": "importing",
                 "ferdig": "done", "feilet": "failed", "trenger_hjelp": "needs_help", "avbrutt": "cancelled"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS swaps(id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, updated REAL, title_key TEXT,
  title TEXT, service TEXT, arr_id INTEGER, season INTEGER, release_title TEXT, guid TEXT, indexer_id INTEGER,
  release_size INTEGER, old_size INTEGER, after_swap TEXT, state TEXT, message TEXT, download_id TEXT,
  progress REAL, log TEXT);
"""


def init() -> None:
    with db.conn() as c:
        c.executescript(SCHEMA)
        for old, new in LEGACY_STATES.items():  # 1.0: state values in English
            c.execute("UPDATE swaps SET state=? WHERE state=?", (new, old))


def _svc(service: str) -> str:
    return "Radarr" if service == "radarr" else "Sonarr"


def _log(c, sid: int, state: str, message, **extra) -> None:
    row = c.execute("SELECT log FROM swaps WHERE id=?", (sid,)).fetchone()
    entries = json.loads(row[0] or "[]") if row else []
    entries.append({"ts": time.time(), "state": state, "message": message})
    sets = {"state": state, "message": store(message), "updated": time.time(),
            "log": json.dumps(entries[-50:], ensure_ascii=False), **extra}
    c.execute(f"UPDATE swaps SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", [*sets.values(), sid])
    db.audit(c, "swap", {"id": sid, "state": state, "message": message})


def quality_profiles(service: str) -> list[dict]:
    base, h = _arr(service)
    return [{"id": p["id"], "name": p["name"]} for p in _req("GET", f"{base}/api/v3/qualityprofile", h).json()]


def start(key: str, guid: str, indexer_id: int, season: int | None = None, after_swap: str = "none") -> dict:
    if not actions_enabled():
        raise Forbidden(L("Swapping requires deletion through Radarr/Sonarr to be switched on under Settings → Deletion",
                          "Bytte krever at sletting via Radarr/Sonarr er slått på under Innstillinger → Sletting"))
    from .releases import search  # reuse the cached search to find the release
    with db.conn() as c:
        t = db.rows(c, "SELECT * FROM titles WHERE key=?", (key,))
        if not t:
            raise ActionError(L("Title not found", "Fant ikke tittelen"))
        t = t[0]
        if t["protected"]:
            raise ActionError(fmt("The title is protected: {r}", "Tittelen er beskyttet: {r}", r=t["protect_reason"]))
        busy = c.execute(f"SELECT id FROM swaps WHERE title_key=? AND IFNULL(season,-1)=? AND state IN ({','.join('?' * len(ACTIVE))})",
                         (key, -1 if season is None else season, *ACTIVE)).fetchone()
        if busy:
            raise ActionError(L("A swap is already in progress for this title", "Det pågår allerede et bytte for denne tittelen"))
    res = search(key, season)
    rel = next((r for r in res["releases"] if r["guid"] == guid and r["indexer_id"] == indexer_id), None)
    if not rel:
        raise ActionError(L("The release is not in the latest search – search again",
                            "Fant ikke utgivelsen i siste søk – søk på nytt"))
    service = res["service"]
    arr_id = t["radarr_id"] if service == "radarr" else t["sonarr_id"]
    base, h = _arr(service)
    _req("POST", f"{base}/api/v3/release", h, json={"guid": guid, "indexerId": indexer_id})
    with db.conn() as c:
        sid = c.execute("""INSERT INTO swaps(created,updated,title_key,title,service,arr_id,season,release_title,guid,
                           indexer_id,release_size,old_size,after_swap,state,message,progress,log)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (time.time(), time.time(), key, t["name"], service, arr_id, season, rel["title"], guid, indexer_id,
                         rel["size"], res["current_size"], after_swap, "waiting", "", 0, "[]")).lastrowid
        _log(c, sid, "waiting", fmt("The release «{r}» was sent to {svc} for download. The large file stays until the swap.",
                                    "Utgivelsen «{r}» er sendt til {svc} for nedlasting. Den store filen blir liggende til byttet.",
                                    r=rel["title"], svc=_svc(service)))
    return get(sid)


def get(sid: int) -> dict:
    with db.conn() as c:
        r = db.rows(c, "SELECT * FROM swaps WHERE id=?", (sid,))
    if not r:
        raise ActionError(L("Swap not found", "Fant ikke byttet"))
    r = r[0]
    r["log"] = json.loads(r["log"] or "[]")
    return r


def list_swaps(key: str | None = None, limit: int = 100) -> list[dict]:
    with db.conn() as c:
        rows = db.rows(c, "SELECT * FROM swaps" + (" WHERE title_key=?" if key else "") + " ORDER BY id DESC LIMIT ?",
                       (key, limit) if key else (limit,))
    for r in rows:
        r["log"] = json.loads(r["log"] or "[]")
    return rows


def cancel(sid: int) -> dict:
    with db.conn() as c:
        _log(c, sid, "cancelled", L("Cancelled in the app. The download may still be in the Radarr/Sonarr queue – remove it there if you like.",
                                    "Avbrutt i appen. Nedlastingen kan fortsatt ligge i køen i Radarr/Sonarr – fjern den der om ønskelig."))
    return get(sid)


# ------------------------------------------------------------------ follow-up

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


def _after(service: str, base: str, h: dict, sw: dict) -> dict | None:
    action = sw["after_swap"] or "none"
    if action == "none":
        return None
    path = "movie" if service == "radarr" else "series"
    obj = _req("GET", f"{base}/api/v3/{path}/{sw['arr_id']}", h).json()
    if action == "unmonitor":
        if service == "sonarr" and sw["season"] is not None:
            for s in obj.get("seasons", []):
                if s.get("seasonNumber") == sw["season"]:
                    s["monitored"] = False
            note = L(f"Season {sw['season']} is unmonitored", f"Sesong {sw['season']} er avovervåket")
        else:
            obj["monitored"] = False
            note = L("Unmonitored", "Avovervåket")
    elif action.startswith("profile:"):
        obj["qualityProfileId"] = int(action.split(":", 1)[1])
        note = L("Quality profile changed", "Kvalitetsprofil endret")
    else:
        return None
    _req("PUT", f"{base}/api/v3/{path}/{sw['arr_id']}", h, json=obj)
    return fmt("{n}, so it is not swapped back.", "{n}, så det ikke byttes tilbake.", n=note)


class _NeedsHelp(Exception):
    def __init__(self, msg):
        super().__init__(str(msg))
        self.msg = msg


def _swap_now(service: str, base: str, h: dict, sw: dict, download_id: str) -> dict:
    """Called when the download is finished. Checks the import proposals, deletes the old file, imports the new one."""
    params = {"downloadId": download_id, "filterExistingFiles": "false"}
    params["movieId" if service == "radarr" else "seriesId"] = sw["arr_id"]
    proposals = _req("GET", f"{base}/api/v3/manualimport", h, params=params).json()
    if service == "sonarr" and sw["season"] is not None:
        proposals = [p for p in proposals if (p.get("seasonNumber") == sw["season"]) or
                     any(e.get("seasonNumber") == sw["season"] for e in p.get("episodes") or [])]
    if not proposals:
        raise _NeedsHelp(L("Found no files to import in the download", "Fant ingen filer å importere i nedlastingen"))
    blocking = []
    for p in proposals:
        for r in p.get("rejections") or []:
            reason = r.get("reason") if isinstance(r, dict) else str(r)
            if not UPGRADE_REJECTION.search(reason or ""):
                blocking.append(f"{p.get('name') or p.get('path')}: {reason}")
    if blocking:
        joined = "; ".join(blocking[:3])
        raise _NeedsHelp(L(f"The download cannot be imported automatically: {joined}",
                           f"Nedlastingen kan ikke importeres automatisk: {joined}"))

    # 1) delete the old file(s) through Radarr/Sonarr
    if service == "radarr":
        for mf in _req("GET", f"{base}/api/v3/moviefile", h, params={"movieId": sw["arr_id"]}).json():
            _req("DELETE", f"{base}/api/v3/moviefile/{mf['id']}", h)
        files = [{"path": p["path"], "movieId": sw["arr_id"], "quality": p.get("quality"), "languages": p.get("languages") or [],
                  "releaseGroup": p.get("releaseGroup"), "downloadId": download_id, "indexerFlags": p.get("indexerFlags", 0)}
                 for p in proposals]
    else:
        old = [f["id"] for f in (arr.episode_files(base, h, sw["arr_id"]) or [])
               if f.get("seasonNumber") == sw["season"]]
        if old:
            _req("DELETE", f"{base}/api/v3/episodefile/bulk", h, json={"episodeFileIds": old})
        files = [{"path": p["path"], "seriesId": sw["arr_id"], "seasonNumber": sw["season"],
                  "episodeIds": [e["id"] for e in p.get("episodes") or []], "quality": p.get("quality"),
                  "languages": p.get("languages") or [], "releaseGroup": p.get("releaseGroup"), "downloadId": download_id}
                 for p in proposals]
    # 2) import the new one
    _req("POST", f"{base}/api/v3/command", h, json={"name": "ManualImport", "importMode": "auto", "files": files})
    return fmt("Old file deleted and {n} new file(s) sent to import.", "Gammel fil slettet og {n} ny(e) fil(er) sendt til import.",
               n=len(files))


def poll(sid: int | None = None) -> list[dict]:
    """Follows up active swaps. Safe to call often."""
    with db.conn() as c:
        q = f"SELECT * FROM swaps WHERE state IN ({','.join('?' * len(ACTIVE))})" + (" AND id=?" if sid else "")
        active = db.rows(c, q, (*ACTIVE, sid) if sid else ACTIVE)
    for sw in active:
        service = sw["service"]
        name = _svc(service)
        try:
            base, h = _arr(service)
            if sw["state"] == "importing":
                # done when Radarr/Sonarr has a file again and the queue item is gone
                item = _queue_item(service, base, h, sw)
                if service == "radarr":
                    mv = _req("GET", f"{base}/api/v3/movie/{sw['arr_id']}", h).json()
                    has_file = bool(mv.get("hasFile"))
                else:
                    files = (arr.episode_files(base, h, sw["arr_id"]) or [])
                    has_file = any(f.get("seasonNumber") == sw["season"] for f in files)
                if has_file and not item:
                    note = _after(service, base, h, sw)
                    msg = fmt("The swap is complete in {svc}.", "Byttet er fullført i {svc}.", svc=name)
                    with db.conn() as c:
                        _log(c, sw["id"], "done", fmt("{a} {b}", "{a} {b}", a=msg, b=note) if note else msg, progress=1.0)
                elif time.time() - sw["updated"] > 3600:
                    with db.conn() as c:
                        _log(c, sw["id"], "needs_help", fmt("The import has not been confirmed after an hour. Check Activity → Queue in {svc}.",
                                                            "Importen er ikke bekreftet etter en time. Sjekk Activity → Queue i {svc}.", svc=name))
                continue
            item = _queue_item(service, base, h, sw)
            if not item:
                if sw["state"] == "waiting" and time.time() - sw["created"] > 900:
                    with db.conn() as c:
                        _log(c, sw["id"], "failed", fmt("The download never appeared in the {svc} queue. The large file has not been touched.",
                                                        "Nedlastingen dukket aldri opp i køen i {svc}. Den store filen er ikke rørt.", svc=name))
                continue
            dl_id = item.get("downloadId")
            size, left = item.get("size") or 0, item.get("sizeleft") or 0
            progress = (1 - left / size) if size else 0
            tstate = (item.get("trackedDownloadState") or "").lower()
            tstatus = (item.get("trackedDownloadStatus") or "").lower()
            qstatus = (item.get("status") or "").lower()
            msgs = _messages(item)
            if tstate in ("failed", "failedpending") or (qstatus in ("failed", "warning") and tstatus == "error"):
                why = "; ".join(msgs) or item.get("errorMessage") or "?"
                with db.conn() as c:
                    _log(c, sw["id"], "failed", fmt("The download failed in {svc}: {why}. The large file has not been touched.",
                                                    "Nedlastingen feilet i {svc}: {why}. Den store filen er ikke rørt.", svc=name, why=why),
                         download_id=dl_id)
            elif tstate == "importing":
                continue
            elif tstate in ("importpending", "importblocked") or qstatus == "completed":
                with db.conn() as c:
                    _log(c, sw["id"], "ready", L("The download is finished – checking the files before swapping",
                                                 "Nedlastingen er ferdig – kontrollerer filene før byttet"), download_id=dl_id, progress=1.0)
                try:
                    detail = _swap_now(service, base, h, sw, dl_id)
                    with db.conn() as c:
                        _log(c, sw["id"], "importing", detail)
                except _NeedsHelp as e:
                    with db.conn() as c:
                        _log(c, sw["id"], "needs_help",
                             fmt("{e}. The large file has not been touched – import manually in {svc} (Activity → Queue).",
                                 "{e}. Den store filen er ikke rørt – importer manuelt i {svc} (Activity → Queue).", e=e.msg, svc=name))
            elif tstate == "imported":
                note = _after(service, base, h, sw)
                msg = fmt("{svc} imported the new file itself.", "{svc} importerte den nye filen selv.", svc=name)
                with db.conn() as c:
                    _log(c, sw["id"], "done", fmt("{a} {b}", "{a} {b}", a=msg, b=note) if note else msg, progress=1.0)
            else:
                if sw["state"] != "downloading" or abs((sw["progress"] or 0) - progress) > 0.05:
                    with db.conn() as c:
                        _log(c, sw["id"], "downloading", fmt("Downloading ({p:.0f} %)", "Laster ned ({p:.0f} %)", p=progress * 100),
                             download_id=dl_id, progress=round(progress, 3))
        except Exception as e:  # network etc. – try again at the next follow-up
            log.warning("Swap %s: %s", sw["id"], e)
            msg = e.msg if isinstance(e, ActionError) else str(e)
            with db.conn() as c:
                c.execute("UPDATE swaps SET message=? WHERE id=?",
                          (store(fmt("Temporary error: {e} (retrying)", "Midlertidig feil: {e} (prøver igjen)", e=msg)), sw["id"]))
    return list_swaps()
