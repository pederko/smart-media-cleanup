"""TrueNAS middleware (optional) via JSON-RPC 2.0 over WebSocket (/api/current, 25.04+).

Read only: pool capacity, datasets and the number of snapshots on the root dataset.
Use an API key tied to a user with the «Read-Only Admin» role.
"""
from __future__ import annotations

import itertools
import json
import ssl
from typing import Any

from ..i18n import L, fmt
from .base import ServiceError


class _RPC:
    def __init__(self, cfg: dict):
        try:
            from websockets.sync.client import connect
        except ImportError as e:  # pragma: no cover
            raise ServiceError("The websockets library is missing") from e
        url = cfg.get("url", "").rstrip("/")
        if not url or not cfg.get("api_key"):
            raise ServiceError(L("URL or API key is missing", "URL eller API-nøkkel mangler"))
        ws_url = url.replace("https://", "wss://").replace("http://", "ws://") + "/api/current"
        ctx = None
        if ws_url.startswith("wss://"):
            ctx = ssl.create_default_context()
            if not cfg.get("verify_tls"):
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
        try:
            self.ws = connect(ws_url, ssl=ctx, open_timeout=10, close_timeout=5, max_size=2**24)
        except Exception as e:
            raise ServiceError(fmt("No connection to TrueNAS: {e}", "Ingen kontakt med TrueNAS: {e}", e=e)) from e
        self.ids = itertools.count(1)
        if self.call("auth.login_with_api_key", [cfg["api_key"]]) is not True:
            self.close()
            raise ServiceError(L("TrueNAS refused the API key", "TrueNAS avviste API-nøkkelen"))

    def call(self, method: str, params: list | None = None) -> Any:
        mid = next(self.ids)
        self.ws.send(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or []}))
        while True:
            msg = json.loads(self.ws.recv(timeout=60))
            if msg.get("id") != mid:
                continue  # events/notifications
            if "error" in msg:
                err = msg["error"]
                raise ServiceError(f"{method}: {err.get('message') or err}")
            return msg.get("result")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _parsed(v):
    if isinstance(v, dict):
        return v.get("parsed")
    return v


def _guess_pool() -> str:
    """The pool behind the first library (/mnt/<pool>/...), unless a dataset is configured."""
    from .. import settings
    for lib in settings.get()["libraries"]:
        parts = (lib.get("host_path") or "").strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "mnt":
            return parts[1]
    raise ServiceError(L("Set the pool or dataset under Settings → TrueNAS", "Angi pool eller datasett under Innstillinger → TrueNAS"))


def fetch(cfg: dict) -> dict:
    rpc = _RPC(cfg)
    try:
        ds_name = cfg.get("dataset") or _guess_pool()
        pool_name = ds_name.split("/")[0]
        pools = rpc.call("pool.query", [[["name", "=", pool_name]]]) or []
        pool = pools[0] if pools else {}
        datasets = rpc.call("pool.dataset.query", [[["pool", "=", pool_name]],
                                                   {"extra": {"flat": True, "retrieve_children": True}}]) or []
        ds_rows = []
        for d in datasets:
            ds_rows.append({
                "name": d.get("name") or d.get("id"),
                "mountpoint": d.get("mountpoint"),
                "used": _parsed(d.get("used")),
                "available": _parsed(d.get("available")),
                "referenced": _parsed(d.get("referenced") or d.get("usedbydataset")),
                "usedbysnapshots": _parsed(d.get("usedbysnapshots")),
                "compressratio": _parsed(d.get("compressratio")),
            })
        snaps = None
        for method in ("pool.snapshot.query", "zfs.snapshot.query"):
            try:
                snaps = rpc.call(method, [[["dataset", "=", ds_name]], {"count": True}])
                break
            except ServiceError:
                continue
        return {
            "pool": {"name": pool.get("name"), "size": pool.get("size"), "allocated": pool.get("allocated"),
                     "free": pool.get("free"), "status": pool.get("status")},
            "datasets": ds_rows,
            "root_dataset": ds_name,
            "root_snapshots": snaps if isinstance(snaps, int) else None,
        }
    finally:
        rpc.close()


def status(cfg: dict) -> dict:
    rpc = _RPC(cfg)
    try:
        info = rpc.call("system.info") or {}
        return {"version": info.get("version"), "app": "TrueNAS"}
    finally:
        rpc.close()
