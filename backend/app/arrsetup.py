"""Download rules: how Radarr, Sonarr, Seerr and qBittorrent decide what is downloaded and kept.

Read: quality size limits, quality profiles (with custom format scores), Seerr's default profiles,
download clients, indexer seed limits and qBittorrent's seeding state – compared with recommended
values based on TRaSH Guides (https://trash-guides.info), with presets that cap sizes to save space.

Write (only after an explicit confirmation, with «Allow changes through …» switched on):
  * plan(changes)    -> what will change, before and after, plus a token
  * execute(changes, token) -> re-reads the current state, refuses if it differs from the plan,
    saves a backup of every object it is about to change, applies the changes and logs each one.
  * restore(name)    -> puts the objects from a backup back (profiles created by the app are deleted).
Nothing that is not selected is touched: custom formats, languages, other profiles and settings
are carried over as they are.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

from . import db, settings
from .actions import DONE, FAILED, log_action
from .actions import enabled as actions_enabled
from .clients import qbit
from .clients.base import TIMEOUT, ServiceError, get_json
from .i18n import L, ActionError, Conflict, Forbidden, fmt, join

log = logging.getLogger("smc.arrsetup")

ARR = ("radarr", "sonarr")
NAMES = {"radarr": "Radarr", "sonarr": "Sonarr", "seerr": "Seerr", "qbittorrent": "qBittorrent"}
# Typical runtime used to show MB per minute as a size per title
RUNTIME = {"radarr": 120, "sonarr": 45}
# The value Radarr/Sonarr show as «Unlimited» on the slider
UNLIMITED = {"radarr": 2000, "sonarr": 1000}

REMUX = {"Remux-1080p", "Remux-2160p", "Bluray-1080p Remux", "Bluray-2160p Remux"}
DISC = {"BR-DISK", "Raw-HD"}
# Custom formats that, scored positively, pull towards the largest releases
HEAVY_CF = re.compile(r"remux|truehd|atmos|dts|flac|pcm|lossless|br-?disk", re.I)

# Size limits in MB per minute: (minimum, preferred, maximum). None = unlimited.
# «trash» = TRaSH Guides (quality first: no upper limit). «balanced» and «small» keep TRaSH's minimums
# (to avoid low-quality encodes) but cap the size and prefer moderate releases.
PRESETS: dict[str, dict[str, dict[str, tuple]]] = {
    "radarr": {
        "trash": {
            "HDTV-720p": (17.1, 1999, None), "WEBDL-720p": (12.5, 1999, None), "WEBRip-720p": (12.5, 1999, None),
            "Bluray-720p": (25.7, 1999, None), "HDTV-1080p": (33.8, 1999, None), "WEBDL-1080p": (12.5, 1999, None),
            "WEBRip-1080p": (12.5, 1999, None), "Bluray-1080p": (50.8, 1999, None), "Remux-1080p": (102, 1999, None),
            "HDTV-2160p": (85, 1999, None), "WEBDL-2160p": (34.5, 1999, None), "WEBRip-2160p": (34.5, 1999, None),
            "Bluray-2160p": (102, 1999, None), "Remux-2160p": (187.4, 1999, None),
        },
        "balanced": {
            "HDTV-720p": (17.1, 25, 40), "WEBDL-720p": (12.5, 25, 40), "WEBRip-720p": (12.5, 25, 40),
            "Bluray-720p": (25.7, 30, 40), "HDTV-1080p": (33.8, 50, 80), "WEBDL-1080p": (12.5, 50, 80),
            "WEBRip-1080p": (12.5, 50, 80), "Bluray-1080p": (50.8, 80, 125), "Remux-1080p": (102, 250, 300),
            "HDTV-2160p": (85, 130, 200), "WEBDL-2160p": (34.5, 130, 200), "WEBRip-2160p": (34.5, 130, 200),
            "Bluray-2160p": (102, 220, 350), "Remux-2160p": (187.4, 500, 600),
        },
        "small": {
            "HDTV-720p": (17.1, 18, 25), "WEBDL-720p": (12.5, 15, 25), "WEBRip-720p": (12.5, 15, 25),
            "Bluray-720p": (25.7, 26, 30), "HDTV-1080p": (33.8, 35, 50), "WEBDL-1080p": (12.5, 30, 50),
            "WEBRip-1080p": (12.5, 30, 50), "Bluray-1080p": (50.8, 55, 80), "Remux-1080p": (102, 150, 200),
            "HDTV-2160p": (85, 90, 125), "WEBDL-2160p": (34.5, 80, 125), "WEBRip-2160p": (34.5, 80, 125),
            "Bluray-2160p": (102, 150, 200), "Remux-2160p": (187.4, 250, 350),
        },
    },
    "sonarr": {
        "trash": {
            "HDTV-720p": (10, 995, None), "HDTV-1080p": (15, 995, None), "WEBRip-720p": (10, 995, None),
            "WEBDL-720p": (10, 995, None), "Bluray-720p": (17.1, 995, None), "WEBRip-1080p": (15, 995, None),
            "WEBDL-1080p": (15, 995, None), "Bluray-1080p": (50.4, 995, None), "Bluray-1080p Remux": (69.1, 995, None),
            "HDTV-2160p": (25, 995, None), "WEBRip-2160p": (25, 995, None), "WEBDL-2160p": (25, 995, None),
            "Bluray-2160p": (94.6, 995, None), "Bluray-2160p Remux": (187.4, 995, None),
        },
        "balanced": {
            "HDTV-720p": (10, 20, 30), "HDTV-1080p": (15, 40, 60), "WEBRip-720p": (10, 20, 30),
            "WEBDL-720p": (10, 20, 30), "Bluray-720p": (17.1, 22, 30), "WEBRip-1080p": (15, 40, 60),
            "WEBDL-1080p": (15, 40, 60), "Bluray-1080p": (50.4, 65, 90), "Bluray-1080p Remux": (69.1, 150, 200),
            "HDTV-2160p": (25, 100, 150), "WEBRip-2160p": (25, 100, 150), "WEBDL-2160p": (25, 100, 150),
            "Bluray-2160p": (94.6, 180, 250), "Bluray-2160p Remux": (187.4, 350, 450),
        },
        "small": {
            "HDTV-720p": (10, 12, 20), "HDTV-1080p": (15, 22, 35), "WEBRip-720p": (10, 12, 20),
            "WEBDL-720p": (10, 12, 20), "Bluray-720p": (17.1, 18, 20), "WEBRip-1080p": (15, 22, 35),
            "WEBDL-1080p": (15, 22, 35), "Bluray-1080p": (50.4, 55, 70), "Bluray-1080p Remux": (69.1, 100, 120),
            "HDTV-2160p": (25, 60, 90), "WEBRip-2160p": (25, 60, 90), "WEBDL-2160p": (25, 60, 90),
            "Bluray-2160p": (94.6, 120, 160), "Bluray-2160p Remux": (187.4, 230, 300),
        },
    },
}
PRESET_INFO = {
    "trash": L("TRaSH Guides: quality first. Sensible minimums, no upper limit – size is then controlled by the profile.",
               "TRaSH Guides: kvalitet først. Fornuftige minimum, ingen øvre grense – størrelsen styres da av profilen."),
    "balanced": L("Recommended: TRaSH's minimums, but a ceiling per quality and a preference for moderate sizes.",
                  "Anbefalt: TRaSH sine minimum, men et tak per kvalitet og en preferanse for moderate størrelser."),
    "small": L("Saves the most space: efficient encodes (often x265/HEVC). Remuxes and big encodes are refused.",
               "Sparer mest plass: effektive encoder (ofte x265/HEVC). Remuxer og store encoder avvises."),
}

# New profiles (qualities only, as in TRaSH Guides). Custom formats, scores and language are copied
# from the profile chosen as a base, so a custom setup is carried over.
RECIPES = {
    "radarr": {
        "hd": {"name": "HD Bluray + WEB", "allowed": ["WEBDL-1080p", "WEBRip-1080p", "Bluray-1080p"], "cutoff": "Bluray-1080p",
               "info": L("1080p, upgrades from WEB to Bluray encodes. Typically 6–15 GB per movie.",
                         "1080p, oppgraderer fra WEB til Bluray-encode. Typisk 6–15 GB per film.")},
        "web": {"name": "WEB-1080p", "allowed": ["WEBDL-1080p", "WEBRip-1080p"], "cutoff": "WEBDL-1080p",
                "info": L("1080p web releases only. Typically 4–10 GB per movie.",
                          "Bare 1080p web-utgivelser. Typisk 4–10 GB per film.")},
        "uhd": {"name": "UHD Bluray + WEB", "allowed": ["WEBDL-2160p", "WEBRip-2160p", "Bluray-2160p"], "cutoff": "Bluray-2160p",
                "info": L("4K without remuxes. Typically 20–60 GB per movie.", "4K uten remuxer. Typisk 20–60 GB per film.")},
    },
    "sonarr": {
        "web": {"name": "WEB-1080p", "allowed": ["WEBDL-1080p", "WEBRip-1080p"], "cutoff": "WEBDL-1080p",
                "info": L("1080p web releases (TRaSH's recommendation for series). Typically 1–3 GB per episode.",
                          "1080p web-utgivelser (TRaSH sin anbefaling for serier). Typisk 1–3 GB per episode.")},
        "uhd": {"name": "WEB-2160p", "allowed": ["WEBDL-2160p", "WEBRip-2160p"], "cutoff": "WEBDL-2160p",
                "info": L("4K web releases. Typically 3–8 GB per episode.", "4K web-utgivelser. Typisk 3–8 GB per episode.")},
    },
}

SEED_DEFAULT = {"ratio": 1.0, "minutes": 1440}


# ================================================================== HTTP helpers

def _arr_cfg(svc: str) -> tuple[str, dict] | None:
    cfg = settings.get()["services"][svc]
    if not cfg.get("url") or not cfg.get("api_key"):
        return None
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}


def _seerr_cfg() -> tuple[str, dict] | None:
    cfg = settings.get()["services"]["seerr"]
    if not cfg.get("enabled") or not cfg.get("url") or not cfg.get("api_key"):
        return None
    return cfg["url"].rstrip("/"), {"X-Api-Key": cfg["api_key"]}


def _qbit_cfg() -> dict | None:
    cfg = settings.get()["services"]["qbittorrent"]
    return cfg if cfg.get("enabled") and cfg.get("url") else None


def _send(svc: str, method: str, url: str, headers: dict, body=None, params=None):
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.request(method, url, headers=headers, json=body, params=params)
    except httpx.HTTPError as e:
        raise ActionError(fmt("No connection to {s}: {e}", "Ingen kontakt med {s}: {e}", s=NAMES[svc], e=e)) from e
    if r.status_code >= 400:
        detail = r.text[:400]
        try:
            j = r.json()
            if isinstance(j, list):  # Radarr/Sonarr validation errors
                detail = "; ".join(str(x.get("errorMessage") or x) for x in j)[:400]
            elif isinstance(j, dict):
                detail = str(j.get("message") or j.get("error") or j)[:400]
        except ValueError:
            pass
        raise ActionError(fmt("{s} answered {c}: {d}", "{s} svarte {c}: {d}", s=NAMES[svc], c=r.status_code, d=detail))
    return r.json() if r.content and "json" in r.headers.get("content-type", "") else None


# ================================================================== profile helpers

def _iname(item: dict) -> str:
    return item.get("name") or (item.get("quality") or {}).get("name") or "?"


def _iid(item: dict) -> int:
    return item["id"] if item.get("items") else item["quality"]["id"]


def _children(item: dict) -> list[str]:
    return [_iname(x) for x in item.get("items") or []] or [_iname(item)]


def allowed_qualities(profile: dict) -> list[str]:
    """Allowed quality names, best first (Radarr/Sonarr list them worst first)."""
    out = []
    for it in profile.get("items", []):
        if it.get("allowed"):
            out.extend(_children(it))
    return list(reversed(out))


def cutoff_name(profile: dict) -> str | None:
    for it in profile.get("items", []):
        if it.get("allowed") and _iid(it) == profile.get("cutoff"):
            return _iname(it)
    return None


def _fix_cutoff(profile: dict) -> None:
    allowed = [it for it in profile["items"] if it.get("allowed")]
    if not allowed:
        raise ActionError(L("The profile would have no allowed qualities left", "Profilen ville ikke hatt noen tillatte kvaliteter igjen"))
    if not any(_iid(it) == profile.get("cutoff") for it in allowed):
        profile["cutoff"] = _iid(allowed[-1])


def disallow(profile: dict, names: set[str]) -> list[str]:
    """Stops the given qualities from being downloaded. Mixed groups are split so the rest stays allowed."""
    done, items = [], []
    for it in profile["items"]:
        kids = it.get("items") or []
        if not kids:
            if it.get("allowed") and _iname(it) in names:
                it["allowed"] = False
                done.append(_iname(it))
            items.append(it)
            continue
        hit = [k for k in kids if _iname(k) in names]
        if not hit or not it.get("allowed"):
            items.append(it)
        elif len(hit) == len(kids):
            it["allowed"] = False
            for k in kids:
                k["allowed"] = False
            done.extend(_iname(k) for k in kids)
            items.append(it)
        else:  # take the unwanted ones out of the group, just before it
            for k in hit:
                items.append({"quality": k["quality"], "items": [], "allowed": False})
                done.append(_iname(k))
            rest = [k for k in kids if k not in hit]
            if len(rest) == 1:
                # Radarr/Sonarr refuse groups with a single quality – it becomes a plain quality
                single = {"quality": rest[0]["quality"], "items": [], "allowed": True}
                if profile.get("cutoff") == it.get("id"):
                    profile["cutoff"] = single["quality"]["id"]
                items.append(single)
            else:
                it["items"] = rest
                items.append(it)
    profile["items"] = items
    _fix_cutoff(profile)
    return done


def from_recipe(base: dict, recipe: dict) -> dict:
    """A new profile with the recipe's qualities, everything else copied from ``base``."""
    p = copy.deepcopy(base)
    p.pop("id", None)
    p["name"] = recipe["name"]
    want = set(recipe["allowed"])
    for it in p["items"]:
        kids = it.get("items") or []
        on = any(n in want for n in _children(it))
        it["allowed"] = on
        for k in kids:
            k["allowed"] = on
    cut = next((it for it in p["items"] if recipe["cutoff"] in _children(it)), None)
    if cut is None or not any(it.get("allowed") for it in p["items"]):
        raise ActionError(L("Radarr/Sonarr does not have the qualities this profile needs",
                            "Radarr/Sonarr har ikke kvalitetene denne profilen trenger"))
    p["cutoff"] = _iid(cut)
    p["upgradeAllowed"] = True
    return p


