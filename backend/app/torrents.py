"""qBittorrent: every torrent, what it is (still downloading, waiting for import, already in a library,
orphaned, broken) and the seeding rules.

Classes of a torrent:
  * downloading – not finished.
  * importing   – finished, and Radarr/Sonarr still has it in the queue (never touched).
  * imported    – finished, and its content is found in a library (hardlink or identical copy).
  * orphaned    – from Radarr/Sonarr (by category), finished, not in their queue, and its content is in the
                  downloads folder but not in any library (never imported, or the title was deleted since).
  * error       – qBittorrent reports an error or missing files.
  * other       – not from Radarr/Sonarr (another category).
  * unknown     – from Radarr/Sonarr, but its files are not in a scanned downloads library, so the app cannot
                  tell. Never offered for deletion with files.

The seeding rule (Settings «seeding_rule») is the one thing that runs on its own once switched on – and
only after the user confirmed it: it sets a seeding limit on torrents from Radarr/Sonarr that still
use qBittorrent's global limit. Torrents with their own limit (set by an indexer, e.g. a private
tracker's rules) are left alone. It never removes anything.
"""
from __future__ import annotations

import logging
import time

from . import db, settings
from .actions import DONE, log_action
from .actions import enabled as actions_enabled
from .clients import qbit
from .clients.base import ServiceError, get_json
from .i18n import fmt

log = logging.getLogger("smc.torrents")

ERROR_STATES = {"error", "missingFiles"}
STOPPED_STATES = {"pausedUP", "stoppedUP", "pausedDL", "stoppedDL"}
GLOBAL, NONE = -2, -1


def qbit_cfg() -> dict | None:
    cfg = settings.get()["services"]["qbittorrent"]
    return cfg if cfg.get("enabled") and cfg.get("url") else None


def rule() -> dict:
    r = settings.get().get("seeding_rule") or {}
    return {"enabled": bool(r.get("enabled")), "ratio": r.get("ratio"), "minutes": r.get("minutes"),
            "inactive": r.get("inactive")}


def _arr_cfg(svc: str):
    cfg = settings.get()["services"][svc]
    if not cfg.get("url") or not cfg.get("api_key"):
        return None
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}


def arr_context() -> dict:
    """The qBittorrent categories Radarr/Sonarr use, and the download ids in their queues."""
    cats: dict[str, str] = {}
    queue: set[str] = set()
    ok = True
    for svc, field in (("radarr", "movieCategory"), ("sonarr", "tvCategory")):
        cfg = _arr_cfg(svc)
        if not cfg:
            continue
        base, h = cfg
        try:
            for c in get_json(f"{base}/api/v3/downloadclient", headers=h, retries=0):
                if c.get("protocol") == "torrent":
                    for f in c.get("fields") or []:
                        if f.get("name") == field and f.get("value"):
                            cats[f["value"]] = svc
            for q in get_json(f"{base}/api/v3/queue/details", headers=h, retries=0):
                if q.get("downloadId"):
                    queue.add(str(q["downloadId"]).lower())
        except ServiceError:
            ok = False  # without the queue, nothing from that service may be called orphaned
    return {"categories": cats, "queue": queue, "complete": ok}


def _entry(entries: list[dict], content_path: str | None) -> dict | None:
    if not content_path:
        return None
    host = settings.map_service_path(content_path)
    for e in entries:
        if host == e["path"] or host.startswith(e["path"] + "/"):
            return e
    return None


def classify(t: dict, entries: list[dict], ctx: dict) -> dict:
    e = _entry(entries, t.get("content_path"))
    state = t.get("state") or ""
    complete = (t.get("progress") or 0) >= 1
    arr = ctx["categories"].get(t.get("category") or "")
    in_queue = t["hash"].lower() in ctx["queue"]
    imported = bool(e and e["status"] in ("hardlinked", "copied"))
    if state in ERROR_STATES:
        cls = "error"
    elif not complete:
        cls = "downloading"
    elif in_queue:
        cls = "importing"
    elif imported:
        cls = "imported"
    elif not arr:
        cls = "other"
    elif e and ctx["complete"]:
        cls = "orphaned"
    else:
        cls = "unknown"
    rl, sl = t.get("ratio_limit"), t.get("seeding_time_limit")
    il = t.get("inactive_seeding_time_limit")
    if rl == GLOBAL and sl == GLOBAL and il in (None, GLOBAL):
        limit = "global"
    elif rl == NONE and sl == NONE and il in (None, NONE, GLOBAL):
        limit = "none"
    else:
        limit = "own"
    return {
        "hash": t["hash"], "name": t.get("name"), "category": t.get("category") or "", "arr": arr, "state": state,
        "class": cls, "stopped": state in STOPPED_STATES, "complete": complete, "ratio": round(t.get("ratio") or 0, 2),
        "seeding_minutes": int((t.get("seeding_time") or 0) / 60), "size": t.get("size") or 0,
        "added": t.get("added_on"), "last_activity": t.get("last_activity"),
        "limit": limit, "ratio_limit": rl, "seeding_limit": sl, "inactive_limit": il,
        "import_status": e["status"] if e else None, "title_name": e["title_name"] if e else None,
        "title_key": e["title_key"] if e else None,
        "freed": e["freed"] if e and cls in ("imported", "orphaned", "other") else 0,
        "removable": complete and cls in ("imported", "orphaned", "other", "error", "unknown"),
        "files_removable": complete and cls in ("imported", "orphaned", "other"),
    }


