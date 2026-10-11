"""Avvik mellom disk og Plex.

  * På disk, ikke i Plex: videofiler i bibliotekene (ikke ekstramateriale, ikke nedlastingsmappen)
    som ingen Plex-element peker på.
  * I Plex, mangler på disk: Plex-elementer som peker på filer som ikke finnes i skanningen.

Den eneste handlingen er å be Plex skanne en mappe på nytt (delvis bibliotekskanning) –
ufarlig, endrer ingenting på disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
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


# ================================================================== sletting av mapper på disk
# Gjelder titler som verken Radarr eller Sonarr kjenner (nøkkel «dir:…»): hele toppmappen i biblioteket
# slettes direkte på disk. Samme bryter og skrivetilgang som duplikater og nedlastinger.

def _dir_target(c, key: str) -> dict:
    t = db.rows(c, "SELECT key, name, year, library, folder, protected, protect_reason FROM titles WHERE key=?", (key,))
    if not t:
        return {"key": key, "ok": False, "reason": "Finnes ikke i siste analyse", "name": key, "files": [], "size": 0, "freed": 0}
    t = t[0]
    out = {"key": key, "name": t["name"] + (f" ({t['year']})" if t["year"] else ""), "library": t["library"],
           "folder": t["folder"], "files": [], "size": 0, "freed": 0, "ok": False, "reason": None}
    lib = {l["name"]: l for l in settings.get()["libraries"]}.get(t["library"]) or {}
    folder = (t["folder"] or "").rstrip("/")
    root = (lib.get("host_path") or "").rstrip("/")
    if not key.startswith("dir:"):
        out["reason"] = "Administreres av Radarr/Sonarr – slett tittelen via dem"
        return out
    if lib.get("kind") == "downloads":
        out["reason"] = "Ligger i nedlastingsmappen – slett fra Nedlastinger"
        return out
    if not root or not folder.startswith(root + "/") or "/" in folder[len(root) + 1:]:
        out["reason"] = "Bare mapper rett under et bibliotek kan slettes"
        return out
    if t["protected"]:
        out["reason"] = f"Beskyttet: {t['protect_reason']}"
        return out
    files = db.rows(c, "SELECT path, size, alloc, mtime, dev, inode, nlink, is_video FROM files WHERE path=? OR substr(path,1,?)=?",
                    (folder, len(folder) + 1, folder + "/"))
    if not files:
        out["reason"] = "Ingen filer i siste skanning"
        return out
    paths = {f["path"] for f in files}
    from .dupes import _managed_paths
    if paths & _managed_paths(c):
        out["reason"] = "Noen filer administreres av Radarr/Sonarr"
        return out
    arr_folders = [r[0] for r in c.execute("SELECT path FROM radarr_movies UNION SELECT path FROM sonarr_series") if r[0]]
    if any(a.rstrip("/") == folder or a.startswith(folder + "/") for a in arr_folders):
        out["reason"] = "Mappen inneholder en film eller serie fra Radarr/Sonarr"
        return out
    in_plex = paths & {r[0] for r in c.execute("SELECT path FROM plex_parts")}
    if in_plex:
        out["reason"] = f"{len(in_plex)} fil(er) i mappen er i Plex"
        return out
    # hardlenker: plassen frigjøres bare hvis alle stiene til inoden er i mappen
    freed = 0
    for f in files:
        size = f["alloc"] or f["size"] or 0
        if (f["nlink"] or 1) > 1:
            others = [r[0] for r in c.execute("SELECT path FROM files WHERE dev=? AND inode=?", (f["dev"], f["inode"]))]
            if len(others) < f["nlink"] or any(p not in paths for p in others):
                continue
        freed += size
    out.update(files=[{"path": f["path"], "size": f["size"], "mtime": f["mtime"]} for f in sorted(files, key=lambda x: x["path"])],
               size=sum(f["alloc"] or f["size"] or 0 for f in files), freed=freed, ok=True)
    return out


def _disk_check(target: dict) -> str | None:
    """Rett før sletting: mappen må finnes, ikke være symlenke, være skrivbar og ha samme innhold som ved skanning."""
    from .dupes import _container_path
    cpath, lib = _container_path(target["folder"])
    if not cpath:
        return "Mappen er ikke montert i appen"
    root = os.path.realpath(lib["container_path"])
    real = os.path.realpath(cpath)
    if real == root or not real.startswith(root + os.sep):
        return "Peker utenfor biblioteket"
    try:
        st = os.lstat(cpath)
    except FileNotFoundError:
        return "Finnes ikke lenger"
    import stat as _stat
    if _stat.S_ISLNK(st.st_mode):
        return "Er en symlenke"
    if not os.access(os.path.dirname(cpath), os.W_OK):
        return "Ingen skrivetilgang (montert :ro)"
    host_root = lib["host_path"].rstrip("/")
    on_disk = {}
    if _stat.S_ISDIR(st.st_mode):
        for dp, dns, fns in os.walk(cpath):
            for n in fns:
                p = os.path.join(dp, n)
                try:
                    s = os.lstat(p)
                except FileNotFoundError:
                    continue
                on_disk[host_root + p[len(lib["container_path"].rstrip("/")):]] = s.st_size
    else:
        on_disk[target["folder"]] = st.st_size
    scanned = {f["path"]: f["size"] for f in target["files"]}
    if on_disk != scanned:
        new = len(set(on_disk) - set(scanned))
        return "Innholdet er endret siden siste skanning" + (f" ({new} nye filer)" if new else "") + " – kjør Skann endringer"
    return None


def delete_plan(keys: list[str]) -> dict:
    from .dupes import enabled as files_enabled
    items, h = [], hashlib.sha256()
    with db.conn() as c:
        for k in list(dict.fromkeys(keys))[:200]:
            it = _dir_target(c, k)
            if it["ok"]:
                reason = _disk_check(it)
                if reason:
                    it.update(ok=False, reason=reason)
            if it["ok"]:
                for f in it["files"]:
                    h.update(f"{f['path']}|{f['size']}|{f['mtime']}".encode())
            items.append(it)
    ok = [i for i in items if i["ok"]]
    return {"enabled": files_enabled(), "items": items, "count": len(ok), "files": sum(len(i["files"]) for i in ok),
            "size": sum(i["size"] for i in ok), "freed": sum(i["freed"] for i in ok), "token": h.hexdigest()[:24]}


def delete_execute(keys: list[str], token: str) -> dict:
    from .dupes import _container_path, enabled as files_enabled
    if not files_enabled():
        raise PermissionError("Sletting av filer er slått av under Innstillinger → Sletting")
    p = delete_plan(keys)
    if p["token"] != token:
        raise ValueError("Innholdet er endret siden oppsummeringen ble vist. Åpne den på nytt.")
    results = []
    with db.conn() as c:
        for it in p["items"]:
            if not it["ok"]:
                results.append({"key": it["key"], "status": "hoppet over", "detail": it["reason"]})
                continue
            reason = _disk_check(it)
            if reason:
                status, detail = "feilet", reason
            else:
                cpath, _ = _container_path(it["folder"])
                try:
                    if os.path.isdir(cpath):
                        shutil.rmtree(cpath)
                    else:
                        os.remove(cpath)
                    status, detail = "utført", f"Slettet fra disk ({len(it['files'])} filer)"
                except OSError as e:
                    status, detail = "feilet", f"{type(e).__name__}: {e}"
            c.execute("INSERT INTO actions(ts,suggestion_id,title_key,title,action,service,status,detail,bytes) VALUES(?,?,?,?,?,?,?,?,?)",
                      (time.time(), None, it["key"], f"{it['library']}: {it['name']}", "delete_folder", "filsystem",
                       status, detail, it["freed"] if status == "utført" else 0))
            db.audit(c, "delete_folder", {"folder": it["folder"], "status": status, "detail": detail})
            results.append({"key": it["key"], "status": status, "detail": detail})
    done = sum(r["status"] == "utført" for r in results)
    if done:
        from . import jobs
        jobs.enqueue("refresh")
    return {"results": results, "done": done, "failed": sum(r["status"] == "feilet" for r in results)}


# ================================================================== fjern fra Plex
# For Plex-oppføringer der filene mangler på disk. Plex sin DELETE på et element sletter også filene –
# derfor kontrolleres det rett før hvert kall at INGEN av elementets filer finnes, og at biblioteksmappen
# faktisk er montert og har innhold (ellers ville en manglende montering se ut som «alt mangler»).

def _plex_targets(c, group_key: str) -> dict:
    out = {"key": group_key, "ok": False, "reason": None, "name": group_key, "calls": [], "files": [], "size": 0}
    parts = db.rows(c, """SELECT p.path, p.rating_key, p.media_id, p.size, i.kind, i.title, i.show_key, i.season, i.episode
                          FROM plex_parts p JOIN plex_items i ON i.rating_key=p.rating_key""")
    if group_key.startswith("show:"):
        show = group_key[5:]
        mine = [p for p in parts if p["show_key"] == show]
        name = c.execute("SELECT title FROM plex_items WHERE rating_key=?", (show,)).fetchone()
        out["name"] = name[0] if name else "Ukjent serie"
    elif group_key.startswith("movie:"):
        mine = [p for p in parts if p["rating_key"] == group_key[6:]]
        out["name"] = mine[0]["title"] if mine else group_key
    else:
        out["reason"] = "Ukjent oppføring"
        return out
    if not mine:
        out["reason"] = "Finnes ikke i Plex lenger (fra siste synk)"
        return out
    state = {p["path"]: _exists(p["path"]) for p in mine}
    if any(v is None for v in state.values()):
        out["reason"] = "Biblioteksmappen er ikke montert eller er tom – kan ikke bekrefte at filene mangler"
        return out
    missing = [p for p in mine if state[p["path"]] is False]
    present = [p for p in mine if state[p["path"]]]
    by_item: dict[str, list] = defaultdict(list)
    for p in mine:
        by_item[p["rating_key"]].append(p)
    if group_key.startswith("show:") and not present:
        out["calls"] = [{"rating_key": group_key[5:], "media_id": None, "label": "Hele serien"}]
    else:
        for rk, ps in by_item.items():
            gone = [p for p in ps if state[p["path"]] is False]
            if not gone:
                continue
            label = (f"S{ps[0]['season']:02d}E{ps[0]['episode']:02d}" if ps[0]["kind"] == "episode" and ps[0]["season"] is not None
                     and ps[0]["episode"] is not None else ps[0]["title"])
            if len(gone) == len(ps):
                out["calls"].append({"rating_key": rk, "media_id": None, "label": label})
            else:
                # flere versjoner – fjern bare versjonene som mangler (alle delene i versjonen må mangle)
                medias = defaultdict(list)
                for p in ps:
                    medias[p["media_id"]].append(p)
                for mid, mps in medias.items():
                    if all(state[p["path"]] is False for p in mps):
                        out["calls"].append({"rating_key": rk, "media_id": mid, "label": f"{label} (én versjon)"})
    out["files"] = [{"path": p["path"], "size": p["size"]} for p in missing]
    out["size"] = sum(p["size"] or 0 for p in missing)
    out["kept"] = len(present)
    if not out["calls"]:
        out["reason"] = "Alle filene finnes på disk"
        return out
    out["ok"] = True
    return out


def _exists(host_path: str) -> bool | None:
    """True/False om filen finnes; None hvis det ikke kan avgjøres (ikke montert / tomt bibliotek)."""
    from .dupes import _container_path
    cpath, lib = _container_path(host_path)
    if not cpath:
        return None
    root = lib["container_path"]
    try:
        if not os.path.isdir(root) or not any(os.scandir(root)):
            return None
    except OSError:
        return None
    return os.path.lexists(cpath)


def plex_remove_plan(keys: list[str]) -> dict:
    from .actions import enabled as actions_enabled
    items, h = [], hashlib.sha256()
    with db.conn() as c:
        for k in list(dict.fromkeys(keys))[:200]:
            it = _plex_targets(c, k)
            if it["ok"]:
                h.update(json.dumps(it["calls"], sort_keys=True).encode())
            items.append(it)
    ok = [i for i in items if i["ok"]]
    return {"enabled": actions_enabled(), "items": items, "count": len(ok), "calls": sum(len(i["calls"]) for i in ok),
            "token": h.hexdigest()[:24]}


def plex_remove_execute(keys: list[str], token: str) -> dict:
    from .actions import enabled as actions_enabled
    if not actions_enabled():
        raise PermissionError("Sletting via tjenestene er slått av under Innstillinger → Sletting")
    cfg = settings.get()["services"]["plex"]
    if not cfg.get("url") or not cfg.get("token"):
        raise ActionError("Plex er ikke konfigurert")
    p = plex_remove_plan(keys)
    if p["token"] != token:
        raise ValueError("Innholdet er endret siden oppsummeringen ble vist. Åpne den på nytt.")
    base = cfg["url"].rstrip("/")
    results = []
    with db.conn() as c:
        for it in p["items"]:
            if not it["ok"]:
                results.append({"key": it["key"], "status": "hoppet over", "detail": it["reason"]})
                continue
            # kontroller på nytt rett før kallene
            again = _plex_targets(c, it["key"])
            if not again["ok"] or again["calls"] != it["calls"]:
                status, detail = "feilet", again["reason"] or "Endret siden oppsummeringen"
            else:
                done, errs = 0, []
                for call in it["calls"]:
                    url = f"{base}/library/metadata/{call['rating_key']}" + (f"/media/{call['media_id']}" if call["media_id"] else "")
                    try:
                        r = httpx.delete(url, headers={"X-Plex-Token": cfg["token"]}, timeout=30)
                    except httpx.HTTPError as e:
                        errs.append(f"{call['label']}: ingen kontakt ({e})")
                        continue
                    if r.status_code in (401, 403):
                        errs.append("Plex avviste slettingen. Slå på «Allow media deletion» i Plex → Settings → Library")
                        break
                    if r.status_code >= 400 and r.status_code != 404:
                        errs.append(f"{call['label']}: Plex svarte {r.status_code}")
                        continue
                    done += 1
                status = "utført" if done and not errs else "feilet"
                detail = f"Fjernet {done} av {len(it['calls'])} oppføringer fra Plex" + (f". {'; '.join(errs[:2])}" if errs else "")
            c.execute("INSERT INTO actions(ts,suggestion_id,title_key,title,action,service,status,detail,bytes) VALUES(?,?,?,?,?,?,?,?,?)",
                      (time.time(), None, None, it["name"], "plex_remove", "plex", status, detail, 0))
            db.audit(c, "plex_remove", {"key": it["key"], "calls": it["calls"], "status": status, "detail": detail})
            results.append({"key": it["key"], "status": status, "detail": detail})
    if any(r["status"] == "utført" for r in results):
        from . import jobs
        jobs.enqueue("sync")
    return {"results": results, "done": sum(r["status"] == "utført" for r in results),
            "failed": sum(r["status"] == "feilet" for r in results)}