# ================================================================== read

def _fetch_arr(svc: str) -> dict:
    base, h = _arr_cfg(svc)
    out = {"definitions": get_json(f"{base}/api/v3/qualitydefinition", headers=h, retries=0),
           "profiles": get_json(f"{base}/api/v3/qualityprofile", headers=h, retries=0)}
    try:
        out["clients"] = get_json(f"{base}/api/v3/downloadclient", headers=h, retries=0)
    except ServiceError:
        out["clients"] = []
    try:
        out["indexers"] = get_json(f"{base}/api/v3/indexer", headers=h, retries=0)
    except ServiceError:
        out["indexers"] = []
    titles = get_json(f"{base}/api/v3/{'movie' if svc == 'radarr' else 'series'}", headers=h)
    out["titles"] = titles
    return out


def _field(obj: dict, name: str):
    for f in obj.get("fields") or []:
        if f.get("name") == name:
            return f.get("value")
    return None


def _set_field(obj: dict, name: str, value) -> None:
    for f in obj.get("fields") or []:
        if f.get("name") == name:
            f["value"] = value
            return


def _usage(svc: str, titles: list[dict]) -> dict[int, dict]:
    use: dict[int, dict] = {}
    for t in titles:
        u = use.setdefault(t.get("qualityProfileId"), {"count": 0, "bytes": 0})
        u["count"] += 1
        u["bytes"] += int(t.get("sizeOnDisk") or (t.get("statistics") or {}).get("sizeOnDisk") or 0)
    return use


