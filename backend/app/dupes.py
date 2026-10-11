"""Duplicates: overview, filtering and (optional) deletion of redundant files.

Redundant versions and copies are normally NOT managed by Radarr/Sonarr, so they are deleted
directly on disk (see fsops for the two required choices). Files that Radarr/Sonarr do know are
deleted through their API instead, followed by a rescan so the kept file is picked up.

Hard rules (checked on the server right before each file is deleted):
  * the file belongs to a duplicate group from the latest analysis and is not the kept file
  * the kept file still exists, so at least one file in the group remains
  * the title/library is not protected (only if protection is set to include duplicates)
  * the file is a regular file (not a symlink) inside a configured library
  * size, mtime and inode are unchanged since the scan
"""
from __future__ import annotations

import hashlib
import json
import os
import stat as _stat

from . import db, jobs, settings
from .actions import DONE, FAILED, SKIPPED, _arr, _req, _same_folder, log_action
from .analysis import engine
from .fsops import VIDEO_EXT, container_path, files_enabled, managed_paths, read_only, writable_libraries
from .i18n import L, ActionError, Conflict, Forbidden, fmt

KINDS = ("identical", "versions", "hardlink")

# Re-exported for older imports
enabled = files_enabled
_container_path = container_path
_managed_paths = managed_paths


def _libs():
    return {l["name"]: l for l in settings.get()["libraries"]}


def protection_applies() -> bool:
    """Does protection (library, tags, labels) also apply to duplicates? Default: no."""
    return bool(settings.get()["protection"].get("include_duplicates", False))


def _load_groups(c) -> list[dict]:
    groups = db.rows(c, """SELECT g.id, g.kind, g.title_key, g.label, g.total, g.reclaimable, g.files,
                                  t.name AS title_name, t.year, t.kind AS title_kind, t.protected, t.protect_reason
                           FROM duplicate_groups g LEFT JOIN titles t ON t.key = g.title_key""")
    paths = set()
    for g in groups:
        fs = json.loads(g["files"] or "[]")
        g["keep_reason"] = next((x["keep_reason"] for x in fs if "keep_reason" in x), None)
        g["files"] = [x for x in fs if "path" in x]
        paths |= {f["path"] for f in g["files"]}
    info = {}
    plist = list(paths)
    for i in range(0, len(plist), 900):
        chunk = plist[i:i + 900]
        q = ",".join("?" * len(chunk))
        for r in db.rows(c, f"SELECT path, library, size, alloc, mtime, inode, dev, nlink, ext FROM files WHERE path IN ({q})", chunk):
            info[r["path"]] = r
    managed = managed_paths(c)
    libs = _libs()
    for g in groups:
        for f in g["files"]:
            fi = info.get(f["path"], {})
            f.update({k: fi.get(k) for k in ("library", "alloc", "mtime", "nlink", "ext")})
            f["managed"] = f["path"] in managed
            f["in_downloads"] = libs.get(fi.get("library"), {}).get("kind") == "downloads"
            f["missing"] = not fi
        g["in_downloads"] = any(f["in_downloads"] for f in g["files"])
        lib_prot = any(libs.get(f.get("library"), {}).get("protected") for f in g["files"])
        g["protected"] = 1 if (protection_applies() and (g["protected"] or lib_prot)) else 0
        g["libraries"] = sorted({f["library"] for f in g["files"] if f.get("library")})
        g["name"] = g["title_name"] or os.path.basename(g["files"][0]["path"]) if g["files"] else g["title_name"]
    return groups


def overview(kind: str = "", q: str = "", library: str = "", where: str = "", sort: str = "reclaimable",
             order: str = "desc", limit: int = 200, offset: int = 0) -> dict:
    with db.conn() as c:
        groups = _load_groups(c)
    summary = {}
    for k in KINDS:
        gs = [g for g in groups if g["kind"] == k]
        summary[k] = {"groups": len(gs), "files": sum(len(g["files"]) for g in gs),
                      "reclaimable": sum(g["reclaimable"] or 0 for g in gs),
                      "in_downloads": sum(1 for g in gs if g["in_downloads"]),
                      "in_downloads_bytes": sum(g["reclaimable"] or 0 for g in gs if g["in_downloads"])}
    items = [g for g in groups if not kind or g["kind"] == kind]
    if q:
        ql = q.lower()
        items = [g for g in items if ql in (g["name"] or "").lower() or any(ql in f["path"].lower() for f in g["files"])]
    if library:
        items = [g for g in items if library in g["libraries"]]
    if where == "downloads":
        items = [g for g in items if g["in_downloads"]]
    elif where == "library":
        items = [g for g in items if not g["in_downloads"]]
    keyf = {"reclaimable": lambda g: g["reclaimable"] or 0, "size": lambda g: g["total"] or 0,
            "name": lambda g: (g["name"] or "").lower(), "files": lambda g: len(g["files"])}
    items.sort(key=keyf.get(sort, keyf["reclaimable"]), reverse=order != "asc")
    total = len(items)
    page = items[offset:offset + max(1, min(limit, 1000))]
    return {"summary": summary, "total": total, "total_reclaimable": sum(g["reclaimable"] or 0 for g in items),
            "items": page, "files_enabled": files_enabled(), "writable": writable_libraries()}


