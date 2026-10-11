"""Henter data fra tjenestene og lagrer i SQLite. Hver tjeneste feiler uavhengig."""
from __future__ import annotations

import json
import time
from typing import Callable

from . import db, settings
from .clients import arr, plex, seerr, tautulli, truenas
from .clients.base import ServiceError

Progress = Callable[[float, str], None]

STATUS_FUNCS = {
    "radarr": arr.status, "sonarr": arr.status, "plex": plex.status,
    "tautulli": tautulli.status, "seerr": seerr.status, "truenas": truenas.status,
}


def test_service(name: str, cfg: dict | None = None) -> dict:
    s = settings.get()
    cfg = cfg or s["services"][name]
    try:
        info = STATUS_FUNCS[name](cfg)
        return {"ok": True, **info}
    except ServiceError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # uventet – rapporter, ikke krasj
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _set_status(c, name: str, ok: bool, message: str, count: int | None = None, configured: bool = True):
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
            result[name] = "ikke konfigurert"
            with db.conn() as c:
                _set_status(c, name, False, "Ikke konfigurert", configured=False)
            return
        progress(frac, f"Henter fra {name}")
        try:
            count, msg = fn(lambda f, m: progress(frac + f * 0.15, m))
            with db.conn() as c:
                _set_status(c, name, True, msg, count)
            result[name] = msg
        except Exception as e:
            err = str(e) if isinstance(e, ServiceError) else f"{type(e).__name__}: {e}"
            with db.conn() as c:
                _set_status(c, name, False, err)
            result[name] = f"feil: {err}"

    def do_radarr(p):
        rows = arr.fetch_radarr(svc["radarr"], mp)
        with db.conn() as c:
            _replace(c, "radarr_movies", rows)
        return len(rows), f"{len(rows)} filmer"

    def do_sonarr(p):
        series, files = arr.fetch_sonarr(svc["sonarr"], mp, p)
        with db.conn() as c:
            _replace(c, "sonarr_series", series)
            _replace(c, "sonarr_files", files)
        return len(series), f"{len(series)} serier, {len(files)} episodefiler"

    def do_plex(p):
        items, parts, libs = plex.fetch(svc["plex"], mp, s["protection"]["plex_labels"], p)
        with db.conn() as c:
            _replace(c, "plex_items", items)
            _replace(c, "plex_parts", parts)
            db.kv_set(c, "plex_libraries", libs)
        return len(items), f"{len(items)} elementer i {len(libs)} bibliotek"

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
        return total, f"{total} avspillinger ({len(rows)} nye/oppdatert)"

    def do_seerr(p):
        rows = seerr.fetch_requests(svc["seerr"])
        with db.conn() as c:
            _replace(c, "requests", rows)
        return len(rows), f"{len(rows)} forespørsler"

    def do_truenas(p):
        info = truenas.fetch(svc["truenas"])
        with db.conn() as c:
            db.kv_set(c, "truenas", {**info, "fetched": time.time()})
        n = info.get("root_snapshots")
        return len(info["datasets"]), f"{len(info['datasets'])} datasett, snapshots på rot: {n if n is not None else 'ukjent'}"

    step("radarr", 0.0, do_radarr)
    step("sonarr", 0.15, do_sonarr)
    step("plex", 0.35, do_plex)
    step("tautulli", 0.6, do_tautulli)
    step("seerr", 0.8, do_seerr)
    step("truenas", 0.9, do_truenas)
    with db.conn() as c:
        db.kv_set(c, "last_sync", time.time())
    progress(1.0, "Synkronisering ferdig")
    return result


def reset_history():
    """Brukes hvis Tautulli-databasen er byttet ut."""
    with db.conn() as c:
        c.execute("DELETE FROM plays")
        db.audit(c, "reset_history", {})


__all__ = ["run", "test_service", "reset_history", "json"]
