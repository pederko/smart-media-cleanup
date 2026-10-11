"""Background jobs: one worker thread (limits load on ZFS) and a simple scheduler."""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback

from . import db, scanner, settings, sync, updates
from .analysis import engine
from .i18n import L, fmt, store

log = logging.getLogger("smc.jobs")

KINDS = {
    "sync": L("Sync services", "Synkroniser tjenester"),
    "scan": L("Incremental file scan", "Inkrementell filskanning"),
    "scan_full": L("Full file scan", "Full filskanning"),
    "analyze": L("Analysis", "Analyse"),
    "refresh": L("Full refresh", "Full oppdatering"),
}

_q: "queue.Queue[int]" = queue.Queue()
_started = False
_lock = threading.Lock()

# Progress of running jobs is kept in memory. It is NOT written to the database while running:
# the jobs (scanner, analysis) hold write transactions themselves, and a separate write from the
# progress reporting would wait for them – a deadlock («database is locked»).
PROGRESS_INTERVAL = 0.5
_live: dict[int, dict] = {}
_live_lock = threading.Lock()


def _set_live(jid: int, progress: float, message) -> None:
    with _live_lock:
        _live[jid] = {"progress": progress, "message": message}


def _clear_live(jid: int) -> None:
    with _live_lock:
        _live.pop(jid, None)


def overlay(rows: list[dict]) -> list[dict]:
    """Overlays fresh in-memory progress on job rows from the database."""
    with _live_lock:
        live = dict(_live)
    for r in rows:
        if r.get("status") == "running" and r.get("id") in live:
            r.update(live[r["id"]])
    return rows


def enqueue(kind: str) -> dict:
    if kind not in KINDS:
        raise ValueError(kind)
    with db.conn() as c:
        existing = c.execute("SELECT id FROM jobs WHERE kind=? AND status IN ('queued','running')", (kind,)).fetchone()
        if existing:
            return {"id": existing[0], "duplicate": True}
        jid = c.execute("INSERT INTO jobs(kind,status,progress,message,started) VALUES(?,?,?,?,?)",
                        (kind, "queued", 0, store(L("Queued", "I kø")), None)).lastrowid
    _q.put(jid)
    return {"id": jid, "duplicate": False}


def _run(jid: int, kind: str):
    last_write = [0.0]
    base = [0.0, 1.0]  # for composite jobs

    def progress(frac: float, msg):
        now = time.time()
        if now - last_write[0] < PROGRESS_INTERVAL and frac < 1.0:
            return
        last_write[0] = now
        p = base[0] + (base[1] - base[0]) * max(0.0, min(1.0, frac))
        _set_live(jid, round(p, 3), msg)

    def phase(lo, hi, fn, *a):
        base[0], base[1] = lo, hi
        last_write[0] = 0
        return fn(progress, *a)

    if kind == "sync":
        return phase(0, 1, sync.run)
    if kind == "scan":
        return phase(0, 1, scanner.scan, False)
    if kind == "scan_full":
        return phase(0, 1, scanner.scan, True)
    if kind == "analyze":
        return phase(0, 1, engine.run)
    if kind == "refresh":
        with db.conn() as c:
            last_full = db.kv_get(c, "last_full_scan", 0) or 0
        full = time.time() - last_full > settings.get()["scanner"]["full_scan_days"] * 86400
        r1 = phase(0.0, 0.35, sync.run)
        r2 = phase(0.35, 0.85, scanner.scan, full)
        r3 = phase(0.85, 1.0, engine.run)
        return {"sync": r1, "scan": r2, "analysis": r3}


def _worker():
    while True:
        jid = _q.get()
        with db.conn() as c:
            row = c.execute("SELECT kind FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                continue
            c.execute("UPDATE jobs SET status='running', started=?, message=? WHERE id=?",
                      (time.time(), store(L("Starting", "Starter")), jid))
        kind = row[0]
        _set_live(jid, 0.0, L("Starting", "Starter"))
        try:
            result = _run(jid, kind)
            with db.conn() as c:
                c.execute("UPDATE jobs SET status='done', progress=1, finished=?, message=?, log=? WHERE id=?",
                          (time.time(), store(L("Done", "Ferdig")), _short(result), jid))
        except Exception as e:
            log.exception("Job %s failed", kind)
            with db.conn() as c:
                c.execute("UPDATE jobs SET status='failed', finished=?, error=?, message=? WHERE id=?",
                          (time.time(), traceback.format_exc()[-4000:], store(fmt("Failed: {e}", "Feilet: {e}", e=e)), jid))
        finally:
            _clear_live(jid)


def _short(obj) -> str:
    import json
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)[:4000]
    except Exception:
        return str(obj)[:4000]


def _scheduler():
    time.sleep(20)
    while True:
        try:
            s = settings.get()
            with db.conn() as c:
                last_sync = db.kv_get(c, "last_sync", 0) or 0
                last_scan = (db.kv_get(c, "last_scan", {}) or {}).get("time", 0)
            now = time.time()
            if (now - last_sync > s["sync"]["interval_hours"] * 3600
                    and now - last_scan > s["scanner"]["interval_hours"] * 3600):
                enqueue("refresh")
            elif now - last_sync > s["sync"]["interval_hours"] * 3600:
                enqueue("sync")
                enqueue("analyze")
            elif now - last_scan > s["scanner"]["interval_hours"] * 3600:
                enqueue("refresh")
            updates.check()
            try:
                from . import swaps
                swaps.poll()
            except Exception:
                log.exception("Following up swaps failed")
            with db.conn() as c:
                last_backup = db.kv_get(c, "last_backup", 0) or 0
            if now - last_backup > 86400:
                path = db.backup()
                with db.conn() as c:
                    db.kv_set(c, "last_backup", now)
                log.info("Backup written to %s", path)
        except Exception:
            log.exception("Scheduler failed")
        time.sleep(300)


def start(schedule: bool = True):
    global _started
    with _lock:
        if _started:
            return
        _started = True
    with db.conn() as c:
        c.execute("UPDATE jobs SET status='aborted', message=? WHERE status IN ('queued','running')",
                  (store(L("Aborted by restart", "Avbrutt ved omstart")),))
        c.execute("DELETE FROM jobs WHERE id NOT IN (SELECT id FROM jobs ORDER BY id DESC LIMIT 200)")
        needs = db.kv_get(c, "needs_analysis")
        if needs:
            db.kv_set(c, "needs_analysis", False)
    threading.Thread(target=_worker, name="smc-worker", daemon=True).start()
    if schedule:
        threading.Thread(target=_scheduler, name="smc-scheduler", daemon=True).start()
    if needs:
        enqueue("analyze")