def _entries() -> list[dict]:
    from . import downloads
    return downloads.overview()["items"]


def limits_from_prefs(prefs: dict) -> dict:
    return {"ratio_enabled": bool(prefs.get("max_ratio_enabled")), "ratio": prefs.get("max_ratio"),
            "time_enabled": bool(prefs.get("max_seeding_time_enabled")), "minutes": prefs.get("max_seeding_time"),
            "inactive_enabled": bool(prefs.get("max_inactive_seeding_time_enabled")),
            "inactive": prefs.get("max_inactive_seeding_time"),
            "inactive_supported": "max_inactive_seeding_time_enabled" in prefs,
            "action": prefs.get("max_ratio_act")}


def view(arr_only: bool = False) -> dict:
    cfg = qbit_cfg()
    if not cfg:
        return {"configured": False}
    try:
        with qbit.Client(cfg) as q:
            prefs = q.preferences()
            raw = q.torrents()
            version = q.version()
    except ServiceError as e:
        return {"configured": True, "error": e.msg}
    ctx = arr_context()
    entries = _entries()
    items = [classify(t, entries, ctx) for t in raw]
    if arr_only:
        items = [i for i in items if i["arr"]]
    items.sort(key=lambda x: -x["size"])
    summary = {"count": len(items), "size": sum(i["size"] for i in items), "by_class": {},
               "seeding": sum(1 for i in items if i["complete"] and not i["stopped"] and i["class"] != "error")}
    for i in items:
        d = summary["by_class"].setdefault(i["class"], {"count": 0, "size": 0, "freed": 0})
        d["count"] += 1
        d["size"] += i["size"]
        d["freed"] += i["freed"]
    with db.conn() as c:
        applied = db.kv_get(c, "seeding_rule_applied", {}) or {}
    return {"configured": True, "version": version, "limits": limits_from_prefs(prefs), "rule": rule(),
            "rule_applied": {"count": len(applied.get("hashes") or []), "at": applied.get("at"), "error": applied.get("error")},
            "categories": ctx["categories"], "arr_checked": ctx["complete"], "torrents": items, "summary": summary,
            "actions_enabled": actions_enabled(), "files_enabled": bool(settings.get()["actions"].get("files_enabled"))}


def _rule_values(r: dict) -> tuple[float, int, int]:
    return (float(r["ratio"]) if r.get("ratio") is not None else NONE,
            int(r["minutes"]) if r.get("minutes") is not None else NONE,
            int(r["inactive"]) if r.get("inactive") is not None else NONE)


def apply_rule(force: bool = False) -> int:
    """Sets the seeding rule on Radarr/Sonarr torrents that still use the global limit (or that the rule
    set before, if the rule changed). Runs from the scheduler; does nothing unless the rule and
    «Allow changes» are on. Returns how many torrents were changed."""
    r = rule()
    cfg = qbit_cfg()
    if not (r["enabled"] and cfg and actions_enabled()):
        return 0
    if r["ratio"] is None and r["minutes"] is None and r["inactive"] is None:
        return 0
    ctx = arr_context()
    if not ctx["categories"]:
        return 0
    want = _rule_values(r)
    with db.conn() as c:
        state = db.kv_get(c, "seeding_rule_applied", {}) or {}
    ours = set(state.get("hashes") or [])
    with qbit.Client(cfg) as q:
        torrents = q.torrents()
        todo = []
        for t in torrents:
            if t.get("category") not in ctx["categories"]:
                continue
            cur = (t.get("ratio_limit"), t.get("seeding_time_limit"), t.get("inactive_seeding_time_limit", GLOBAL))
            untouched = cur[0] == GLOBAL and cur[1] == GLOBAL and cur[2] in (GLOBAL, None)
            if t["hash"] in ours or untouched:
                if (cur[0], cur[1]) != want[:2] or (cur[2] is not None and cur[2] != want[2]):
                    todo.append(t["hash"])
        if todo:
            q.set_share_limits(todo, want[0], want[1], want[2])
    present = {t["hash"] for t in torrents}
    ours = (ours & present) | set(todo)
    with db.conn() as c:
        db.kv_set(c, "seeding_rule_applied", {"hashes": sorted(ours), "at": time.time(), "error": None})
        if todo:
            log_action(c, title="qBittorrent", action="seeding_rule", service="qbittorrent", status=DONE,
                       detail=fmt("Seeding rule set on {n} torrent(s) from Radarr/Sonarr",
                                  "Delingsregel satt på {n} torrent(er) fra Radarr/Sonarr", n=len(todo)))
    return len(todo)


def apply_rule_safely() -> None:
    """For the scheduler: a failure is remembered and shown on the page, not logged every 5 minutes."""
    try:
        apply_rule()
        err = None
    except Exception as e:  # never break the scheduler
        log.warning("Seeding rule failed: %s", e)
        err = e.msg if hasattr(e, "msg") else f"{type(e).__name__}: {e}"
    with db.conn() as c:
        state = db.kv_get(c, "seeding_rule_applied", {}) or {}
        if state.get("error") != err:
            state["error"] = err
            db.kv_set(c, "seeding_rule_applied", state)