# ------------------------------------------------------------------ deletion

def _arr_route(c, path: str, keep: str, keep_in_downloads: bool) -> tuple[dict | None, dict | None]:
    """For files Radarr/Sonarr know: delete through their API and let them rescan the folder, so the
    kept file is used instead. Requires the kept file to be in the same movie/series folder
    (otherwise the title would end up missing)."""
    m = db.rows(c, "SELECT id, path, title FROM radarr_movies WHERE file_path=?", (path,))
    if m:
        route = {"service": "radarr", "movie_id": m[0]["id"], "folder": (m[0]["path"] or "").rstrip("/")}
    else:
        sf = db.rows(c, "SELECT f.id, f.series_id, s.path FROM sonarr_files f JOIN sonarr_series s ON s.id=f.series_id "
                        "WHERE f.path=?", (path,))
        if not sf:
            return None, L("Managed by Radarr/Sonarr – could not find the entry", "Administreres av Radarr/Sonarr – fant ikke oppføringen")
        route = {"service": "sonarr", "file_id": sf[0]["id"], "series_id": sf[0]["series_id"],
                 "folder": (sf[0]["path"] or "").rstrip("/")}
    name = "Radarr" if route["service"] == "radarr" else "Sonarr"
    if keep_in_downloads or not route["folder"] or not keep.startswith(route["folder"] + "/"):
        return None, fmt("{svc} knows this file, and the file you keep is outside {svc}'s folder. "
                         "Keep a file in the same folder, or delete it in {svc}.",
                         "{svc} kjenner denne filen, og filen som beholdes ligger utenfor mappen til {svc}. "
                         "Velg en fil i samme mappe som «Beholdes», eller slett i {svc}.", svc=name)
    if os.path.splitext(keep)[1].lower() not in VIDEO_EXT:
        return None, L("The file you keep is not a video file", "Filen som beholdes er ikke en videofil")
    return route, None


def _check_file(f: dict, fi: dict | None, managed: set[str], protected: bool, need_write: bool = True) -> dict | None:
    """Reason why the file can NOT be deleted, or None."""
    if fi is None:
        return L("No longer in the scan", "Finnes ikke lenger i skanningen")
    if protected:
        return L("The title or library is protected", "Tittelen eller biblioteket er beskyttet")
    if f["path"] in managed:
        return L("Managed by Radarr/Sonarr – delete it there", "Administreres av Radarr/Sonarr – slett den der")
    cpath, lib = container_path(f["path"])
    if not cpath or not lib:
        return L("Outside the libraries", "Ligger utenfor bibliotekene")
    if lib.get("protected") and protection_applies():
        return fmt("The library {lib} is protected", "Biblioteket {lib} er beskyttet", lib=lib["name"])
    root = os.path.realpath(lib["container_path"])
    if not os.path.realpath(cpath).startswith(root + os.sep):
        return L("Points outside the library", "Peker utenfor biblioteket")
    try:
        st = os.lstat(cpath)
    except FileNotFoundError:
        return L("The file no longer exists", "Filen finnes ikke lenger")
    if not _stat.S_ISREG(st.st_mode):
        return L("Not a regular file", "Ikke en vanlig fil")
    if st.st_size != fi["size"] or abs(st.st_mtime - fi["mtime"]) > 1 or st.st_ino != fi["inode"]:
        return L("The file has changed since the scan – run a new scan", "Filen er endret siden skanningen – kjør ny skanning")
    if need_write and not os.access(os.path.dirname(cpath), os.W_OK):
        return read_only(lib)
    return None


