"""SQLite-lag. Én fil i /data, WAL-modus, ny tilkobling per bruk."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

from . import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY,
  library TEXT NOT NULL,
  dir TEXT NOT NULL,
  name TEXT NOT NULL,
  ext TEXT,
  size INTEGER NOT NULL,
  alloc INTEGER NOT NULL,
  inode INTEGER NOT NULL,
  dev INTEGER NOT NULL,
  nlink INTEGER NOT NULL,
  mtime REAL NOT NULL,
  is_video INTEGER NOT NULL DEFAULT 0,
  is_extra INTEGER NOT NULL DEFAULT 0,
  phash TEXT, phash_size INTEGER, phash_mtime REAL,
  scan_id INTEGER
);
CREATE INDEX IF NOT EXISTS files_dir ON files(dir);
CREATE INDEX IF NOT EXISTS files_size ON files(size);
CREATE INDEX IF NOT EXISTS files_inode ON files(dev, inode);
CREATE INDEX IF NOT EXISTS files_lib ON files(library);

CREATE TABLE IF NOT EXISTS dirs(path TEXT PRIMARY KEY, library TEXT, mtime REAL, scan_id INTEGER);
CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL, finished REAL,
  kind TEXT, files INTEGER, bytes INTEGER, status TEXT);

CREATE TABLE IF NOT EXISTS radarr_movies(id INTEGER PRIMARY KEY, title TEXT, year INTEGER, tmdb_id INTEGER,
  path TEXT, monitored INTEGER, added INTEGER, tags TEXT, has_file INTEGER, file_path TEXT, file_size INTEGER,
  quality TEXT, resolution TEXT, codec TEXT, file_added INTEGER);
CREATE TABLE IF NOT EXISTS sonarr_series(id INTEGER PRIMARY KEY, title TEXT, year INTEGER, tvdb_id INTEGER,
  path TEXT, monitored INTEGER, added INTEGER, tags TEXT, seasons TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS sonarr_files(id INTEGER PRIMARY KEY, series_id INTEGER, season INTEGER, path TEXT,
  size INTEGER, quality TEXT, resolution TEXT, codec TEXT, added INTEGER);
CREATE INDEX IF NOT EXISTS sonarr_files_path ON sonarr_files(path);

CREATE TABLE IF NOT EXISTS plex_items(rating_key TEXT PRIMARY KEY, kind TEXT, title TEXT, year INTEGER,
  show_key TEXT, season INTEGER, episode INTEGER, added_at INTEGER, library TEXT, labels TEXT);
CREATE TABLE IF NOT EXISTS plex_parts(path TEXT, rating_key TEXT, media_id TEXT, size INTEGER,
  resolution TEXT, codec TEXT, bitrate INTEGER, PRIMARY KEY(path, rating_key));

CREATE TABLE IF NOT EXISTS plays(row_id TEXT PRIMARY KEY, date INTEGER, user TEXT, rating_key TEXT,
  grandparent_key TEXT, parent_index INTEGER, media_type TEXT, title TEXT, grandparent_title TEXT,
  year INTEGER, duration INTEGER, percent INTEGER);
CREATE INDEX IF NOT EXISTS plays_rk ON plays(rating_key);
CREATE INDEX IF NOT EXISTS plays_gk ON plays(grandparent_key);

CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, media_type TEXT, tmdb_id INTEGER, tvdb_id INTEGER,
  requested_by TEXT, created INTEGER, status INTEGER);

CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, status TEXT, progress REAL,
  message TEXT, started REAL, finished REAL, error TEXT, log TEXT);

CREATE TABLE IF NOT EXISTS titles(key TEXT PRIMARY KEY, kind TEXT, name TEXT, year INTEGER, library TEXT,
  folder TEXT, radarr_id INTEGER, sonarr_id INTEGER, plex_keys TEXT, monitored INTEGER, added INTEGER,
  tags TEXT, protected INTEGER, protect_reason TEXT, size INTEGER, alloc INTEGER, file_count INTEGER,
  video_count INTEGER, play_count INTEGER, last_played INTEGER, users TEXT, users_count INTEGER,
  recent_users_count INTEGER, requested_by TEXT, requested_at INTEGER, best_resolution TEXT, seasons TEXT);
CREATE TABLE IF NOT EXISTS file_title(path TEXT PRIMARY KEY, title_key TEXT, season INTEGER, episode INTEGER);
CREATE INDEX IF NOT EXISTS file_title_key ON file_title(title_key);

CREATE TABLE IF NOT EXISTS suggestions(id TEXT PRIMARY KEY, kind TEXT, title_key TEXT, scope TEXT, action TEXT,
  label TEXT, location TEXT, score REAL, risk TEXT, size INTEGER, savings INTEGER, savings_note TEXT,
  reasons TEXT, consequences TEXT, components TEXT, history TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS suggestion_files(suggestion_id TEXT, path TEXT, claim INTEGER,
  PRIMARY KEY(suggestion_id, path));
CREATE INDEX IF NOT EXISTS suggestion_files_path ON suggestion_files(path);

CREATE TABLE IF NOT EXISTS duplicate_groups(id TEXT PRIMARY KEY, kind TEXT, title_key TEXT, label TEXT,
  total INTEGER, reclaimable INTEGER, files TEXT);

CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, action TEXT, detail TEXT);
"""


def db_path():
    return settings.DATA_DIR / "smc.sqlite3"


def connect() -> sqlite3.Connection:
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path(), timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    c = connect()
    try:
        yield c
    finally:
        c.close()


# Kolonner lagt til etter 0.1.0. Legges alltid til sist, slik at INSERT ... VALUES(?) stemmer.
MIGRATIONS = {
    "requests": [("plex_username", "TEXT"), ("rating_key", "TEXT")],
    "plays": [("username", "TEXT")],
    "titles": [("requests", "TEXT")],
}


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def kv_get(c: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return default


def kv_set(c: sqlite3.Connection, key: str, value: Any) -> None:
    c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (key, json.dumps(value, ensure_ascii=False)))


def audit(c: sqlite3.Connection, action: str, detail: Any) -> None:
    c.execute("INSERT INTO audit(ts,action,detail) VALUES(?,?,?)",
              (time.time(), action, json.dumps(detail, ensure_ascii=False)))


def backup(keep: int = 7) -> str:
    """Konsistent kopi av databasen og innstillingene til /data/backups (SQLite online backup)."""
    import shutil
    dest_dir = settings.DATA_DIR / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"smc-{stamp}.sqlite3"
    src = connect()
    try:
        out = sqlite3.connect(dest)
        with out:
            src.backup(out)
        out.close()
    finally:
        src.close()
    if settings.SETTINGS_FILE.exists():
        shutil.copy2(settings.SETTINGS_FILE, dest_dir / f"settings-{stamp}.json")
    for pattern in ("smc-*.sqlite3", "settings-*.json"):
        files = sorted(dest_dir.glob(pattern))
        for old in files[:-keep]:
            old.unlink(missing_ok=True)
    return str(dest)


def rows(c: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in c.execute(sql, params).fetchall()]