def _file_rates(svc: str, titles: list[dict]) -> dict[str, list]:
    """Per quality: [MB per minute, size] for every file, so the page can show live how many files
    are above a limit. Movies: from the movie list; episodes: from the last sync."""
    rates: dict[str, list] = {}
    if svc == "radarr":
        for t in titles:
            mf = t.get("movieFile") or {}
            q = ((mf.get("quality") or {}).get("quality") or {}).get("name")
            if q and mf.get("size") and t.get("runtime"):
                rates.setdefault(q, []).append([round(mf["size"] / 2 ** 20 / t["runtime"], 1), mf["size"]])
    else:
        runtime = {t["id"]: t.get("runtime") for t in titles}
        with db.conn() as c:
            for sid, q, size in c.execute("SELECT series_id, quality, size FROM sonarr_files"):
                rt = runtime.get(sid)
                if q and size and rt:
                    rates.setdefault(q, []).append([round(size / 2 ** 20 / rt, 1), size])
    return rates


def _is_unlimited(svc: str, mx) -> bool:
    return mx is None or mx == 0 or mx >= UNLIMITED[svc]


def _profile_view(svc: str, p: dict, defs: dict[str, dict], use: dict, recipes_present: set[str]) -> dict:
    allowed = allowed_qualities(p)
    findings = []
    remux = [q for q in allowed if q in REMUX]
    if remux:
        findings.append({"id": f"{svc}:{p['id']}:remux", "level": "warn",
                         "text": fmt("Allows remuxes ({q}). A remux is the untouched disc: 20–40 GB in 1080p and 40–100 GB in 4K.",
                                     "Tillater remuxer ({q}). En remux er platen urørt: 20–40 GB i 1080p og 40–100 GB i 4K.",
                                     q=", ".join(remux)),
                         "change": {"op": "disallow", "service": svc, "profile": p["id"], "qualities": remux}})
    disc = [q for q in allowed if q in DISC]
    if disc:
        findings.append({"id": f"{svc}:{p['id']}:disc", "level": "warn",
                         "text": fmt("Allows {q} – full discs or raw broadcasts that Plex often cannot play well.",
                                     "Tillater {q} – hele plater eller rå sendinger som Plex ofte ikke spiller godt.",
                                     q=", ".join(disc)),
                         "change": {"op": "disallow", "service": svc, "profile": p["id"], "qualities": disc}})
    formats = [{"id": f.get("format"), "name": f.get("name"), "score": f.get("score", 0)}
               for f in p.get("formatItems") or [] if f.get("score")]
    for f in formats:
        if f["score"] > 0 and HEAVY_CF.search(f["name"] or ""):
            findings.append({"id": f"{svc}:{p['id']}:cf:{f['id']}", "level": "info",
                             "text": fmt("The custom format «{n}» gives +{s} and pulls towards the largest releases.",
                                         "Custom format «{n}» gir +{s} og trekker mot de største utgivelsene.",
                                         n=f["name"], s=f["score"]),
                             "change": {"op": "cf_score", "service": svc, "profile": p["id"], "format": f["id"], "score": 0}})
    unlimited = [q for q in allowed if q in defs and _is_unlimited(svc, defs[q].get("maxSize"))]
    biggest = None
    if allowed and not unlimited:
        biggest = max((defs[q]["maxSize"] for q in allowed if q in defs), default=None)
    if unlimited:
        findings.append({"id": f"{svc}:{p['id']}:unlimited", "level": "info",
                         "text": fmt("No size limit for {q} – see «Size limits».",
                                     "Ingen størrelsesgrense for {q} – se «Størrelsesgrenser».",
                                     q=", ".join(unlimited[:4]) + ("…" if len(unlimited) > 4 else ""))})
    if not formats:
        findings.append({"id": f"{svc}:{p['id']}:nocf", "level": "info",
                         "text": L("No custom formats are scored. TRaSH Guides recommends custom formats that block low-quality "
                                   "groups and prefer efficient releases – Recyclarr can sync them.",
                                   "Ingen custom formats har poeng. TRaSH Guides anbefaler custom formats som blokkerer "
                                   "dårlige utgivergrupper og foretrekker effektive utgivelser – Recyclarr kan synkronisere dem.")})
    u = use.get(p["id"], {"count": 0, "bytes": 0})
    return {"id": p["id"], "name": p["name"], "upgrade_allowed": bool(p.get("upgradeAllowed")), "cutoff": cutoff_name(p),
            "allowed": allowed, "formats": formats, "min_format_score": p.get("minFormatScore", 0),
            "cutoff_format_score": p.get("cutoffFormatScore", 0), "count": u["count"], "bytes": u["bytes"],
            "max_mb_per_min": biggest, "unlimited": unlimited, "findings": findings,
            "recipe": p["name"] in recipes_present}


