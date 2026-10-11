"""The downloads folder: what is there, has it been imported, and what can be deleted.

Status per top-level folder/file in a downloads library:
  * hardlinked   – the same file is in a library (hardlink). Deleting frees nothing until the
                   library file is gone too.
  * copied       – an identical copy (size + partial hash) exists in a library. Safe to delete.
  * not_imported – no copy in a library. May be unfinished, seeding, or forgotten.
  * no_video     – no video files (leftovers from a download).
Deletion happens directly on disk and needs the same two choices as duplicates (switch + write access).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import time
from collections import defaultdict

from . import db, jobs, settings
from .actions import DONE, FAILED, SKIPPED, log_action
from .fsops import VIDEO_EXT, check_entry, files_enabled, writable_libraries
from .i18n import L, Conflict, Forbidden, fmt

DAY = 86400


def _dl_libs() -> list[dict]:
    return [l for l in settings.get()["libraries"] if l.get("kind") == "downloads"]


def _entries(c, lib: dict) -> list[dict]:
    root = lib["host_path"].rstrip("/")
    files = db.rows(c, "SELECT path, size, alloc, mtime, inode, dev, nlink, ext, phash, is_video FROM files WHERE library=?",
                    (lib["name"],))
    # inodes and content that exist in non-download libraries
    dl_names = {l["name"] for l in _dl_libs()}
    ph = ",".join("?" * len(dl_names))
    lib_inodes = {(r[0], r[1]) for r in c.execute(f"SELECT dev, inode FROM files WHERE library NOT IN ({ph})", list(dl_names))}
    lib_hash = {(r[0], r[1]) for r in c.execute(
        f"SELECT size, phash FROM files WHERE phash IS NOT NULL AND library NOT IN ({ph})", list(dl_names))}
    # Which library title does the file correspond to (identical content or hardlink)?
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
            status = "hardlinked"
        elif videos and len(linked) + len(copied) == len(videos):
            status = "copied"
        elif not videos:
            status = "no_video"
        else:
            status = "not_imported"
        title = None
        for f in videos:
            title = title_by_inode.get((f["dev"], f["inode"])) or (title_by_hash.get((f["size"], f["phash"])) if f["phash"] else None)
            if title:
                break
        newest = max(f["mtime"] for f in fs)
        age_days = (now - newest) / DAY
        # freed if the whole folder is deleted: hardlinked files free nothing
        freed = sum((f["alloc"] or f["size"]) for f in uniq if (f["dev"], f["inode"]) not in lib_inodes and f["nlink"] <= 1)
        if status == "hardlinked":
            advice, why = "keep", L("Hardlinked to the library – deleting frees nothing now",
                                    "Hardlenket til biblioteket – sletting frigjør ingenting nå")
        elif age_days < 14:
            advice, why = "keep", fmt("Changed {d:.0f} days ago – may still be downloading, importing or seeding",
                                      "Endret for {d:.0f} dager siden – kan fortsatt være under nedlasting, import eller deling",
                                      d=age_days)
        elif status == "copied":
            advice, why = "delete", L("An identical copy exists in the library", "Identisk kopi finnes i biblioteket")
        elif status == "no_video":
            advice, why = "delete", L("Contains no video files (leftovers from a download)",
                                      "Inneholder ingen videofiler (rester etter nedlasting)")
        elif age_days >= 60:
            advice, why = "consider", fmt("Not imported, and not changed for {d:.0f} days",
                                          "Ikke importert, og ikke endret på {d:.0f} dager", d=age_days)
        else:
            advice, why = "consider", L("Not imported to the library", "Ikke importert til biblioteket")
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


# ------------------------------------------------------------------ deletion

def _check(path: str):
    return check_entry(path, top_level_of="downloads")[2]


def plan(paths: list[str]) -> dict:
    data = overview()
    by_path = {i["path"]: i for i in data["items"]}
    items, h = [], hashlib.sha256()
    for p in list(dict.fromkeys(paths))[:500]:
        e = by_path.get(p)
        if not e:
            items.append({"path": p, "name": os.path.basename(p), "ok": False,
                          "reason": L("Not in the latest scan", "Finnes ikke i siste skanning")})
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
        raise Forbidden(L("Deleting files is switched off under Settings → Deletion",
                          "Sletting av filer er slått av under Innstillinger → Sletting"))
    p = plan(paths)
    if p["token"] != token:
        raise Conflict(L("The content has changed since the summary was shown. Open it again.",
                         "Innholdet er endret siden oppsummeringen ble vist. Åpne den på nytt."))
    results = []
    with db.conn() as c:
        for it in p["items"]:
            if not it["ok"]:
                results.append({"path": it["path"], "status": SKIPPED, "detail": it["reason"]})
                continue
            cpath, _lib, reason = check_entry(it["path"], top_level_of="downloads")
            if reason:
                status, detail = FAILED, reason
            else:
                try:
                    if os.path.isdir(cpath):
                        shutil.rmtree(cpath)
                    else:
                        os.remove(cpath)
                    status, detail = DONE, fmt("Deleted ({n} files)", "Slettet ({n} filer)", n=it["files"])
                except OSError as e:
                    status, detail = FAILED, f"{type(e).__name__}: {e}"
            log_action(c, title=f"{it['library']}: {it['name']}", action="delete_download", service="disk",
                       status=status, detail=detail, bytes_=it["freed"], title_key=it.get("title_key"))
            results.append({"path": it["path"], "status": status, "detail": detail})
    done = sum(r["status"] == DONE for r in results)
    if done:
        jobs.enqueue("refresh")
    return {"results": results, "done": done, "failed": sum(r["status"] == FAILED for r in results),
            "freed_estimate": sum(i["freed"] for i in p["items"] if i["ok"] and any(
                r["path"] == i["path"] and r["status"] == DONE for r in results))}
