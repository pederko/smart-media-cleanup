"""Innstillinger: standardverdier <- /data/settings.json <- miljøvariabler.

Miljøvariabler har høyest prioritet og låses i UI. Hemmeligheter maskeres i API-svar.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("SMC_DATA_DIR", "/data"))
SETTINGS_FILE = DATA_DIR / "settings.json"
MASK = "********"
SECRET_KEYS = {"api_key", "token"}

DEFAULTS: dict[str, Any] = {
    "services": {
        "radarr": {"enabled": True, "url": "", "api_key": ""},
        "sonarr": {"enabled": True, "url": "", "api_key": ""},
        "plex": {"enabled": True, "url": "", "token": ""},
        "tautulli": {"enabled": True, "url": "", "api_key": ""},
        "seerr": {"enabled": False, "url": "", "api_key": ""},
        "truenas": {"enabled": False, "url": "", "api_key": "", "verify_tls": False, "dataset": "pool1"},
    },
    # Biblioteker som skannes. host_path = sti på TrueNAS, container_path = mount i containeren.
    "libraries": [
        {"name": "FILM", "host_path": "/mnt/pool1/FILM", "container_path": "/media/FILM", "kind": "movies", "protected": False},
        {"name": "TV", "host_path": "/mnt/pool1/TV", "container_path": "/media/TV", "kind": "series", "protected": False},
        {"name": "Barn", "host_path": "/mnt/pool1/Barn", "container_path": "/media/Barn", "kind": "mixed", "protected": True},
        {"name": "tmp", "host_path": "/mnt/pool1/tmp", "container_path": "/media/tmp", "kind": "downloads", "protected": False},
    ],
    # Hvordan tjenestene ser stiene -> vertssti. Lengste prefiks vinner.
    "path_mappings": [
        {"from": "/FILM", "to": "/mnt/pool1/FILM"},
        {"from": "/TV", "to": "/mnt/pool1/TV"},
        {"from": "/Barn", "to": "/mnt/pool1/Barn"},
        {"from": "/tmp-download", "to": "/mnt/pool1/tmp"},
        {"from": "/downloads", "to": "/mnt/pool1/tmp"},
    ],
    "analysis": {
        "stale_months": [12, 24, 36],
        "quarantine_months": 6,
        "recent_play_months": 12,
        "min_suggestion_gb": 2.0,
        "large_movie_gb": 40.0,
        "large_episode_gb": 8.0,
        "target_movie_gb": 12.0,
        "target_episode_gb": 2.5,
        "min_score": 20,
    },
    "weights": {
        "space": 1.0,
        "staleness": 1.0,
        "consumption": 1.0,
        "viewers": 1.0,
        "monitored": 1.0,
        "recent": 1.0,
        "versions": 1.0,
        "request": 1.0,
    },
    "protection": {
        "tags": ["keep", "behold"],
        "plex_labels": ["keep", "behold"],
        "paths": [],
    },
    "scanner": {
        "interval_hours": 24,
        "full_scan_days": 7,
        "throttle_ms_per_1000": 20,
        "hash_min_size_mb": 200,
    },
    "sync": {"interval_hours": 6},
    "updates": {"check": True},
    "actions": {"enabled": False},
}

ENV_MAP = {
    ("services", "radarr", "url"): "SMC_RADARR_URL",
    ("services", "radarr", "api_key"): "SMC_RADARR_API_KEY",
    ("services", "sonarr", "url"): "SMC_SONARR_URL",
    ("services", "sonarr", "api_key"): "SMC_SONARR_API_KEY",
    ("services", "plex", "url"): "SMC_PLEX_URL",
    ("services", "plex", "token"): "SMC_PLEX_TOKEN",
    ("services", "tautulli", "url"): "SMC_TAUTULLI_URL",
    ("services", "tautulli", "api_key"): "SMC_TAUTULLI_API_KEY",
    ("services", "seerr", "url"): "SMC_SEERR_URL",
    ("services", "seerr", "api_key"): "SMC_SEERR_API_KEY",
    ("services", "truenas", "url"): "SMC_TRUENAS_URL",
    ("services", "truenas", "api_key"): "SMC_TRUENAS_API_KEY",
}

_lock = threading.Lock()


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_file() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        # Ødelagt fil skal ikke stoppe appen; standardverdier brukes.
        return {}


def env_locked() -> list[str]:
    return [".".join(path) for path, env in ENV_MAP.items() if os.environ.get(env)]


def get() -> dict:
    with _lock:
        s = _deep_merge(DEFAULTS, _read_file())
    for path, env in ENV_MAP.items():
        val = os.environ.get(env)
        if val:
            node = s
            for p in path[:-1]:
                node = node.setdefault(p, {})
            node[path[-1]] = val
            # En URL satt via env betyr at tjenesten er ment å være på.
            if path[-1] == "url":
                node["enabled"] = True
    return s


def masked(s: dict | None = None) -> dict:
    s = copy.deepcopy(s or get())
    for svc in s["services"].values():
        for k in SECRET_KEYS:
            if svc.get(k):
                svc[k] = MASK
    s["_env_locked"] = env_locked()
    return s


def save(new: dict) -> dict:
    """Lagrer innstillinger fra UI. Maskerte hemmeligheter beholder gammel verdi."""
    new = copy.deepcopy(new)
    new.pop("_env_locked", None)
    with _lock:
        current = _deep_merge(DEFAULTS, _read_file())
        for name, svc in new.get("services", {}).items():
            for k in SECRET_KEYS:
                if svc.get(k) == MASK:
                    svc[k] = current["services"].get(name, {}).get(k, "")
        merged = _deep_merge(current, new)
        # Lister erstattes helt (ikke flettes)
        for key in ("libraries", "path_mappings"):
            if key in new:
                merged[key] = new[key]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False), "utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(SETTINGS_FILE)
    return get()


def map_service_path(path: str | None, s: dict | None = None) -> str | None:
    """Oversetter en sti slik tjenesten ser den til vertssti."""
    if not path:
        return path
    s = s or get()
    best = None
    for m in s["path_mappings"]:
        src = m["from"].rstrip("/")
        if path == src or path.startswith(src + "/"):
            if best is None or len(src) > len(best["from"].rstrip("/")):
                best = m
    if best is None:
        return path
    src = best["from"].rstrip("/")
    return best["to"].rstrip("/") + path[len(src):]