def _seeding_view(svc: str, data: dict) -> dict:
    clients, cats = [], []
    for c in data["clients"]:
        if c.get("protocol") != "torrent":
            continue
        cat = _field(c, "movieCategory" if svc == "radarr" else "tvCategory")
        if cat:
            cats.append(cat)
        item = {"id": c["id"], "name": c.get("name"), "implementation": c.get("implementation"), "enabled": bool(c.get("enable")),
                "remove_completed": bool(c.get("removeCompletedDownloads")), "category": cat,
                "host": _field(c, "host"), "port": _field(c, "port"), "ssl": bool(_field(c, "useSsl")),
                "url_base": _field(c, "urlBase") or ""}
        if item["enabled"] and not item["remove_completed"]:
            item["finding"] = {"id": f"{svc}:client:{c['id']}", "level": "warn",
                               "text": fmt("«Remove completed» is off: {s} leaves finished torrents in {c} for ever.",
                                           "«Remove completed» er av: {s} lar ferdige torrenter ligge i {c} for alltid.",
                                           s=NAMES[svc], c=c.get("name")),
                               "change": {"op": "remove_completed", "service": svc, "client": c["id"]}}
        clients.append(item)
    indexers = []
    for i in data["indexers"]:
        if i.get("protocol") != "torrent":
            continue
        indexers.append({"id": i["id"], "name": i.get("name"), "enabled": bool(i.get("enableRss") or i.get("enableAutomaticSearch")),
                         "ratio": _field(i, "seedCriteria.seedRatio"), "minutes": _field(i, "seedCriteria.seedTime"),
                         "pack_minutes": _field(i, "seedCriteria.seasonPackSeedTime"),
                         "prowlarr": "(Prowlarr)" in (i.get("name") or "")})
    return {"clients": clients, "indexers": indexers, "categories": cats}


def _seerr_view(arr_views: dict) -> dict:
    sc = _seerr_cfg()
    if not sc:
        return {"configured": False, "servers": []}
    base, h = sc
    servers = []
    for kind in ARR:
        try:
            lst = get_json(f"{base}/api/v1/settings/{kind}", headers=h, retries=0)
        except ServiceError as e:
            return {"configured": True, "error": e.msg, "servers": []}
        ours = arr_views.get(kind) or {}
        ours_by_name = {p["name"]: p for p in ours.get("profiles", [])}
        for s in lst:
            try:
                test = _send("seerr", "POST", f"{base}/api/v1/settings/{kind}/test", h, body={
                    "hostname": s.get("hostname"), "port": s.get("port"), "apiKey": s.get("apiKey"),
                    "useSsl": s.get("useSsl"), "baseUrl": s.get("baseUrl")}) or {}
                profiles = [{"id": p["id"], "name": p["name"]} for p in test.get("profiles") or []]
            except ActionError:
                profiles = [{"id": p["id"], "name": p["name"]} for p in ours.get("profiles", [])]
            same = bool(profiles) and {p["name"] for p in profiles} <= set(ours_by_name)
            fields = [("activeProfileId", "activeProfileName", L("Default profile", "Standardprofil"))]
            if kind == "sonarr" and s.get("activeAnimeProfileId") is not None:
                fields.append(("activeAnimeProfileId", "activeAnimeProfileName", L("Anime profile", "Anime-profil")))
            slots = []
            for fid, fname, label in fields:
                cur = s.get(fid)
                prof = next((p for p in profiles if p["id"] == cur), None)
                name = (prof or {}).get("name") or s.get(fname)
                ana = ours_by_name.get(name) if same else None
                slot = {"field": fid, "name_field": fname, "label": label, "profile": cur, "profile_name": name,
                        "allows_remux": bool(ana and any(q in REMUX for q in ana["allowed"])),
                        "count": (ana or {}).get("count")}
                if slot["allows_remux"] and not s.get("is4k"):
                    alt = [p for p in ours.get("profiles", []) if not any(q in REMUX | DISC for q in p["allowed"])]
                    slot["finding"] = {"level": "warn",
                                       "text": fmt("New requests from Seerr use «{p}», which allows remuxes.",
                                                   "Nye forespørsler fra Seerr bruker «{p}», som tillater remuxer.", p=name),
                                       "alternatives": [p["id"] for p in alt]}
                slots.append(slot)
            servers.append({"kind": kind, "id": s["id"], "name": s.get("name"), "is4k": bool(s.get("is4k")),
                            "default": bool(s.get("isDefault")), "same_instance": same, "profiles": profiles, "slots": slots})
    return {"configured": True, "servers": servers}


def _torrent_status(paths_by_entry: list[dict], content_path: str | None) -> dict | None:
    if not content_path:
        return None
    host = settings.map_service_path(content_path)
    for e in paths_by_entry:
        if host == e["path"] or host.startswith(e["path"] + "/"):
            return e
    return None


def _qbit_view(categories: list[str]) -> dict:
    cfg = _qbit_cfg()
    if not cfg:
        return {"configured": False}
    from . import downloads
    try:
        with qbit.Client(cfg) as q:
            prefs = q.preferences()
            torrents = q.torrents()
    except ServiceError as e:
        return {"configured": True, "error": e.msg}
    entries = downloads.overview()["items"]
    cats = set(categories)
    items = []
    for t in torrents:
        if cats and t.get("category") not in cats:
            continue
        e = _torrent_status(entries, t.get("content_path"))
        complete = (t.get("progress") or 0) >= 1
        imported = bool(e and e["status"] in ("hardlinked", "copied"))
        items.append({
            "hash": t["hash"], "name": t.get("name"), "category": t.get("category"), "state": t.get("state"),
            "complete": complete, "ratio": round(t.get("ratio") or 0, 2), "seeding_minutes": int((t.get("seeding_time") or 0) / 60),
            "ratio_limit": t.get("ratio_limit"), "seeding_limit": t.get("seeding_time_limit"), "size": t.get("size") or 0,
            "added": t.get("added_on"), "tracker_private": bool(t.get("private")) if "private" in t else None,
            "import_status": e["status"] if e else None, "title_name": e["title_name"] if e else None,
            "freed": (e["freed"] if e else 0), "imported": imported,
            "removable": complete and imported,
        })
    items.sort(key=lambda x: -x["size"])
    global_limits = {"ratio_enabled": bool(prefs.get("max_ratio_enabled")), "ratio": prefs.get("max_ratio"),
                     "time_enabled": bool(prefs.get("max_seeding_time_enabled")), "minutes": prefs.get("max_seeding_time"),
                     "action": prefs.get("max_ratio_act")}
    finding = None
    if not (global_limits["ratio_enabled"] or global_limits["time_enabled"]) or global_limits["action"] != qbit.STOP:
        finding = {"id": "qbit:prefs", "level": "warn",
                   "text": L("qBittorrent has no seeding limit that stops torrents, so Radarr/Sonarr never get to remove them.",
                             "qBittorrent har ingen delingsgrense som stopper torrenter, så Radarr/Sonarr får aldri fjernet dem."),
                   "change": {"op": "qbit_prefs", **SEED_DEFAULT}}
    return {"configured": True, "limits": global_limits, "finding": finding, "torrents": items,
            "summary": {"count": len(items), "size": sum(i["size"] for i in items),
                        "removable": sum(1 for i in items if i["removable"]),
                        "removable_freed": sum(i["freed"] for i in items if i["removable"])}}


