"""Avvik mellom disk og Plex.

  * På disk, ikke i Plex: videofiler i bibliotekene (ikke ekstramateriale, ikke nedlastingsmappen)
    som ingen Plex-element peker på.
  * I Plex, mangler på disk: Plex-elementer som peker på filer som ikke finnes i skanningen.

Den eneste handlingen er å be Plex skanne en mappe på nytt (delvis bibliotekskanning) –
ufarlig, endrer ingenting på disk.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict

import httpx

from . import db, settings
from .actions import ActionError

DISC_EXT = {".iso", ".img"}


def host_to_service(path: str) -> str:
    """Motsatt av settings.map_service_path: vertssti -> slik tjenestene (Plex) ser den."""
    best = None
    for m in settings.get()["path_mappings"]:
        to = m["to"].rstrip("/")
        if path == to or path.startswith(to + "/"):
            if best is None or len(to) > len(best["to"].rstrip("/")):
                best = m
    if not best:
        return path
    to = best["to"].rstrip("/")
    return best["from"].rstrip("/") + path[len(to):]


def _sections(c) -> list[dict]:
    return db.kv_get(c, "plex_libraries", []) or []


def _section_for(path: str, sections: list[dict]) -> dict | None:
    best, blen = None, -1
    for s in sections:
        for loc in s.get("locations") or []:
            loc = (loc or "").rstrip("/")
            if loc and (path == loc or path.startswith(loc + "/")) and len(loc) > blen:
                best, blen = s, len(loc)
    return best


def overview(view: str = "not_in_plex", q: str = "", library: str = "") -> dict:
    s = settings.get()
    libs = {l["name"]: l for l in s["libraries"]}
    with db.conn() as c:
        status = (db.kv_get(c, "service_status", {}) or {}).get("plex", {})
        sections = _sections(c)
        plex_paths = {r[0] for r in c.execute("SELECT DISTINCT path FROM plex_parts")}
        plex_synced = status.get("last_success")
        if not plex_paths:
            return {"available": False, "message": "Ingen data fra Plex ennå. Koble til Plex under Innstillinger og kjør en full oppdatering.",
                    "summary": {}, "items": []}
        files = db.rows(c, """SELECT f.path, f.library, f.size, f.alloc, f.mtime, f.ext, f.is_extra, f.dir,
                                     ft.title_key, t.name AS title_name, t.year, t.kind, t.radarr_id, t.sonarr_id
                              FROM files f LEFT JOIN file_title ft ON ft.path=f.path LEFT JOIN titles t ON t.key=ft.title_key
                              WHERE f.is_video=1""")
        disk_paths = {f["path"] for f in files}
        parts = db.rows(c, """SELECT p.path, p.rating_key, p.size, i.title, i.kind, i.show_key, i.season, i.episode, i.library
                              FROM plex_parts p LEFT JOIN plex_items i ON i.rating_key=p.rating_key""")
        shows = {r[0]: r[1] for r in c.execute("SELECT rating_key, title FROM plex_items WHERE kind='show'")}

    # ---------- på disk, ikke i Plex
    groups: dict[str, dict] = {}
    for f in files:
        lib = libs.get(f["library"], {})
        if lib.get("kind") == "downloads" or f["is_extra"] or f["path"] in plex_paths:
            continue
        sec = _section_for(f["path"], sections)
        if sec is None:
            reason, code = "Mappen er ikke med i noe Plex-bibliotek", "no_section"
        elif (f["ext"] or "").lower() in DISC_EXT:
            reason, code = "Plex spiller ikke av diskbilder (ISO/IMG)", "disc"
        elif plex_synced and f["mtime"] > plex_synced - 3600:
            reason, code = "Lagt til etter siste synk med Plex – kan være under skanning", "recent"
        else:
            reason, code = "Ikke funnet av Plex – kan være feil navngitt, umatchet eller ignorert", "unmatched"
        key = f["title_key"] or f["dir"]
        g = groups.setdefault(key, {
            "key": key, "title_key": f["title_key"], "name": f["title_name"] or os.path.basename(f["dir"]),
            "year": f["year"], "kind": f["kind"], "library": f["library"], "folder": f["dir"],
            "managed": f["radarr_id"] is not None or f["sonarr_id"] is not None,
            "section": sec["title"] if sec else None, "section_key": sec["key"] if sec else None,
            "files": [], "size": 0, "reasons": defaultdict(int), "codes": set(), "newest": 0})
        g["files"].append({"path": f["path"], "size": f["size"], "mtime": f["mtime"], "reason": reason})
        g["size"] += f["alloc"] or f["size"]
        g["reasons"][reason] += 1
        g["codes"].add(code)
        g["newest"] = max(g["newest"], f["mtime"])
    not_in_plex = []
    for g in groups.values():
        g["reason"] = max(g["reasons"].items(), key=lambda kv: kv[1])[0]
        g["code"] = next(iter(sorted(g["codes"])))
        g["reasons"] = dict(g["reasons"])
        g["codes"] = sorted(g["codes"])
        g["count"] = len(g["files"])
        g["files"].sort(key=lambda x: x["path"])
        not_in_plex.append(g)

    # ---------- i Plex, mangler på disk (bare innenfor bibliotekene vi skanner)
    roots = [l["host_path"].rstrip("/") for l in libs.values() if l.get("kind") != "downloads"]
    missing_groups: dict[str, dict] = {}
    for p in parts:
        if p["path"] in disk_paths or not any(p["path"].startswith(r + "/") for r in roots):
            continue
        if p["kind"] == "episode":
            key, name = f"show:{p['show_key']}", shows.get(p["show_key"]) or "Ukjent serie"
        else:
            key, name = f"movie:{p['rating_key']}", p["title"] or os.path.basename(p["path"])
        g = missing_groups.setdefault(key, {"key": key, "name": name, "section": p["library"],
                                            "folder": os.path.dirname(p["path"]), "files": [], "size": 0})
        g["files"].append({"path": p["path"], "size": p["size"],
                           "label": f"S{p['season']:02d}E{p['episode']:02d}" if p["kind"] == "episode" and p["season"] is not None and p["episode"] is not None else None})
        g["size"] += p["size"] or 0
    missing = list(missing_groups.values())
    for g in missing:
        g["count"] = len(g["files"])
        sec = _section_for(g["files"][0]["path"], sections)
        g["section_key"] = sec["key"] if sec else None

    def agg(items):
        return {"groups": len(items), "files": sum(i["count"] for i in items), "size": sum(i["size"] for i in items)}
    by_code = defaultdict(list)
    for g in not_in_plex:
        by_code[g["code"]].append(g)
    summary = {"not_in_plex": agg(not_in_plex), "missing": agg(missing),
               "by_reason": {k: agg(v) for k, v in by_code.items()},
               "plex_synced": plex_synced, "sections": [s["title"] for s in sections]}

    items = not_in_plex if view == "not_in_plex" else missing
    if view.startswith("reason:"):
        items = by_code.get(view.split(":", 1)[1], [])
    if q:
        items = [i for i in items if q.lower() in (i["name"] or "").lower() or q.lower() in i["folder"].lower()]
    if library:
        items = [i for i in items if i.get("library") == library]
    items = sorted(items, key=lambda i: -i["size"])
    return {"available": True, "summary": summary, "items": items[:1000], "total": len(items)}


def rescan(folder: str) -> dict:
    """Be Plex skanne én mappe (delvis bibliotekskanning)."""
    s = settings.get()
    cfg = s["services"]["plex"]
    if not cfg.get("url") or not cfg.get("token"):
        raise ActionError("Plex er ikke konfigurert")
    with db.conn() as c:
        sec = _section_for(folder, _sections(c))
        if not sec:
            raise ActionError("Mappen ligger ikke i noe Plex-bibliotek. Legg den til i Plex først.")
        plex_path = host_to_service(folder)
        try:
            r = httpx.get(f"{cfg['url'].rstrip('/')}/library/sections/{sec['key']}/refresh",
                          params={"path": plex_path}, headers={"X-Plex-Token": cfg["token"]}, timeout=30)
        except httpx.HTTPError as e:
            raise ActionError(f"Ingen kontakt med Plex: {e}") from e
        if r.status_code >= 400:
            raise ActionError(f"Plex svarte {r.status_code}")
        db.audit(c, "plex_rescan", {"folder": folder, "plex_path": plex_path, "section": sec["title"]})
    return {"ok": True, "section": sec["title"], "plex_path": plex_path,
            "message": f"Plex skanner {plex_path} i «{sec['title']}». Kjør en synk om noen minutter for å se resultatet.",
            "ts": time.time()}
