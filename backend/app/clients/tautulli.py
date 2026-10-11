"""Tautulli API v2. Watch history is fetched incrementally."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from ..i18n import L
from .base import ServiceError, get_json

PAGE = 1000


def _call(cfg: dict, cmd: str, **params):
    if not cfg.get("url") or not cfg.get("api_key"):
        raise ServiceError(L("URL or API key is missing", "URL eller API-nøkkel mangler"))
    data = get_json(f"{cfg['url'].rstrip('/')}/api/v2",
                    params={"apikey": cfg["api_key"], "cmd": cmd, **params})
    resp = data.get("response", {})
    if resp.get("result") != "success":
        raise ServiceError(f"Tautulli {cmd}: {resp.get('message') or 'unknown error'}")
    return resp.get("data")


def status(cfg: dict) -> dict:
    info = _call(cfg, "get_tautulli_info") or {}
    return {"version": info.get("tautulli_version"), "app": "Tautulli"}


def _row(r: dict) -> tuple:
    rid = r.get("row_id") or r.get("id") or r.get("reference_id")
    return (str(rid), r.get("date") or r.get("started"), r.get("friendly_name") or r.get("user"),
            str(r.get("rating_key") or ""), str(r.get("grandparent_rating_key") or ""),
            _int(r.get("parent_media_index")), r.get("media_type"), r.get("title"),
            r.get("grandparent_title"), _int(r.get("year")),
            _int(r.get("play_duration") or r.get("duration")), _int(r.get("percent_complete")),
            r.get("user"))


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fetch_history(cfg: dict, since_epoch: int | None,
                  progress: Callable[[float, str], None] | None = None) -> list[tuple]:
    params = {"length": PAGE, "order_column": "date", "order_dir": "asc", "grouping": 1}
    if since_epoch:
        # Overlap one day; rows are upserted on row_id so duplicates are harmless.
        d = datetime.fromtimestamp(since_epoch, tz=timezone.utc) - timedelta(days=1)
        params["after"] = d.strftime("%Y-%m-%d")
    out, start = [], 0
    while True:
        data = _call(cfg, "get_history", start=start, **params) or {}
        rows = data.get("data", []) or []
        out.extend(_row(r) for r in rows if r.get("media_type") in ("movie", "episode"))
        total = data.get("recordsFiltered") or 0
        start += len(rows)
        if progress and total:
            progress(min(1.0, start / total), f"Tautulli: {start}/{total} avspillinger")
        if not rows or start >= total:
            return out
