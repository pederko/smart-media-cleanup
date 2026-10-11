"""First-run checklist and path-mapping suggestions.

The app needs to know where the libraries are (detected from /media) and how Radarr, Sonarr and Plex
see the same folders. The services often see different paths than the NAS (e.g. «/movies» inside
their container), so a mapping «/movies» -> «/mnt/tank/media/movies» is needed. Suggestions are made
by matching the folder names of the services' root folders with the library folders.
"""
from __future__ import annotations

import os

from . import db, settings
from .i18n import L, fmt


def _within(path: str, root: str) -> bool:
    root = root.rstrip("/")
    return path == root or path.startswith(root + "/")


def service_paths(c) -> list[dict]:
    """Every root folder / Plex location we know, how it maps today and a suggestion if it does not."""
    s = settings.get()
    libs = s["libraries"]
    roots = db.kv_get(c, "root_folders", {}) or {}
    out = []
    sources = [("radarr", p) for p in roots.get("radarr", [])] + [("sonarr", p) for p in roots.get("sonarr", [])]
    for sec in db.kv_get(c, "plex_libraries", []) or []:
        sources += [("plex", p) for p in sec.get("raw_locations") or []]
    seen = set()
    for service, raw in sources:
        if (service, raw) in seen:
            continue
        seen.add((service, raw))
        mapped = settings.map_service_path(raw, s) or raw
        lib = next((l for l in libs if _within(mapped, l["host_path"]) or _within(l["host_path"], mapped)), None)
        item = {"service": service, "path": raw, "mapped": mapped, "library": lib["name"] if lib else None,
                "ok": lib is not None, "suggestion": None}
        if not lib:
            base = os.path.basename(raw.rstrip("/")).lower()
            match = next((l for l in libs if os.path.basename(l["host_path"].rstrip("/")).lower() == base
                          or l["name"].lower() == base), None)
            if match:
                item["suggestion"] = {"from": raw.rstrip("/"), "to": match["host_path"].rstrip("/"), "library": match["name"]}
        out.append(item)
    return out


def status() -> dict:
    s = settings.get()
    with db.conn() as c:
        svc = db.kv_get(c, "service_status", {}) or {}
        paths = service_paths(c)
        last_scan = db.kv_get(c, "last_scan")
        last_analysis = db.kv_get(c, "last_analysis")
    libs = s["libraries"]
    missing = [l["name"] for l in libs if not os.path.isdir(l.get("container_path") or "")]
    core = ("radarr", "sonarr", "plex", "tautulli")
    configured = {n: bool(s["services"][n].get("url")) for n in s["services"]}
    steps = [
        {"id": "libraries", "done": bool(libs) and not missing,
         "title": L("Libraries are mounted", "Bibliotekene er montert"),
         "detail": (fmt("Found: {names}", "Funnet: {names}", names=", ".join(l["name"] for l in libs))
                    if libs and not missing else
                    fmt("Not found in the container: {m}", "Finnes ikke i containeren: {m}", m=", ".join(missing)) if missing else
                    L("Mount your media folders under /media in the app's compose file",
                      "Monter mediemappene under /media i appens compose-fil"))},
        {"id": "services", "done": all(configured[n] for n in core),
         "title": L("Radarr, Sonarr, Plex and Tautulli are connected", "Radarr, Sonarr, Plex og Tautulli er koblet til"),
         "detail": fmt("{n} of 4 configured", "{n} av 4 konfigurert", n=sum(configured[n] for n in core))},
        {"id": "services_ok", "done": all(svc.get(n, {}).get("ok") for n in core if configured[n]) and any(configured[n] for n in core),
         "title": L("The services answer", "Tjenestene svarer"),
         "detail": ", ".join(f"{n.capitalize()}: {'OK' if svc.get(n, {}).get('ok') else '–'}" for n in core if configured[n]) or "–"},
        {"id": "paths", "done": bool(paths) and all(p["ok"] for p in paths),
         "title": L("The services' folders match the libraries", "Tjenestenes mapper stemmer med bibliotekene"),
         "detail": (fmt("Needs a path mapping: {names}", "Trenger stimapping: {names}", names=", ".join(p["path"] for p in paths if not p["ok"]))
                    if any(not p["ok"] for p in paths) else
                    L("Checked after the first sync", "Sjekkes etter første synk") if not paths else L("All good", "Alt stemmer"))},
        {"id": "refresh", "done": bool(last_scan and last_analysis),
         "title": L("First full refresh has run", "Første fulle oppdatering er kjørt"),
         "detail": L("Activity → Run full refresh", "Aktivitet → Kjør full oppdatering")},
    ]
    return {"steps": steps, "done": all(x["done"] for x in steps), "paths": paths, "libraries": libs,
            "detected": settings.detect_libraries()}