def plan(choices: list[dict]) -> dict:
    """choices: [{"id": group id, "keep": path to keep}]"""
    with db.conn() as c:
        groups = {g["id"]: g for g in _load_groups(c)}
        managed = managed_paths(c)
        file_rows = {}
        all_paths = [f["path"] for ch in choices for f in groups.get(ch.get("id"), {}).get("files", [])]
        for i in range(0, len(all_paths), 900):
            chunk = all_paths[i:i + 900]
            q = ",".join("?" * len(chunk))
            for r in db.rows(c, f"SELECT path, size, alloc, mtime, inode, dev, nlink FROM files WHERE path IN ({q})", chunk):
                file_rows[r["path"]] = r
        items, claims, h = [], {}, hashlib.sha256()
        for ch in choices[:500]:
            g = groups.get(ch.get("id"))
            if not g:
                items.append({"id": ch.get("id"), "name": "?", "executable": False, "files": [],
                              "reason": L("The group no longer exists (a new analysis has run)",
                                          "Gruppen finnes ikke lenger (ny analyse er kjørt)")})
                continue
            keep = ch.get("keep") or next((f["path"] for f in g["files"] if f.get("keep")), None)
            paths = [f["path"] for f in g["files"]]
            base = {"id": g["id"], "name": g["name"], "kind": g["kind"], "keep": keep}
            if g["kind"] == "hardlink":
                items.append({**base, "executable": False, "files": [],
                              "reason": L("Hardlinks take no extra space", "Hardlenker tar ikke ekstra plass")})
                continue
            if keep not in paths:
                items.append({**base, "executable": False, "files": [],
                              "reason": L("The file to keep is not in the group", "Filen som skal beholdes er ikke i gruppen")})
                continue
            kf = next(f for f in g["files"] if f["path"] == keep)
            keep_c, _ = container_path(keep)
            if not keep_c or not os.path.isfile(keep_c):
                items.append({**base, "executable": False, "files": [],
                              "reason": L("The file to keep does not exist on disk", "Filen som skal beholdes finnes ikke på disk")})
                continue
            to_delete = []
            kr = file_rows.get(keep, {})
            for f in g["files"]:
                fr = file_rows.get(f["path"], {})
                if f["path"] == keep or (fr and fr.get("inode") == kr.get("inode") and fr.get("dev") == kr.get("dev")):
                    continue  # the same file as the kept one (hardlink)
                prot = bool(g["protected"]) and protection_applies()
                route = None
                if f["managed"]:
                    route, reason = _arr_route(c, f["path"], keep, kf.get("in_downloads", False))
                    if route:
                        reason = _check_file(f, file_rows.get(f["path"]), set(), prot, need_write=False)
                else:
                    reason = _check_file(f, file_rows.get(f["path"]), managed, prot)
                to_delete.append({"path": f["path"], "size": f["size"], "alloc": f.get("alloc"),
                                  "ok": reason is None, "reason": reason, "managed": f["managed"],
                                  "in_downloads": f["in_downloads"],
                                  "via": route["service"] if route and reason is None else None,
                                  "route": route if reason is None else None})
            ok = [f for f in to_delete if f["ok"]]
            for f in ok:
                claims[f["path"]] = f["alloc"] or f["size"]
                h.update((f["path"] + "|" + (f["via"] or "fs")).encode())
            h.update((g["id"] + "|" + keep).encode())
            items.append({**base, "executable": bool(ok), "files": to_delete,
                          "reason": None if ok else (to_delete[0]["reason"] if to_delete
                                                     else L("Nothing to delete", "Ingenting å slette")),
                          "keep_managed": kf.get("managed"), "warn_downloads": any(f["in_downloads"] for f in ok)})
        info = {p: {"dev": r["dev"], "inode": r["inode"], "nlink": r["nlink"]} for p, r in file_rows.items()}
        inode_paths: dict = {}
        for p, r in file_rows.items():
            inode_paths.setdefault((r["dev"], r["inode"]), []).append(p)
        # hardlinks outside the selection: ask the database for every known path of the inodes
        for (dev, ino) in list(inode_paths):
            inode_paths[(dev, ino)] = [x[0] for x in c.execute("SELECT path FROM files WHERE dev=? AND inode=?", (dev, ino))]
        freed, held = engine.freed_bytes(claims, info, inode_paths)
    return {"enabled": files_enabled(), "writable": writable_libraries(), "items": items,
            "files": len(claims), "freed": freed, "held": held, "token": h.hexdigest()[:24]}


