"""Kobler filer -> titler (filmer/serier) og aggregerer seerhistorikk per tittel og sesong.

Nøkkelen er vertssti. Prioritet for tittel: Radarr-/Sonarr-mappe > toppnivåmappe i biblioteket.
Plex-elementer knyttes til tittelen via filene (Media/Part), og Tautulli-avspillinger via Plex ratingKey,
med navn+år som reserve når ratingKey har endret seg.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .. import db

YEAR_RE = re.compile(r"^(.+?)\s*\((\d{4})\)\s*$")
EP_RE = re.compile(r"[Ss](\d{1,3})[ ._-]?[Ee](\d{1,4})")
MONTH = 30.44 * 86400


def res_rank(res: str | None) -> int:
    if not res:
        return 0
    r = str(res).lower()
    if "2160" in r or "4k" in r or "uhd" in r:
        return 2160
    for n in (1080, 720, 576, 480):
        if str(n) in r:
            return n
    if r in ("sd",):
        return 480
    return 0


def res_label(rank: int) -> str | None:
    return {2160: "4K", 1080: "1080p", 720: "720p", 576: "576p", 480: "SD"}.get(rank)


@dataclass
class FileRec:
    path: str
    library: str
    size: int
    alloc: int
    inode: int
    dev: int
    nlink: int
    mtime: float
    is_video: bool
    is_extra: bool
    ext: str
    phash: str | None
    title_key: str | None = None
    season: int | None = None
    episode: int | None = None
    resolution: int = 0
    managed: bool = False  # Radarr/Sonarr kjenner akkurat denne filen

    @property
    def ino(self) -> tuple[int, int]:
        return (self.dev, self.inode)


@dataclass
class Title:
    key: str
    kind: str
    name: str
    year: int | None
    library: str
    folder: str
    radarr_id: int | None = None
    sonarr_id: int | None = None
    plex_keys: set = field(default_factory=set)
    monitored: bool | None = None
    added: int | None = None
    tags: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    protected: bool = False
    protect_reason: str | None = None
    files: list = field(default_factory=list)
    play_count: int = 0
    last_played: int | None = None
    users: set = field(default_factory=set)
    recent_users: set = field(default_factory=set)
    requested_by: str | None = None
    requested_at: int | None = None
    requests: list = field(default_factory=list)       # [{by, plex_username, at, watched}]
    viewer_names: set = field(default_factory=set)    # visningsnavn + brukernavn, små bokstaver
    seasons_monitored: dict = field(default_factory=dict)
    season_stats: dict = field(default_factory=dict)  # season -> {plays,last,users,recent_users}

    def unique_files(self):
        seen, out = set(), []
        for f in self.files:
            if f.ino not in seen:
                seen.add(f.ino)
                out.append(f)
        return out

    @property
    def size(self) -> int:
        return sum(f.size for f in self.unique_files())

    @property
    def alloc(self) -> int:
        return sum(f.alloc for f in self.unique_files())

    @property
    def videos(self):
        return [f for f in self.files if f.is_video and not f.is_extra]

    @property
    def best_resolution(self) -> int:
        return max((f.resolution for f in self.videos), default=0)


@dataclass
class Model:
    files: list[FileRec]
    titles: dict[str, Title]
    libs: dict[str, dict]
    history_start: int | None
    now: float
    inode_paths: dict  # (dev,inode) -> [paths]
    downloads: list[FileRec]


def build(c, s: dict, now: float) -> Model:
    libs = {l["name"]: l for l in s["libraries"]}
    prot = s["protection"]
    prot_tags = {t.lower() for t in prot.get("tags", [])}
    prot_paths = [p.rstrip("/") for p in prot.get("paths", []) if p]
    recent_cut = now - s["analysis"]["recent_play_months"] * MONTH

    files: list[FileRec] = []
    for r in c.execute("SELECT path,library,size,alloc,inode,dev,nlink,mtime,is_video,is_extra,ext,phash FROM files"):
        files.append(FileRec(r[0], r[1], r[2], r[3] or r[2], r[4], r[5], r[6], r[7], bool(r[8]), bool(r[9]),
                             r[10] or "", r[11]))
    inode_paths: dict = defaultdict(list)
    for f in files:
        inode_paths[f.ino].append(f.path)

    radarr = db.rows(c, "SELECT * FROM radarr_movies")
    sonarr = db.rows(c, "SELECT * FROM sonarr_series")
    sonarr_files = {r["path"]: r for r in db.rows(c, "SELECT path, season, resolution, series_id FROM sonarr_files")}
    radarr_files = {r["file_path"]: r for r in radarr if r["file_path"]}
    plex_items = {r["rating_key"]: r for r in db.rows(c, "SELECT * FROM plex_items")}
    plex_parts: dict[str, list] = defaultdict(list)
    for r in db.rows(c, "SELECT path, rating_key, resolution FROM plex_parts"):
        plex_parts[r["path"]].append(r)

    folder_key: dict[str, str] = {}
    titles: dict[str, Title] = {}
    for m in radarr:
        if not m["path"]:
            continue
        k = f"movie:r:{m['id']}"
        folder_key[m["path"].rstrip("/")] = k
        titles[k] = Title(k, "movie", m["title"], m["year"], "", m["path"].rstrip("/"), radarr_id=m["id"],
                          monitored=bool(m["monitored"]), added=m["added"], tags=json.loads(m["tags"] or "[]"))
    for sr in sonarr:
        if not sr["path"]:
            continue
        k = f"series:s:{sr['id']}"
        folder_key[sr["path"].rstrip("/")] = k
        titles[k] = Title(k, "series", sr["title"], sr["year"], "", sr["path"].rstrip("/"), sonarr_id=sr["id"],
                          monitored=bool(sr["monitored"]), added=sr["added"], tags=json.loads(sr["tags"] or "[]"),
                          seasons_monitored={int(a): b for a, b in json.loads(sr["seasons"] or "{}").items()})

    downloads: list[FileRec] = []
    for f in files:
        lib = libs.get(f.library)
        if not lib:
            continue
        if lib.get("kind") == "downloads":
            downloads.append(f)
            continue
        key = None
        d = os.path.dirname(f.path)
        root = lib["host_path"].rstrip("/")
        while len(d) >= len(root):
            if d in folder_key:
                key = folder_key[d]
                break
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
        if key is None:
            rel = f.path[len(root) + 1:]
            top = rel.split("/", 1)[0]
            folder = root + "/" + top
            key = f"dir:{f.library}:{top}"
            if key not in titles:
                raw = os.path.splitext(top)[0] if "/" not in rel else top
                ym = YEAR_RE.match(raw)
                titles[key] = Title(key, "unknown", ym.group(1).strip() if ym else raw,
                                    int(ym.group(2)) if ym else None, f.library, folder)
        t = titles[key]
        if not t.library:
            t.library = f.library
        f.title_key = key
        t.files.append(f)

        # sesong/episode + oppløsning
        sf = sonarr_files.get(f.path)
        rf = radarr_files.get(f.path)
        if sf:
            f.season, f.managed = sf["season"], True
            f.resolution = res_rank(sf["resolution"])
        if rf:
            f.managed = True
            f.resolution = res_rank(rf["resolution"])
        m = EP_RE.search(os.path.basename(f.path))
        if m:
            if f.season is None:
                f.season = int(m.group(1))
            f.episode = int(m.group(2))
        for p in plex_parts.get(f.path, []):
            it = plex_items.get(p["rating_key"])
            if not f.resolution:
                f.resolution = res_rank(p["resolution"])
            if not it:
                continue
            if it["kind"] == "episode":
                t.plex_keys.add(("show", it["show_key"]))
                if f.season is None:
                    f.season = it["season"]
                if f.episode is None:
                    f.episode = it["episode"]
            else:
                t.plex_keys.add(("movie", it["rating_key"]))

    # Fjern Radarr/Sonarr-titler uten filer på disk (ingenting å frigjøre)
    titles = {k: t for k, t in titles.items() if t.files}

    for t in titles.values():
        lib = libs.get(t.library, {})
        # type, navn og lagt-til for titler utenfor Radarr/Sonarr
        if t.kind == "unknown":
            kinds = {k for k, _ in t.plex_keys}
            if "show" in kinds:
                t.kind = "series"
            elif "movie" in kinds:
                t.kind = "movie"
            elif lib.get("kind") == "series" or any(f.episode is not None for f in t.videos):
                t.kind = "series"
            else:
                t.kind = "movie"
        plex_added = []
        for kind, rk in t.plex_keys:
            it = plex_items.get(rk)
            if it:
                plex_added.append(it["added_at"])
                t.labels += json.loads(it["labels"] or "[]")
                if t.key.startswith("dir:"):
                    t.name, t.year = it["title"] or t.name, it["year"] or t.year
        if not t.added:
            cands = [a for a in plex_added if a] or [int(f.mtime) for f in t.videos] or [int(f.mtime) for f in t.files]
            t.added = min(cands) if cands else None
        # Beskyttelse
        reasons = []
        if lib.get("protected"):
            reasons.append(f"Biblioteket {t.library} er beskyttet")
        tagged = [x for x in t.tags if x.lower() in prot_tags]
        if tagged:
            reasons.append(f"Tagget «{tagged[0]}» i {'Radarr' if t.radarr_id else 'Sonarr'}")
        if t.labels:
            reasons.append(f"Plex-etikett «{t.labels[0]}»")
        if any(t.folder == p or t.folder.startswith(p + "/") for p in prot_paths):
            reasons.append("Beskyttet sti")
        if reasons:
            t.protected, t.protect_reason = True, "; ".join(reasons)

    # ---- Avspillinger ----
    movie_by_rk, show_by_rk = {}, {}
    movie_by_name, show_by_name = defaultdict(list), defaultdict(list)
    for t in titles.values():
        for kind, rk in t.plex_keys:
            (movie_by_rk if kind == "movie" else show_by_rk)[rk] = t
        n = _norm(t.name)
        if t.kind == "movie":
            movie_by_name[(n, t.year)].append(t)
        else:
            show_by_name[n].append(t)

    history_start = c.execute("SELECT MIN(date) FROM plays").fetchone()[0]
    for p in db.rows(c, "SELECT * FROM plays WHERE percent IS NULL OR percent >= 5"):
        t = None
        if p["media_type"] == "movie":
            t = movie_by_rk.get(p["rating_key"])
            if t is None:
                cand = movie_by_name.get((_norm(p["title"]), p["year"]))
                t = cand[0] if cand and len(cand) == 1 else None
        else:
            t = show_by_rk.get(p["grandparent_key"])
            if t is None:
                cand = show_by_name.get(_norm(p["grandparent_title"]))
                t = cand[0] if cand and len(cand) == 1 else None
        if t is None:
            continue
        date = p["date"] or 0
        t.play_count += 1
        t.last_played = max(t.last_played or 0, date) or None
        if p["user"]:
            t.users.add(p["user"])
            if date >= recent_cut:
                t.recent_users.add(p["user"])
        for n in (p["user"], p.get("username")):
            if n:
                t.viewer_names.add(n.lower())
        if t.kind == "series" and p["parent_index"] is not None:
            ss = t.season_stats.setdefault(p["parent_index"], {"plays": 0, "last": None, "users": set(), "recent_users": set()})
            ss["plays"] += 1
            ss["last"] = max(ss["last"] or 0, date) or None
            if p["user"]:
                ss["users"].add(p["user"])
                if date >= recent_cut:
                    ss["recent_users"].add(p["user"])

    # ---- Forespørsler (Seerr) ----
    by_tmdb = {m["tmdb_id"]: f"movie:r:{m['id']}" for m in radarr if m["tmdb_id"]}
    by_tvdb = {sr["tvdb_id"]: f"series:s:{sr['id']}" for sr in sonarr if sr["tvdb_id"]}
    by_plex = {rk: t for t in titles.values() for _, rk in t.plex_keys}
    for r in db.rows(c, "SELECT * FROM requests ORDER BY created"):
        k = by_tmdb.get(r["tmdb_id"]) if r["media_type"] == "movie" else by_tvdb.get(r["tvdb_id"])
        t = titles.get(k) if k else None
        if t is None and r.get("rating_key"):
            t = by_plex.get(r["rating_key"])  # f.eks. titler som ikke ligger i Radarr/Sonarr
        if t is None or not r["requested_by"]:
            continue
        names = {n.lower() for n in (r["requested_by"], r.get("plex_username")) if n}
        t.requests.append({"by": r["requested_by"], "plex_username": r.get("plex_username"),
                           "at": r["created"], "watched": bool(names & t.viewer_names)})
        if r["created"] and (t.requested_at or 0) <= r["created"]:
            t.requested_by, t.requested_at = r["requested_by"], r["created"]

    return Model(files, titles, libs, history_start, now, inode_paths, downloads)


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