def overview() -> dict:
    out: dict = {"enabled": actions_enabled(), "services": {}, "presets": {k: {"info": v} for k, v in PRESET_INFO.items()}}
    raw: dict[str, dict] = {}
    for svc in ARR:
        if not _arr_cfg(svc):
            out["services"][svc] = {"configured": False}
            continue
        try:
            data = raw[svc] = _fetch_arr(svc)
        except ServiceError as e:
            out["services"][svc] = {"configured": True, "error": e.msg}
            continue
        defs = {d["quality"]["name"]: d for d in data["definitions"]}
        use = _usage(svc, data["titles"])
        recipes = RECIPES[svc]
        present = {r["name"] for r in recipes.values()} & {p["name"] for p in data["profiles"]}
        profiles = [_profile_view(svc, p, defs, use, present) for p in data["profiles"]]
        presets = PRESETS[svc]
        out["services"][svc] = {
            "configured": True, "runtime": RUNTIME[svc], "unlimited": UNLIMITED[svc],
            "definitions": [{"id": d["id"], "name": d["quality"]["name"], "title": d.get("title"),
                             "min": d.get("minSize"), "preferred": d.get("preferredSize"), "max": d.get("maxSize"),
                             "presets": {k: list(v[d["quality"]["name"]]) for k, v in presets.items() if d["quality"]["name"] in v},
                             "used": any(d["quality"]["name"] in p["allowed"] for p in profiles)}
                            for d in data["definitions"]],
            "files": _file_rates(svc, data["titles"]),
            "profiles": profiles,
            "recipes": [{"key": k, "name": r["name"], "info": r["info"], "allowed": r["allowed"], "cutoff": r["cutoff"],
                         "exists": r["name"] in present} for k, r in recipes.items()],
            "seeding": _seeding_view(svc, data),
        }
    out["seerr"] = _seerr_view(out["services"])
    cats = [c for svc in ARR for c in (out["services"][svc].get("seeding") or {}).get("categories", [])]
    out["qbit"] = _qbit_view(cats)
    hint = None
    for svc in ARR:
        for c in (out["services"][svc].get("seeding") or {}).get("clients", []):
            if c["implementation"] == "QBittorrent" and c["host"]:
                hint = f"{'https' if c['ssl'] else 'http'}://{c['host']}:{c['port']}{c['url_base'] or ''}"
                break
        if hint:
            break
    out["qbit"]["url_hint"] = hint
    out["seed_default"] = SEED_DEFAULT
    return out


# ================================================================== plan / execute