def execute(choices: list[dict], token: str) -> dict:
    if not files_enabled():
        raise Forbidden(L("Deleting files is switched off under Settings → Deletion",
                          "Sletting av filer er slått av under Innstillinger → Sletting"))
    p = plan(choices)
    if p["token"] != token:
        raise Conflict(L("The selection or the analysis has changed since the summary was shown. Open it again.",
                         "Utvalget eller analysen er endret siden oppsummeringen ble vist. Åpne den på nytt."))
    results, deleted_bytes = [], 0
    with db.conn() as c:
        managed = managed_paths(c)
        for it in p["items"]:
            for f in it.get("files", []):
                if not f["ok"]:
                    results.append({"path": f["path"], "status": SKIPPED, "detail": f["reason"]})
                    continue
                # Check again right before deleting
                fi = db.rows(c, "SELECT path, size, alloc, mtime, inode, dev, nlink FROM files WHERE path=?", (f["path"],))
                if f.get("via"):
                    reason = _check_file(f, fi[0] if fi else None, set(), False, need_write=False)
                else:
                    reason = _check_file(f, fi[0] if fi else None, managed, False)
                keep_c, _ = container_path(it["keep"])
                if reason is None and not (keep_c and os.path.isfile(keep_c)):
                    reason = L("The file to keep no longer exists", "Filen som skal beholdes finnes ikke lenger")
                if reason:
                    status, detail = FAILED, reason
                else:
                    try:
                        if f.get("via"):
                            detail = _delete_via_arr(f["route"], f["path"], it["keep"])
                        else:
                            os.remove(container_path(f["path"])[0])
                            detail = fmt("Deleted (kept {k})", "Slettet (beholdt {k})", k=os.path.basename(it["keep"]))
                        status = DONE
                        deleted_bytes += f["alloc"] or f["size"] or 0
                    except ActionError as e:
                        status, detail = FAILED, e.msg
                    except OSError as e:
                        status, detail = FAILED, f"{type(e).__name__}: {e}"
                log_action(c, title=f"{it['name']}: {os.path.basename(f['path'])}", action="delete_file",
                           service=f.get("via") or "disk", status=status, detail=detail,
                           bytes_=f["alloc"] or f["size"] or 0, suggestion_id=it["id"])
                results.append({"path": f["path"], "status": status, "detail": detail})
    done = sum(r["status"] == DONE for r in results)
    if done:
        jobs.enqueue("refresh")
    return {"results": results, "done": done, "failed": sum(r["status"] == FAILED for r in results),
            "freed_estimate": min(deleted_bytes, p["freed"]) if p["freed"] else deleted_bytes}


def _delete_via_arr(route: dict, path: str, keep: str) -> dict:
    """Delete one file through Radarr/Sonarr and ask them to rescan, so the kept file is used."""
    k = os.path.basename(keep)
    if route["service"] == "radarr":
        base, h = _arr("radarr")
        movie = _req("GET", f"{base}/api/v3/movie/{route['movie_id']}", h).json()
        if not _same_folder(movie.get("path"), route["folder"]):
            raise ActionError(L("The folder in Radarr does not match the analysis – run a new refresh first",
                                "Mappen i Radarr stemmer ikke med analysen – kjør ny oppdatering først"))
        files = _req("GET", f"{base}/api/v3/moviefile", h, params={"movieId": route["movie_id"]}).json()
        mf = next((x for x in files if settings.map_service_path(x.get("path")) == path), None)
        if not mf:
            raise ActionError(L("Radarr no longer points to this file – run a new refresh first",
                                "Radarr peker ikke lenger på denne filen – kjør ny oppdatering først"))
        _req("DELETE", f"{base}/api/v3/moviefile/{mf['id']}", h)
        _req("POST", f"{base}/api/v3/command", h, json={"name": "RescanMovie", "movieId": route["movie_id"]})
        return fmt("Deleted in Radarr; Radarr rescans the folder and uses {k}",
                   "Slettet i Radarr; Radarr skanner mappen og tar i bruk {k}", k=k)
    base, h = _arr("sonarr")
    ef = _req("GET", f"{base}/api/v3/episodefile/{route['file_id']}", h).json()
    if settings.map_service_path(ef.get("path")) != path:
        raise ActionError(L("Sonarr no longer points to this file – run a new refresh first",
                            "Sonarr peker ikke lenger på denne filen – kjør ny oppdatering først"))
    _req("DELETE", f"{base}/api/v3/episodefile/{route['file_id']}", h)
    _req("POST", f"{base}/api/v3/command", h, json={"name": "RescanSeries", "seriesId": route["series_id"]})
    return fmt("Deleted in Sonarr; Sonarr rescans the folder and uses {k}",
               "Slettet i Sonarr; Sonarr skanner mappen og tar i bruk {k}", k=k)
