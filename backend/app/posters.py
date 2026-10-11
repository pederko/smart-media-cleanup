"""Plakater for filmer og serier.

Hentes fra Plex (samme bilde som i Plex), med Radarr/Sonarr som reserve. Nettleseren
snakker bare med denne appen, så Plex-token og API-nøkler forlater aldri serveren.
Bildene lagres i /data/posters og hentes på nytt etter 30 dager.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

import httpx

from . import db, settings

log = logging.getLogger("smc.posters")
WIDTH, HEIGHT = 300, 450
MAX_AGE = 30 * 86400
MISS_AGE = 86400          # prøv igjen etter et døgn hvis ingen kilde hadde bilde
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _dir() -> Path:
    d = settings.DATA_DIR / "posters"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _is_image(r: httpx.Response) -> bool:
    return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and len(r.content) > 100


def _from_plex(title: dict, s: dict) -> bytes | None:
    cfg = s["services"]["plex"]
    if not cfg.get("enabled") or not cfg.get("url") or not cfg.get("token"):
        return None
    keys = json.loads(title.get("plex_keys") or "[]")
    if not keys:
        return None
    with db.conn() as c:
        ph = ",".join("?" * len(keys))
        rows = db.rows(c, f"SELECT thumb FROM plex_items WHERE rating_key IN ({ph}) AND thumb IS NOT NULL "
                          f"AND kind IN ('movie','show') ORDER BY kind", keys)
    for r in rows:
        try:
            resp = httpx.get(f"{cfg['url'].rstrip('/')}/photo/:/transcode",
                             params={"width": WIDTH, "height": HEIGHT, "minSize": 1, "upscale": 1, "url": r["thumb"]},
                             headers={"X-Plex-Token": cfg["token"]}, timeout=15)
            if _is_image(resp):
                return resp.content
        except httpx.HTTPError as e:
            log.debug("Plex-plakat feilet: %s", e)
    return None


def _from_arr(title: dict, s: dict) -> bytes | None:
    for svc, id_key in (("radarr", "radarr_id"), ("sonarr", "sonarr_id")):
        cfg = s["services"][svc]
        if title.get(id_key) is None or not cfg.get("url") or not cfg.get("api_key"):
            continue
        for name in ("poster-500.jpg", "poster.jpg"):
            try:
                resp = httpx.get(f"{cfg['url'].rstrip('/')}/api/v3/mediacover/{title[id_key]}/{name}",
                                 headers={"X-Api-Key": cfg["api_key"]}, timeout=15)
                if _is_image(resp):
                    return resp.content
            except httpx.HTTPError as e:
                log.debug("%s-plakat feilet: %s", svc, e)
    return None


def get(key: str) -> Path | None:
    name = hashlib.sha1(key.encode()).hexdigest()
    path, miss = _dir() / f"{name}.img", _dir() / f"{name}.none"
    now = time.time()
    if path.exists() and now - path.stat().st_mtime < MAX_AGE:
        return path
    if miss.exists() and now - miss.stat().st_mtime < MISS_AGE:
        return path if path.exists() else None
    with _lock(key):
        if path.exists() and time.time() - path.stat().st_mtime < MAX_AGE:
            return path
        with db.conn() as c:
            rows = db.rows(c, "SELECT key, plex_keys, radarr_id, sonarr_id FROM titles WHERE key=?", (key,))
        if not rows:
            return None
        s = settings.get()
        data = _from_plex(rows[0], s) or _from_arr(rows[0], s)
        if data:
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
            miss.unlink(missing_ok=True)
            return path
        miss.touch()
        return path if path.exists() else None  # behold et gammelt bilde hvis kilden er nede


def media_type(path: Path) -> str:
    head = path.read_bytes()[:12]
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
