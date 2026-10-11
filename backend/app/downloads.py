"""Nedlastingsmappen (f.eks. tmp): hva ligger der, er det importert, og hva kan slettes.

Status per toppmappe/fil i nedlastingsbiblioteket:
  * hardlenket  – samme fil ligger i biblioteket (hardlink). Sletting frigjør ingenting
                  før biblioteksfilen også er borte.
  * kopiert     – identisk kopi (størrelse + delvis hash) finnes i biblioteket. Trygt å slette.
  * ikke_importert – ingen kopi i biblioteket. Kan være uferdig, under deling, eller glemt.
Sletting skjer direkte på disk og krever samme to valg som duplikater (bryter + skrivetilgang).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat as _stat
import time
from collections import defaultdict

from . import db, jobs, settings
from .analysis import engine
from .dupes import enabled as files_enabled, writable_libraries

DAY = 86400
VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".m2ts", ".iso", ".wmv", ".mov", ".mpg", ".mpeg", ".webm"}


def _dl_libs() -> list[dict]:
    return [l for l in settings.get()["libraries"] if l.get("kind") == "downloads"]


def _entries(c, lib: dict) -> list[dict]:
    root = lib["host_path"].rstrip("/")
    files = db.rows(c, "SELECT path, size, alloc, mtime, inode, dev, nlink, ext, phash, is_video FROM files WHERE library=?",
                    (lib["name"],))
    # inoder og innhold som finnes i ikke-nedlastingsbiblioteker
    dl_names = {l["name"] for l in _dl_libs()}
    ph = ",".join("?" * len(dl_names))
    lib_inodes = {(r[0], r[1]) for r in c.execute(f"SELECT dev, inode FROM files WHERE library NOT IN ({ph})", list(dl_names))}
    lib_hash = {(r[0], r[1]) for r in c.execute(
        f"SELECT size, phash FROM files WHERE phash IS NOT NULL AND library NOT IN ({ph})", list(dl_names))}
    # Hvilken tittel i biblioteket svarer filen til (via identisk innhold eller hardlink)?
    title_by_inode, title_by_hash = {}, {}
    for r in c.execute(f"""SELECT f.dev, f.inode, f.size, f.phash, t.key, t.name FROM files f
                           JOIN file_title ft ON ft.path=f.path JOIN titles t ON t.key=ft.title_key
                           WHERE f.library NOT IN ({ph}) AND f.is_video=1""", list(dl_names)):
        title_by_inode[(r[0], r[1])] = (r[4], r[5])
        if r[3]:
            title_by_hash[(r[2], r[3])] = (r[4], r[5])

    groups: dict[str, list[dict]] = defaultdict(list)
    for f in files:
        rel = f["path"][len(root) + 1:]
        groups[rel.split("/", 1)[0]].append(f)

    now = time.time()
    out = []
    for top, fs in groups.items():
        uniq = {(f["dev"], f["inode"]): f for f in fs}.values()
        size = sum(f["alloc"] or f["size"] for f in uniq)
        videos = [f for f in fs if (f["ext"] or "").lower() in VIDEO_EXT]
        linked = [f for f in videos if (f["dev"], f["inode"]) in lib_inodes]
        copied = [f for f in videos if f not in linked and f["phash"] and (f["size"], f["phash"]) in lib_hash]
        if videos and len(linked) == len(videos):
            status = "hardlenket"
        elif videos and len(linked) + len(copied) == len(videos):
            status = "kopiert"
        elif not videos:
            status = "uten_video"
        else:
            status = "ikke_importert"
        title = None
        for f in videos:
            title = title_by_inode.get((f["dev"], f["inode"])) or (title_by_hash.get((f["size"], f["phash"])) if f["phash"] else None)
            if title:
                break
        newest = max(f["mtime"] for f in fs)
        age_days = (now - newest) / DAY
        # frigjøres hvis hele mappen slettes: hardlenkede filer frigjør ingenting
        freed = sum((f["alloc"] or f["size"]) for f in uniq if (f["dev"], f["inode"]) not in lib_inodes and f["nlink"] <= 1)
        if status == "hardlenket":
            advice, why = "behold", "Hardlenket til biblioteket – sletting frigjør ingenting nå"
        elif age_days < 14:
            advice, why = "behold", f"Endret for {age_days:.0f} dager siden – kan fortsatt være under nedlasting, import eller deling"
        elif status == "kopiert":
            advice, why = "slett", "Identisk kopi finnes i biblioteket"
        elif status == "uten_video":
            advice, why = "slett", "Inneholder ingen videofiler (rester etter nedlasting)"
        elif age_days >= 60:
            advice, why = "vurder", f"Ikke importert, og ikke endret på {age_days:.0f} dager"
        else:
            advice, why = "vurder", "Ikke importert til biblioteket"
        out.append({
            "name": top, "path": f"{root}/{top}", "library": lib["name"], "is_dir": len(fs) > 1 or "/" in fs[0]["path"][len(root) + 1:],
            "files": len(fs), "videos": len(videos), "size": size, "freed": freed, "mtime": newest,
            "age_days": round(age_days, 1), "status": status, "advice": advice, "why": why,
            "title_key": title[0] if title else None, "title_name": title[1] if title else None,
        })
    return out


def overview(library: str = "", status: str = "", advice: str = "", q: str = "", sort: str = "size", order: str = "desc") -> dict:
    libs = _dl_libs()
    if library:
        libs = [l for l in libs if l["name"] == library]
    with db.conn() as c:
        items = [e for lib in libs for e in _entries(c, lib)]
    summary = {"count": len(items), "size": sum(i["size"] for i in items), "by_status": {}, "by_advice": {}}
    for key, field in (("by_status", "status"), ("by_advice", "advice")):
        for i in items:
            d = summary[key].setdefault(i[field], {"count": 0, "size": 0, "freed": 0})
            d["count"] += 1
            d["size"] += i["size"]
            d["freed"] += i["freed"]
    if status:
        items = [i for i in items if i["status"] == status]
    if advice:
        items = [i for i in items if i["advice"] == advice]
    if q:
        items = [i for i in items if q.lower() in i["name"].lower() or q.lower() in (i["title_name"] or "").lower()]
    keyf = {"size": lambda i: i["size"], "freed": lambda i: i["freed"], "age": lambda i: i["age_days"],
            "name": lambda i: i["name"].lower()}
    items.sort(key=keyf.get(sort, keyf["size"]), reverse=order != "asc")
    return {"libraries": [l["name"] for l in _dl_libs()], "summary": summary, "items": items,
            "files_enabled": files_enabled(), "writable": writable_libraries()}


# ------------------------------------------------------------------ sletting

def _resolve(host_path: str) -> tuple[str | None, dict | None]:
    for lib in _dl_libs():
        h = lib["host_path"].rstrip("/")
        if host_path.startswith(h + "/") and "/" not in host_path[len(h) + 1:]:
            return lib["container_path"].rstrip("/") + host_path[len(h):], lib
    return None, None


def _check(path: str) -> str | None:
    cpath, lib = _resolve(path)
    if not cpath:
        return "Bare oppføringer rett under nedlastingsmappen kan slettes her"
    root = os.path.realpath(lib["container_path"])
    if os.path.realpath(cpath) == root or not os.path.realpath(cpath).startswith(root + os.sep):
        return "Peker utenfor nedlastingsmappen"
    try:
        st = os.lstat(cpath)
    except FileNotFoundError:
        return "Finnes ikke lenger"
    if _stat.S_ISLNK(st.st_mode):
        return "Er en symlenke"
    if not os.access(os.path.dirname(cpath), os.W_OK):
        return "Ingen skrivetilgang (mappen er montert :ro)"
    return None


def plan(paths: list[str]) -> dict:
    data = overview()
    by_path = {i["path"]: i for i in data["items"]}
    items, h = [], hashlib.sha256()
    for p in list(dict.fromkeys(paths))[:500]:
        e = by_path.get(p)
        if not e:
            items.append({"path": p, "name": os.path.basename(p), "ok": False, "reason": "Finnes ikke i siste skanning"})
            continue
        reason = _check(p)
        items.append({**e, "ok": reason is None, "reason": reason})
        if reason is None:
            h.update(f"{p}|{e['size']}|{e['mtime']}".encode())
    ok = [i for i in items if i["ok"]]
    return {"enabled": files_enabled(), "items": items, "count": len(ok), "freed": sum(i["freed"] for i in ok),
            "size": sum(i["size"] for i in ok), "token": h.hexdigest()[:24]}


def execute(paths: list[str], token: str) -> dict:
    if not files_enabled():
        raise PermissionError("Sletting av filer er slått av under Innstillinger → Sletting")
    p = plan(paths)
    if p["token"] != token:
        raise ValueError("Innholdet er endret siden oppsummeringen ble vist. Åpne den på nytt.")
    results = []
    with db.conn() as c:
        for it in p["items"]:
            if not it["ok"]:
                results.append({"path": it["path"], "status": "hoppet over", "detail": it["reason"]})
                continue
            reason = _check(it["path"])
            if reason:
                status, detail = "feilet", reason
            else:
                cpath, _ = _resolve(it["path"])
                try:
                    if os.path.isdir(cpath):
                        shutil.rmtree(cpath)
                    else:
                        os.remove(cpath)
                    status, detail = "utført", f"Slettet ({it['files']} filer)"
                except OSError as e:
                    status, detail = "feilet", f"{type(e).__name__}: {e}"
            c.execute("INSERT INTO actions(ts,suggestion_id,title_key,title,action,service,status,detail,bytes) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (time.time(), None, it.get("title_key"), f"{it['library']}: {it['name']}", "delete_download",
                       "filsystem", status, detail, it["freed"] if status == "utført" else 0))
            db.audit(c, "delete_download", {"path": it["path"], "status": status, "detail": detail})
            results.append({"path": it["path"], "status": status, "detail": detail})
    done = sum(r["status"] == "utført" for r in results)
    if done:
        jobs.enqueue("refresh")
    return {"results": results, "done": done, "failed": sum(r["status"] == "feilet" for r in results),
            "freed_estimate": sum(i["freed"] for i in p["items"] if i["ok"] and any(
                r["path"] == i["path"] and r["status"] == "utført" for r in results))}


__all__ = ["overview", "plan", "execute", "engine"]
