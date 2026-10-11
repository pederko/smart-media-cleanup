"""Fetches data from the services and stores it in SQLite. Each service fails independently."""
from __future__ import annotations

import json
import time
from typing import Callable

from . import db, settings
from .clients import arr, plex, qbit, seerr, tautulli, truenas
from .clients.base import ServiceError
from .i18n import L, fmt, text

Progress = Callable[[float, str], None]

STATUS_FUNCS = {
    "radarr": arr.status, "sonarr": arr.status, "plex": plex.status,
    "tautulli": tautulli.status, "seerr": seerr.status, "truenas": truenas.status,
    "qbittorrent": qbit.status,
}


def test_service(name: str, cfg: dict | None = None) -> dict:
    s = settings.get()
    cfg = cfg or s["services"][name]
    try:
        info = STATUS_FUNCS[name](cfg)
        return {"ok": True, **info}
    except ServiceError as e:
        return {"ok": False, "error": e.msg}
    except Exception as e:  # unexpected – report, do not crash
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _set_status(c, name: str, ok: bool, message, count: int | None = None, configured: bool = True):
    st = db.kv_get(c, "service_status", {}) or {}
    prev = st.get(name, {})
    st[name] = {"ok": ok, "configured": configured, "message": message, "checked": time.time(),
                "last_success": time.time() if ok else prev.get("last_success"),
                "count": count if ok else prev.get("count")}
    db.kv_set(c, "service_status", st)


def _replace(c, table: str, rows: list[tuple]):
    if not rows:
        c.execute(f"DELETE FROM {table}")
        return
    ph = ",".join("?" * len(rows[0]))
    c.execute("BEGIN")
    try:
        c.execute(f"DELETE FROM {table}")
        c.executemany(f"INSERT OR REPLACE INTO {table} VALUES({ph})", rows)
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def run(progress: Progress) -> dict:
    s = settings.get()
    svc = s["services"]
    mp = lambda p: settings.map_service_path(p, s)  # noqa: E731
    result: dict[str, str] = {}

    def step(name: str, frac: float, fn: Callable[[Progress], tuple[int, str]]):
        if not svc[name].get("enabled") or not svc[name].get("url"):
            result[name] = "not configured"
            with db.conn() as c:
                _set_status(c, name, False, L("Not configured", "Ikke konfigurert"), configured=False)
            return
        progress(frac, fmt("Fetching from {n}", "Henter fra {n}", n=name.capitalize()))
        try:
            count, msg = fn(lambda f, m: progress(frac + f * 0.15, m))
            with db.conn() as c:
                _set_status(c, name, True, msg, count)
            result[name] = text(msg, "en")
        except Exception as e:
            err = e.msg if isinstance(e, ServiceError) else f"{type(e).__name__}: {e}"
            with db.conn() as c:
                _set_status(c, name, False, err)
            result[name] = f"error: {text(err, 'en')}"

    def _roots(name):
        try:
            return arr.root_folders(svc[name])
        except Exception:  # optional – the mapping helper simply has less to go on
            return None

    def _store_roots(c, name, roots):
        if roots is not None:
            all_roots = db.kv_get(c, "root_folders", {}) or {}
            all_roots[name] = roots
            db.kv_set(c, "root_folders", all_roots)

    def do_radarr(p):
        rows = arr.fetch_radarr(svc["radarr"], mp)
        roots = _roots("radarr")
        with db.conn() as c:
            _replace(c, "radarr_movies", rows)
            _store_roots(c, "radarr", roots)
        return len(rows), fmt("{n} movies", "{n} filmer", n=len(rows))

    def do_sonarr(p):
        series, files, skipped = arr.fetch_sonarr(svc["sonarr"], mp, p)
        roots = _roots("sonarr")
        with db.conn() as c:
            _store_roots(c, "sonarr", roots)
            _replace(c, "sonarr_series", series)
            _replace(c, "sonarr_files", files)
        msg = fmt("{n} series, {f} episode files", "{n} serier, {f} episodefiler", n=len(series), f=len(files))
        if skipped:
            msg = fmt("{m} ({k} skipped: {names})", "{m} ({k} hoppet over: {names})", m=msg, k=len(skipped),
                      names=", ".join(skipped[:5]) + ("…" if len(skipped) > 5 else ""))
        return len(series), msg

    def do_plex(p):
        items, parts, libs = plex.fetch(svc["plex"], mp, s["protection"]["plex_labels"], p)
        with db.conn() as c:
            _replace(c, "plex_items", items)
            _replace(c, "plex_parts", parts)
            db.kv_set(c, "plex_libraries", libs)
        return len(items), fmt("{n} items in {l} libraries", "{n} elementer i {l} bibliotek", n=len(items), l=len(libs))

    def do_tautulli(p):
        with db.conn() as c:
            last = c.execute("SELECT MAX(date) FROM plays").fetchone()[0]
        rows = tautulli.fetch_history(svc["tautulli"], last, p)
        with db.conn() as c:
            if rows:
                c.execute("BEGIN")
                c.executemany("INSERT OR REPLACE INTO plays VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                c.execute("COMMIT")
            total = c.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
        return total, fmt("{t} plays ({n} new/updated)", "{t} avspillinger ({n} nye/oppdatert)", t=total, n=len(rows))

    def do_seerr(p):
        rows = seerr.fetch_requests(svc["seerr"])
        with db.conn() as c:
            _replace(c, "requests", rows)
        return len(rows), fmt("{n} requests", "{n} forespørsler", n=len(rows))

    def do_truenas(p):
        info = truenas.fetch(svc["truenas"])
        with db.conn() as c:
            db.kv_set(c, "truenas", {**info, "fetched": time.time()})
        n = info.get("root_snapshots")
        return len(info["datasets"]), fmt("{d} datasets, snapshots on the root dataset: {n}",
                                          "{d} datasett, snapshots på rotdatasettet: {n}", d=len(info["datasets"]),
                                          n=n if n is not None else "?")

    def do_qbit(p):
        with qbit.Client(svc["qbittorrent"]) as q:
            torrents = q.torrents()
        from .torrents import ERROR_STATES, STOPPED_STATES
        seeding = sum(1 for t in torrents if (t.get("progress") or 0) >= 1 and t.get("state") not in STOPPED_STATES | ERROR_STATES)
        return len(torrents), fmt("{n} torrents, {s} seeding", "{n} torrenter, {s} deler", n=len(torrents), s=seeding)

    step("radarr", 0.0, do_radarr)
    step("sonarr", 0.15, do_sonarr)
    step("plex", 0.35, do_plex)
    step("tautulli", 0.6, do_tautulli)
    step("seerr", 0.8, do_seerr)
    step("truenas", 0.9, do_truenas)
    step("qbittorrent", 0.95, do_qbit)
    with db.conn() as c:
        db.kv_set(c, "last_sync", time.time())
    progress(1.0, L("Sync finished", "Synkronisering ferdig"))
    return result


def reset_history():
    """Used if the Tautulli database has been replaced."""
    with db.conn() as c:
        c.execute("DELETE FROM plays")
        db.audit(c, "reset_history", {})


__all__ = ["run", "test_service", "reset_history", "json"]
