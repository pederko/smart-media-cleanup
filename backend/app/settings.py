"""Settings: defaults <- /data/settings.json <- environment variables.

Environment variables win and are locked in the UI. Secrets are masked in API responses.
Libraries are detected from the folders mounted under /media on first start (see detect_libraries).
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("SMC_DATA_DIR", "/data"))
MEDIA_ROOT = Path(os.environ.get("SMC_MEDIA_ROOT", "/media"))
SETTINGS_FILE = DATA_DIR / "settings.json"
MASK = "********"
SECRET_KEYS = {"api_key", "token", "password"}

DEFAULTS: dict[str, Any] = {
    "services": {
        "radarr": {"enabled": True, "url": "", "api_key": ""},
        "sonarr": {"enabled": True, "url": "", "api_key": ""},
        "plex": {"enabled": True, "url": "", "token": ""},
        "tautulli": {"enabled": True, "url": "", "api_key": ""},
        "seerr": {"enabled": False, "url": "", "api_key": ""},
        "truenas": {"enabled": False, "url": "", "api_key": "", "verify_tls": False, "dataset": ""},
        "qbittorrent": {"enabled": False, "url": "", "username": "", "password": ""},
    },
    # Libraries that are scanned. host_path = path on the NAS, container_path = mount in this container.
    # kind: movies | series | mixed | downloads. Empty by default – detected from /media on first start.
    "libraries": [],
    # How the services (Radarr, Sonarr, Plex, download client) see the paths -> host path.
    # The longest prefix wins. Empty by default; the Settings page suggests mappings.
    "path_mappings": [],
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
        "tags": ["keep"],
        "plex_labels": ["keep"],
        "paths": [],
        # Should protection also prevent cleaning up duplicates? Off by default: one file always
        # remains, so the content is kept anyway.
        "include_duplicates": False,
    },
    "scanner": {
        "interval_hours": 24,
        "full_scan_days": 7,
        "throttle_ms_per_1000": 20,
        "hash_min_size_mb": 200,
    },
    "sync": {"interval_hours": 6},
    "updates": {"check": True},
    "actions": {"enabled": False, "files_enabled": False},
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
    ("services", "qbittorrent", "url"): "SMC_QBITTORRENT_URL",
    ("services", "qbittorrent", "username"): "SMC_QBITTORRENT_USERNAME",
    ("services", "qbittorrent", "password"): "SMC_QBITTORRENT_PASSWORD",
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
        # A broken file must not stop the app; the defaults are used.
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
            # A URL set through env means the service is meant to be on.
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
    """Saves settings from the UI. Masked secrets keep their old value."""
    new = copy.deepcopy(new)
    new.pop("_env_locked", None)
    with _lock:
        current = _deep_merge(DEFAULTS, _read_file())
        for name, svc in new.get("services", {}).items():
            for k in SECRET_KEYS:
                if svc.get(k) == MASK:
                    svc[k] = current["services"].get(name, {}).get(k, "")
        merged = _deep_merge(current, new)
        # Lists are replaced entirely (not merged)
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
    """Translates a path as the service sees it to the host path."""
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


# ---------------------------------------------------------------- library detection

KIND_HINTS = (
    ("downloads", ("download", "torrent", "usenet", "nzb", "incomplete", "complete", "tmp", "temp")),
    ("series", ("tv", "series", "serier", "shows", "show", "anime")),
    ("movies", ("movie", "movies", "film", "filmer", "cinema")),
)


def guess_kind(name: str) -> str:
    n = name.lower()
    for kind, words in KIND_HINTS:
        if any(n == w or n.startswith(w) or w in n.split() for w in words):
            return kind
    return "mixed"


def _mounts() -> dict[str, tuple[str, str, str]]:
    """mount point -> (root inside the source, fstype, source) from /proc/self/mountinfo."""
    out = {}
    try:
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            left, _, right = line.partition(" - ")
            f, r = left.split(), right.split()
            if len(f) >= 5 and len(r) >= 2:
                unesc = lambda x: x.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")  # noqa: E731
                out[unesc(f[4])] = (unesc(f[3]), r[0], unesc(r[1]))
    except OSError:
        pass
    return out


def host_path_for(container_path: str) -> str:
    """Best guess of the NAS path behind a bind mount. On TrueNAS a dataset «pool/a» is mounted at
    /mnt/pool/a, so a bind of /mnt/pool/a/Movies shows up as source «pool/a» with root «/Movies»."""
    info = _mounts().get(container_path.rstrip("/"))
    if info:
        root, fstype, source = info
        if fstype == "zfs" and source and not source.startswith("/"):
            return "/mnt/" + source.strip("/") + ("" if root in ("", "/") else root)
    return container_path.rstrip("/")


def detect_libraries() -> list[dict]:
    """One library per folder mounted directly under /media."""
    libs = []
    try:
        entries = sorted(p for p in MEDIA_ROOT.iterdir() if p.is_dir())
    except OSError:
        return libs
    for p in entries:
        if p.name.startswith("."):
            continue
        libs.append({"name": p.name, "host_path": host_path_for(str(p)), "container_path": str(p),
                     "kind": guess_kind(p.name), "protected": False, "detected": True})
    return libs


def ensure_libraries() -> list[dict]:
    """On first start (no libraries configured): detect them from the mounts and save."""
    current = _read_file()
    if current.get("libraries"):
        return current["libraries"]
    found = detect_libraries()
    if found:
        save({**current, "libraries": found})
    return found