class _State:
    """The live objects a set of changes touches, plus copies being changed."""

    def __init__(self):
        self.arr: dict[str, dict] = {}
        self.seerr: dict[str, dict[int, dict]] = {}
        self.qbit_prefs: dict | None = None
        self.qbit_torrents: dict[str, dict] | None = None

    def arr_data(self, svc: str) -> dict:
        if svc not in self.arr:
            cfg = _arr_cfg(svc)
            if not cfg:
                raise ActionError(fmt("{s} is not configured", "{s} er ikke konfigurert", s=NAMES[svc]))
            base, h = cfg
            self.arr[svc] = {
                "definitions": get_json(f"{base}/api/v3/qualitydefinition", headers=h, retries=0),
                "profiles": {p["id"]: p for p in get_json(f"{base}/api/v3/qualityprofile", headers=h, retries=0)},
                "clients": {c["id"]: c for c in get_json(f"{base}/api/v3/downloadclient", headers=h, retries=0)},
            }
        return self.arr[svc]

    def seerr_servers(self, kind: str) -> dict[int, dict]:
        if kind not in self.seerr:
            sc = _seerr_cfg()
            if not sc:
                raise ActionError(L("Seerr is not configured", "Seerr er ikke konfigurert"))
            base, h = sc
            self.seerr[kind] = {s["id"]: s for s in get_json(f"{base}/api/v1/settings/{kind}", headers=h, retries=0)}
        return self.seerr[kind]

    def qbit(self):
        if self.qbit_prefs is None:
            cfg = _qbit_cfg()
            if not cfg:
                raise ActionError(L("qBittorrent is not configured", "qBittorrent er ikke konfigurert"))
            with qbit.Client(cfg) as q:
                self.qbit_prefs = q.preferences()
                self.qbit_torrents = {t["hash"]: t for t in q.torrents()}
        return self.qbit_prefs, self.qbit_torrents

    def fingerprint(self) -> str:
        def strip_t(t):  # torrents change all the time (ratio, speed) – compare what matters
            return {k: t.get(k) for k in ("hash", "name", "progress", "content_path", "category")}
        prefs = None
        if self.qbit_prefs is not None:
            prefs = {k: self.qbit_prefs.get(k) for k in ("max_ratio_enabled", "max_ratio", "max_seeding_time_enabled",
                                                         "max_seeding_time", "max_ratio_act")}
        blob = json.dumps({"arr": self.arr, "seerr": self.seerr, "qbit": prefs,
                           "torrents": {h: strip_t(t) for h, t in (self.qbit_torrents or {}).items()}},
                          sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _num(v):
    if v is None:
        return None
    v = float(v)
    if v < 0:
        raise ActionError(L("Sizes cannot be negative", "Størrelser kan ikke være negative"))
    return round(v, 1)


def _plan_one(st: _State, ch: dict, work: dict) -> list[dict]:
    """Applies one change to the working copies in ``work``. Returns rows for the summary."""
    op, svc = ch.get("op"), ch.get("service")
    rows = []
    if op == "definitions":
        data = st.arr_data(svc)
        defs = work.setdefault(("definitions", svc), copy.deepcopy(data["definitions"]))
        by_name = {d["quality"]["name"]: d for d in defs}
        for name, vals in (ch.get("values") or {}).items():
            d = by_name.get(name)
            if d is None:
                continue
            mn, pref, mx = (_num(x) for x in (list(vals) + [None, None, None])[:3])
            if mx is not None and mx >= UNLIMITED[svc]:
                mx = None
            if pref is not None and (pref >= UNLIMITED[svc] - 5 or (mx is not None and pref > mx)):
                pref = mx if mx is not None else UNLIMITED[svc] - (1 if svc == "radarr" else 5)
            if mn is None:
                mn = d.get("minSize") or 0
            if mx is not None and mn > mx:
                raise ActionError(fmt("{q}: the minimum is above the maximum", "{q}: minimum er over maksimum", q=name))
            if pref is not None and pref < mn:
                pref = mn
            before = (d.get("minSize"), d.get("preferredSize"), d.get("maxSize"))
            if before == (mn, pref, mx):
                continue
            d["minSize"], d["preferredSize"], d["maxSize"] = mn, pref, mx
            rows.append({"service": svc, "area": "sizes", "what": fmt("Size limits for {q}", "Størrelsesgrenser for {q}", q=name),
                         "before": list(before), "after": [mn, pref, mx], "kind": "mbpm"})
        return rows
    if op in ("disallow", "cf_score"):
        data = st.arr_data(svc)
        pid = ch.get("profile")
        if pid not in data["profiles"]:
            raise ActionError(L("The profile no longer exists", "Profilen finnes ikke lenger"))
        p = work.setdefault(("profile", svc, pid), copy.deepcopy(data["profiles"][pid]))
        if op == "disallow":
            before_cut = cutoff_name(p)
            done = disallow(p, set(ch.get("qualities") or []))
            if done:
                rows.append({"service": svc, "area": "profiles",
                             "what": fmt("Profile «{p}»: stop downloading {q}", "Profil «{p}»: slutt å laste ned {q}",
                                         p=p["name"], q=", ".join(done))})
            if cutoff_name(p) != before_cut:
                rows.append({"service": svc, "area": "profiles",
                             "what": fmt("Profile «{p}»: upgrade until {q}", "Profil «{p}»: oppgrader til {q}", p=p["name"], q=cutoff_name(p)),
                             "before": before_cut, "after": cutoff_name(p)})
        else:
            for f in p.get("formatItems") or []:
                if f.get("format") == ch.get("format") and f.get("score") != ch.get("score"):
                    rows.append({"service": svc, "area": "profiles",
                                 "what": fmt("Profile «{p}»: score for «{f}»", "Profil «{p}»: poeng for «{f}»", p=p["name"], f=f.get("name")),
                                 "before": f.get("score"), "after": ch.get("score")})
                    f["score"] = int(ch.get("score") or 0)
        return rows
    if op == "create_profile":
        data = st.arr_data(svc)
        recipe = RECIPES.get(svc, {}).get(ch.get("recipe"))
        if not recipe:
            raise ActionError(L("Unknown profile recipe", "Ukjent profiloppskrift"))
        if any(p["name"] == recipe["name"] for p in data["profiles"].values()):
            raise ActionError(fmt("A profile named «{n}» already exists", "En profil med navnet «{n}» finnes allerede", n=recipe["name"]))
        base = data["profiles"].get(ch.get("base")) or next(iter(data["profiles"].values()), None)
        if base is None:
            raise ActionError(L("No profile to base it on", "Ingen profil å bygge på"))
        new = from_recipe(base, recipe)
        work[("create", svc, recipe["name"])] = new
        rows.append({"service": svc, "area": "profiles",
                     "what": fmt("New profile «{n}»: {q}, custom formats and language from «{b}»",
                                 "Ny profil «{n}»: {q}, custom formats og språk fra «{b}»",
                                 n=recipe["name"], q=", ".join(allowed_qualities(new)), b=base["name"])})
        return rows
    if op == "remove_completed":
        data = st.arr_data(svc)
        cid = ch.get("client")
        if cid not in data["clients"]:
            raise ActionError(L("The download client no longer exists", "Nedlastingsklienten finnes ikke lenger"))
        c = work.setdefault(("client", svc, cid), copy.deepcopy(data["clients"][cid]))
        want = bool(ch.get("value", True))
        if bool(c.get("removeCompletedDownloads")) != want:
            rows.append({"service": svc, "area": "seeding",
                         "what": fmt("{c}: remove completed downloads after import", "{c}: fjern fullførte nedlastinger etter import",
                                     c=c.get("name")), "before": bool(c.get("removeCompletedDownloads")), "after": want})
            c["removeCompletedDownloads"] = want
        return rows
    if op == "seerr_profile":
        kind = ch.get("kind")
        servers = st.seerr_servers(kind)
        sid = ch.get("server")
        if sid not in servers:
            raise ActionError(L("The Seerr server entry no longer exists", "Serveroppføringen i Seerr finnes ikke lenger"))
        s = work.setdefault(("seerr", kind, sid), copy.deepcopy(servers[sid]))
        field = ch.get("field")
        if field not in ("activeProfileId", "activeAnimeProfileId"):
            raise ActionError(L("Unknown field", "Ukjent felt"))
        name_field = "activeProfileName" if field == "activeProfileId" else "activeAnimeProfileName"
        if s.get(field) != ch.get("profile"):
            rows.append({"service": "seerr", "area": "seerr",
                         "what": fmt("Seerr «{s}»: profile for new requests", "Seerr «{s}»: profil for nye forespørsler", s=s.get("name")),
                         "before": s.get(name_field), "after": ch.get("name")})
            s[field] = ch.get("profile")
            s[name_field] = ch.get("name")
        return rows
    if op == "qbit_prefs":
        prefs, _ = st.qbit()
        p = work.setdefault(("qbit_prefs",), {})
        ratio = ch.get("ratio")
        minutes = ch.get("minutes")
        new = {"max_ratio_enabled": ratio is not None, "max_ratio": float(ratio) if ratio is not None else prefs.get("max_ratio"),
               "max_seeding_time_enabled": minutes is not None,
               "max_seeding_time": int(minutes) if minutes is not None else prefs.get("max_seeding_time"),
               "max_ratio_act": qbit.STOP}
        changed = {k: v for k, v in new.items() if prefs.get(k) != v}
        if changed:
            p.update(changed)
            rows.append({"service": "qbittorrent", "area": "seeding",
                         "what": L("qBittorrent: stop torrents when the seeding limit is reached",
                                   "qBittorrent: stopp torrenter når delingsgrensen er nådd"),
                         "before": _limits_text(prefs), "after": _limits_text({**prefs, **new})})
        return rows
    if op in ("qbit_limits", "qbit_remove"):
        _, torrents = st.qbit()
        hashes = [h for h in ch.get("hashes") or [] if h in torrents]
        if op == "qbit_limits" and hashes:
            work.setdefault(("qbit_limits",), set()).update(hashes)
            rows.append({"service": "qbittorrent", "area": "seeding",
                         "what": fmt("qBittorrent: use the global seeding limit for {n} torrent(s)",
                                     "qBittorrent: bruk den globale delingsgrensen for {n} torrent(er)", n=len(hashes))})
        if op == "qbit_remove":
            from . import downloads
            entries = downloads.overview()["items"]
            ok = []
            for h in hashes:
                t = torrents[h]
                e = _torrent_status(entries, t.get("content_path"))
                if (t.get("progress") or 0) < 1 or not e or e["status"] not in ("hardlinked", "copied"):
                    rows.append({"service": "qbittorrent", "area": "seeding", "skipped": True,
                                 "what": fmt("«{n}» is not imported to a library – kept", "«{n}» er ikke importert til et bibliotek – beholdes",
                                             n=t.get("name"))})
                    continue
                ok.append(h)
                rows.append({"service": "qbittorrent", "area": "seeding", "bytes": e["freed"],
                             "what": fmt("Remove «{n}» from qBittorrent with its downloaded files (the library copy stays)",
                                         "Fjern «{n}» fra qBittorrent med de nedlastede filene (kopien i biblioteket blir)",
                                         n=t.get("name"))})
            if ok:
                work.setdefault(("qbit_remove",), set()).update(ok)
        return rows
    raise ActionError(fmt("Unknown change: {o}", "Ukjent endring: {o}", o=op))


def _seerr_body(server: dict) -> dict:
    """Seerr replaces the whole server entry on PUT, but refuses read-only fields (the id is in the URL)."""
    return {k: v for k, v in server.items() if k != "id"}


def _limits_text(p: dict) -> str:
    parts = []
    if p.get("max_ratio_enabled"):
        parts.append(f"ratio {p.get('max_ratio')}")
    if p.get("max_seeding_time_enabled"):
        parts.append(f"{p.get('max_seeding_time')} min")
    act = {0: "stop", 1: "remove", 2: "super seeding", 3: "remove + files"}.get(p.get("max_ratio_act"), "?")
    return (" / ".join(parts) + f" → {act}") if parts else "–"


def plan(changes: list[dict]) -> dict:
    st = _State()
    work: dict = {}
    rows, errors = [], []
    for i, ch in enumerate(changes[:200]):
        try:
            rows.extend(_plan_one(st, ch, work))
        except (ActionError, ServiceError) as e:
            errors.append({"index": i, "error": e.msg})
    token = hashlib.sha256((st.fingerprint() + json.dumps(changes, sort_keys=True, default=str)).encode()).hexdigest()[:24]
    return {"enabled": actions_enabled(), "rows": rows, "errors": errors,
            "changes": sum(1 for r in rows if not r.get("skipped")), "token": token, "_state": st, "_work": work}


def public(p: dict) -> dict:
    return {k: v for k, v in p.items() if not k.startswith("_")}


BACKUP_DIR = lambda: settings.DATA_DIR / "backups"  # noqa: E731


def _save_backup(st: _State, work: dict, changes: list[dict]) -> str:
    before = {"definitions": {}, "profiles": [], "clients": [], "seerr": [], "qbit_prefs": None, "created": []}
    for key in work:
        kind = key[0]
        if kind == "definitions":
            before["definitions"][key[1]] = st.arr[key[1]]["definitions"]
        elif kind == "profile":
            before["profiles"].append({"service": key[1], "object": st.arr[key[1]]["profiles"][key[2]]})
        elif kind == "client":
            before["clients"].append({"service": key[1], "object": st.arr[key[1]]["clients"][key[2]]})
        elif kind == "seerr":
            before["seerr"].append({"kind": key[1], "object": st.seerr[key[1]][key[2]]})
        elif kind == "qbit_prefs":
            before["qbit_prefs"] = {k: st.qbit_prefs.get(k) for k in work[key]}
    d = BACKUP_DIR()
    d.mkdir(parents=True, exist_ok=True)
    name = f"arr-setup-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path = d / name
    path.write_text(json.dumps({"ts": time.time(), "changes": changes, "before": before}, indent=1), "utf-8")
    os.chmod(path, 0o600)
    return name


def execute(changes: list[dict], token: str) -> dict:
    if not actions_enabled():
        raise Forbidden(L("Changes are switched off under Settings → Deletion",
                          "Endringer er slått av under Innstillinger → Sletting"))
    p = plan(changes)
    if p["token"] != token:
        raise Conflict(L("Radarr, Sonarr, Seerr or qBittorrent changed since the summary was shown. Open it again.",
                         "Radarr, Sonarr, Seerr eller qBittorrent er endret siden oppsummeringen ble vist. Åpne den på nytt."))
    if p["errors"]:
        raise ActionError(p["errors"][0]["error"])
    st, work = p["_state"], p["_work"]
    backup = _save_backup(st, work, changes) if work else None
    created: list[dict] = []
    results = []

    def run(svc, what, fn, bytes_=0):
        try:
            fn()
            status, detail = DONE, what
        except (ActionError, ServiceError) as e:
            status, detail = FAILED, join([what, e.msg], sep=": ")
        except Exception as e:  # unexpected – log, continue with the rest
            log.exception("arr setup change failed")
            status, detail = FAILED, join([what, f"{type(e).__name__}: {e}"], sep=": ")
        with db.conn() as c:
            log_action(c, title=NAMES.get(svc, svc), action="arr_setup", service=svc, status=status, detail=detail, bytes_=bytes_)
        results.append({"service": svc, "what": what, "status": status, "detail": detail})

    for key, obj in work.items():
        kind = key[0]
        if kind == "definitions":
            base, h = _arr_cfg(key[1])
            run(key[1], fmt("Size limits updated", "Størrelsesgrenser oppdatert"),
                lambda b=base, h=h, o=obj, s=key[1]: _send(s, "PUT", f"{b}/api/v3/qualitydefinition/update", h, body=o))
        elif kind == "profile":
            base, h = _arr_cfg(key[1])
            run(key[1], fmt("Profile «{p}» updated", "Profil «{p}» oppdatert", p=obj["name"]),
                lambda b=base, h=h, o=obj, s=key[1]: _send(s, "PUT", f"{b}/api/v3/qualityprofile/{o['id']}", h, body=o))
        elif kind == "create":
            base, h = _arr_cfg(key[1])

            def create(b=base, h=h, o=obj, s=key[1]):
                res = _send(s, "POST", f"{b}/api/v3/qualityprofile", h, body=o) or {}
                created.append({"service": s, "id": res.get("id"), "name": o["name"]})
            run(key[1], fmt("Profile «{p}» created", "Profil «{p}» opprettet", p=obj["name"]), create)
        elif kind == "client":
            base, h = _arr_cfg(key[1])
            run(key[1], fmt("Download client «{c}» updated", "Nedlastingsklient «{c}» oppdatert", c=obj.get("name")),
                lambda b=base, h=h, o=obj, s=key[1]: _send(s, "PUT", f"{b}/api/v3/downloadclient/{o['id']}", h, body=o))
        elif kind == "seerr":
            base, h = _seerr_cfg()
            run("seerr", fmt("Seerr «{s}» updated", "Seerr «{s}» oppdatert", s=obj.get("name")),
                lambda b=base, h=h, o=obj, k=key[1]: _send("seerr", "PUT", f"{b}/api/v1/settings/{k}/{o['id']}", h, body=_seerr_body(o)))
        elif kind == "qbit_prefs":
            def prefs(o=obj):
                with qbit.Client(_qbit_cfg()) as q:
                    q.set_preferences(o)
            run("qbittorrent", L("Seeding limits updated", "Delingsgrenser oppdatert"), prefs)
        elif kind == "qbit_limits":
            def limits(hs=sorted(obj)):
                with qbit.Client(_qbit_cfg()) as q:
                    q.set_share_limits(hs, -2, -2)
            run("qbittorrent", fmt("Global seeding limit applied to {n} torrent(s)",
                                   "Global delingsgrense brukt på {n} torrent(er)", n=len(obj)), limits)
    # Removing torrents last, one by one, so each is logged with its own size
    if ("qbit_remove",) in work:
        from . import downloads
        entries = downloads.overview()["items"]
        for h_ in sorted(work[("qbit_remove",)]):
            t = st.qbit_torrents[h_]
            e = _torrent_status(entries, t.get("content_path"))

            def remove(hs=[h_]):
                with qbit.Client(_qbit_cfg()) as q:
                    q.delete(hs, delete_files=True)
            run("qbittorrent", fmt("Removed «{n}» from qBittorrent with its files", "Fjernet «{n}» fra qBittorrent med filer",
                                   n=t.get("name")), remove, bytes_=(e or {}).get("freed", 0))
    if backup and created:
        path = BACKUP_DIR() / backup
        data = json.loads(path.read_text("utf-8"))
        data["before"]["created"] = created
        path.write_text(json.dumps(data, indent=1), "utf-8")
    if ("qbit_remove",) in work:
        from . import jobs
        jobs.enqueue("refresh")
    done = [r for r in results if r["status"] == DONE]
    return {"results": results, "done": len(done), "failed": len(results) - len(done), "backup": backup}


# ================================================================== backups / restore

def backups() -> list[dict]:
    d = BACKUP_DIR()
    out = []
    for f in sorted(d.glob("arr-setup-*.json"), reverse=True)[:30]:
        try:
            data = json.loads(f.read_text("utf-8"))
        except Exception:
            continue
        b = data.get("before", {})
        out.append({"name": f.name, "ts": data.get("ts"), "changes": len(data.get("changes") or []),
                    "objects": len(b.get("definitions") or {}) + len(b.get("profiles") or []) + len(b.get("clients") or [])
                    + len(b.get("seerr") or []) + (1 if b.get("qbit_prefs") else 0) + len(b.get("created") or [])})
    return out


def _backup_file(name: str) -> Path:
    if not re.fullmatch(r"arr-setup-\d{8}-\d{6}\.json", name or ""):
        raise ActionError(L("Unknown backup", "Ukjent sikkerhetskopi"))
    path = BACKUP_DIR() / name
    if not path.is_file():
        raise ActionError(L("Unknown backup", "Ukjent sikkerhetskopi"))
    return path


def restore(name: str) -> dict:
    """Puts everything in a backup back as it was. Profiles created by that change are deleted
    (Radarr/Sonarr refuse if titles use them – then they stay)."""
    if not actions_enabled():
        raise Forbidden(L("Changes are switched off under Settings → Deletion",
                          "Endringer er slått av under Innstillinger → Sletting"))
    data = json.loads(_backup_file(name).read_text("utf-8"))
    b = data.get("before", {})
    results = []

    def run(svc, what, fn):
        try:
            fn()
            status, detail = DONE, what
        except (ActionError, ServiceError) as e:
            status, detail = FAILED, join([what, e.msg], sep=": ")
        with db.conn() as c:
            log_action(c, title=NAMES.get(svc, svc), action="arr_setup_restore", service=svc, status=status, detail=detail)
        results.append({"service": svc, "what": what, "status": status, "detail": detail})

    for svc, defs in (b.get("definitions") or {}).items():
        base, h = _arr_cfg(svc)
        run(svc, L("Size limits restored", "Størrelsesgrenser gjenopprettet"),
            lambda b_=base, h=h, o=defs, s=svc: _send(s, "PUT", f"{b_}/api/v3/qualitydefinition/update", h, body=o))
    for p in b.get("profiles") or []:
        base, h = _arr_cfg(p["service"])
        o = p["object"]
        run(p["service"], fmt("Profile «{p}» restored", "Profil «{p}» gjenopprettet", p=o["name"]),
            lambda b_=base, h=h, o=o, s=p["service"]: _send(s, "PUT", f"{b_}/api/v3/qualityprofile/{o['id']}", h, body=o))
    for p in b.get("created") or []:
        if not p.get("id"):
            continue
        base, h = _arr_cfg(p["service"])
        run(p["service"], fmt("Profile «{p}» deleted", "Profil «{p}» slettet", p=p["name"]),
            lambda b_=base, h=h, i=p["id"], s=p["service"]: _send(s, "DELETE", f"{b_}/api/v3/qualityprofile/{i}", h))
    for c_ in b.get("clients") or []:
        base, h = _arr_cfg(c_["service"])
        o = c_["object"]
        run(c_["service"], fmt("Download client «{c}» restored", "Nedlastingsklient «{c}» gjenopprettet", c=o.get("name")),
            lambda b_=base, h=h, o=o, s=c_["service"]: _send(s, "PUT", f"{b_}/api/v3/downloadclient/{o['id']}", h, body=o))
    for s_ in b.get("seerr") or []:
        base, h = _seerr_cfg()
        o = s_["object"]
        run("seerr", fmt("Seerr «{s}» restored", "Seerr «{s}» gjenopprettet", s=o.get("name")),
            lambda b_=base, h=h, o=o, k=s_["kind"]: _send("seerr", "PUT", f"{b_}/api/v1/settings/{k}/{o['id']}", h, body=_seerr_body(o)))
    if b.get("qbit_prefs"):
        def prefs(o=b["qbit_prefs"]):
            with qbit.Client(_qbit_cfg()) as q:
                q.set_preferences(o)
        run("qbittorrent", L("Seeding limits restored", "Delingsgrenser gjenopprettet"), prefs)
    done = [r for r in results if r["status"] == DONE]
    return {"results": results, "done": len(done), "failed": len(results) - len(done)}
