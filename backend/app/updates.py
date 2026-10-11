"""Ser etter nye utgivelser på GitHub (kun lesing, ingen automatisk oppdatering).

Selve oppdateringen gjøres i TrueNAS (Apps → mediacleanup → Update) når imaget bruker :latest.
"""
from __future__ import annotations

import logging
import os
import re
import time

import httpx

from . import db, settings

log = logging.getLogger("smc.updates")
REPO = os.environ.get("SMC_UPDATE_REPO", "pederko/smart-media-cleanup")
CHECK_EVERY = 6 * 3600


def current_version() -> str:
    return os.environ.get("SMC_VERSION", "0.7.2")


def parse(v: str | None) -> tuple[int, int, int] | None:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def is_newer(latest: str | None, current: str | None) -> bool:
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


def _fetch_latest() -> dict:
    r = httpx.get(f"https://api.github.com/repos/{REPO}/releases/latest",
                  headers={"Accept": "application/vnd.github+json"}, timeout=10, follow_redirects=True)
    r.raise_for_status()
    d = r.json()
    return {"tag": d.get("tag_name"), "url": d.get("html_url"), "notes": (d.get("body") or "")[:4000],
            "published": d.get("published_at")}


def check(force: bool = False) -> dict:
    """Henter siste release (maks hver 6. time) og lagrer resultatet. Feiler stille."""
    if not settings.get().get("updates", {}).get("check", True):
        return status()
    with db.conn() as c:
        cached = db.kv_get(c, "update_check") or {}
    if not force and time.time() - cached.get("checked", 0) < CHECK_EVERY:
        return status()
    try:
        latest = _fetch_latest()
        cached = {"checked": time.time(), "ok": True, **latest}
    except Exception as e:
        log.info("Fikk ikke sjekket oppdateringer: %s", e)
        cached = {**cached, "checked": time.time(), "ok": False, "error": str(e)}
    with db.conn() as c:
        db.kv_set(c, "update_check", cached)
    return status()


def status() -> dict:
    enabled = settings.get().get("updates", {}).get("check", True)
    with db.conn() as c:
        cached = db.kv_get(c, "update_check") or {}
    latest = (cached.get("tag") or "").lstrip("v") or None
    cur = current_version()
    return {
        "enabled": enabled,
        "current": cur,
        "latest": latest,
        "available": enabled and is_newer(latest, cur),
        "url": cached.get("url"),
        "notes": cached.get("notes"),
        "checked": cached.get("checked"),
        "ok": cached.get("ok"),
        "repo": REPO,
    }
