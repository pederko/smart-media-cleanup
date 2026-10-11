"""Inkrementell filskanner (kun lesing).

- Mapper med uendret mtime hopper over stat() av filene sine (filer lagt til/fjernet endrer
  alltid mappens mtime). Undermapper besøkes alltid, men readdir er billig.
- Full skanning (stat av alt) kjøres periodisk for å fange endringer i eksisterende filer.
- Lav belastning: valgfri pause per 1000 oppføringer.
- Delvis hash (start/midt/slutt) beregnes kun for filer som har samme størrelse som en annen fil.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Callable

from . import db, settings

VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".m2ts", ".iso", ".wmv", ".mov", ".mpg", ".mpeg", ".vob", ".webm", ".img"}
EXTRA_DIRS = {"featurettes", "extras", "behind the scenes", "deleted scenes", "interviews", "scenes",
              "shorts", "trailers", "other", "sample", "samples", "specials-extras"}
EXTRA_RE = re.compile(r"(^|[.\-_ ])(sample|trailer)([.\-_ ]|$)", re.I)
CHUNK = 4 * 1024 * 1024
# Kun for tester med glisne (sparse) filer: bruk tilsynelatende størrelse som allokert størrelse.
APPARENT_ALLOC = os.environ.get("SMC_TEST_APPARENT_SIZE") == "1"

Progress = Callable[[float, str], None]


def is_extra(rel_path: str) -> bool:
    parts = rel_path.lower().split("/")
    if any(p in EXTRA_DIRS for p in parts[:-1]):
        return True
    stem = os.path.splitext(parts[-1])[0]
    return bool(EXTRA_RE.search(stem))


def partial_hash(path: str, size: int) -> str:
    h = hashlib.sha256(str(size).encode())
    with open(path, "rb", buffering=0) as f:
        offsets = [0] if size <= 3 * CHUNK else [0, size // 2 - CHUNK // 2, size - CHUNK]
        for off in offsets:
            f.seek(off)
            h.update(f.read(CHUNK))
    return h.hexdigest()


def scan(progress: Progress, full: bool = False) -> dict:
    s = settings.get()
    throttle = s["scanner"]["throttle_ms_per_1000"] / 1000.0
    libs = [l for l in s["libraries"] if l.get("container_path")]
    started = time.time()
    with db.conn() as c:
        scan_id = c.execute("INSERT INTO scans(started,kind,status) VALUES(?,?,?)",
                            (started, "full" if full else "incremental", "running")).lastrowid
        prev_total = c.execute("SELECT COUNT(*) FROM files").fetchone()[0] or 1
    seen = 0
    stats_done = 0
    missing: list[str] = []

    for lib in libs:
        root_c = lib["container_path"].rstrip("/")
        root_h = lib["host_path"].rstrip("/")
        if not os.path.isdir(root_c):
            missing.append(lib["name"])
            continue
        with db.conn() as c:
            prev_dirs = {r[0]: r[1] for r in c.execute("SELECT path, mtime FROM dirs WHERE library=?", (lib["name"],))}
            c.execute("BEGIN")
            pending = 0
            stack = [root_c]
            while stack:
                d = stack.pop()
                try:
                    dst = os.stat(d)
                except OSError:
                    continue
                rel_dir = d[len(root_c):]
                host_dir = root_h + rel_dir
                changed = full or prev_dirs.get(host_dir) != dst.st_mtime
                try:
                    entries = list(os.scandir(d))
                except OSError:
                    continue
                for e in entries:
                    seen += 1
                    if seen % 1000 == 0:
                        if throttle:
                            time.sleep(throttle)
                        progress(min(0.95, seen / prev_total * 0.9), f"Skanner {lib['name']}: {seen} oppføringer")
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                            continue
                        if not changed or not e.is_file(follow_symlinks=False):
                            continue
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    stats_done += 1
                    rel = e.path[len(root_c):].lstrip("/")
                    ext = os.path.splitext(e.name)[1].lower()
                    c.execute(
                        """INSERT INTO files(path,library,dir,name,ext,size,alloc,inode,dev,nlink,mtime,is_video,is_extra,scan_id)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(path) DO UPDATE SET size=excluded.size, alloc=excluded.alloc,
                             inode=excluded.inode, dev=excluded.dev, nlink=excluded.nlink, mtime=excluded.mtime,
                             is_video=excluded.is_video, is_extra=excluded.is_extra, scan_id=excluded.scan_id,
                             library=excluded.library, dir=excluded.dir""",
                        (root_h + "/" + rel, lib["name"], host_dir, e.name, ext, st.st_size,
                         st.st_size if APPARENT_ALLOC else (getattr(st, "st_blocks", 0) * 512 or st.st_size), st.st_ino, st.st_dev, st.st_nlink,
                         st.st_mtime, 1 if ext in VIDEO_EXT else 0, 1 if is_extra(rel) else 0, scan_id))
                    pending += 1
                if not changed:
                    c.execute("UPDATE files SET scan_id=? WHERE dir=?", (scan_id, host_dir))
                c.execute("INSERT INTO dirs(path,library,mtime,scan_id) VALUES(?,?,?,?) "
                          "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, scan_id=excluded.scan_id",
                          (host_dir, lib["name"], dst.st_mtime, scan_id))
                pending += 1
                if pending >= 5000:
                    c.execute("COMMIT")
                    c.execute("BEGIN")
                    pending = 0
            # Fjern det som ikke lenger finnes i dette biblioteket
            c.execute("DELETE FROM files WHERE library=? AND (scan_id IS NULL OR scan_id<>?)", (lib["name"], scan_id))
            c.execute("DELETE FROM dirs WHERE library=? AND (scan_id IS NULL OR scan_id<>?)", (lib["name"], scan_id))
            c.execute("COMMIT")

    with db.conn() as c:
        # Biblioteker som er fjernet fra konfigurasjonen
        names = [l["name"] for l in libs if l["name"] not in missing]
        if names:
            ph = ",".join("?" * len(names))
            c.execute(f"DELETE FROM files WHERE library NOT IN ({ph})", names)
            c.execute(f"DELETE FROM dirs WHERE library NOT IN ({ph})", names)

    progress(0.95, "Beregner delvis hash for mulige duplikater")
    hashed = hash_candidates(s["scanner"]["hash_min_size_mb"] * 1024 * 1024, libs)

    with db.conn() as c:
        n, b = c.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM files").fetchone()
        status = "ok" if not missing else "delvis: mangler " + ", ".join(missing)
        c.execute("UPDATE scans SET finished=?, files=?, bytes=?, status=? WHERE id=?",
                  (time.time(), n, b, status, scan_id))
        db.kv_set(c, "last_scan", {"time": time.time(), "full": full, "files": n, "bytes": b,
                                   "stat_calls": stats_done, "hashed": hashed, "missing": missing,
                                   "duration": time.time() - started})
        if full:
            db.kv_set(c, "last_full_scan", time.time())
    progress(1.0, f"Skanning ferdig: {n} filer")
    return {"files": n, "bytes": b, "stat_calls": stats_done, "hashed": hashed, "missing": missing}


def hash_candidates(min_size: int, libs: list[dict]) -> int:
    """Delvis hash for filer med samme størrelse men ulik inode. Caches på (størrelse, mtime)."""
    to_container = {l["host_path"].rstrip("/"): l["container_path"].rstrip("/") for l in libs}
    count = 0
    with db.conn() as c:
        rows = db.rows(c, """
            SELECT path, size, mtime, phash, phash_size, phash_mtime FROM files
            WHERE size >= ? AND size IN (
              SELECT size FROM files WHERE size >= ? GROUP BY size
              HAVING COUNT(DISTINCT dev || ':' || inode) > 1)""", (min_size, min_size))
        for r in rows:
            if r["phash"] and r["phash_size"] == r["size"] and r["phash_mtime"] == r["mtime"]:
                continue
            cpath = None
            for h, cp in to_container.items():
                if r["path"].startswith(h + "/"):
                    cpath = cp + r["path"][len(h):]
                    break
            if not cpath:
                continue
            try:
                ph = partial_hash(cpath, r["size"])
            except OSError:
                continue
            c.execute("UPDATE files SET phash=?, phash_size=?, phash_mtime=? WHERE path=?",
                      (ph, r["size"], r["mtime"], r["path"]))
            count += 1
    return count
