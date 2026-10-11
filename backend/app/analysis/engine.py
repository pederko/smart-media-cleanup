"""Duplicates, suggestions, explainable scores and savings without double counting."""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .. import db, settings
from ..i18n import L, date, fmt, gb, join, store
from .linking import MONTH, FileRec, Model, Title, build, res_label

GB = 1024 ** 3


# ---------------------------------------------------------------- savings

def freed_bytes(claims: dict[str, int], file_info: dict[str, dict], inode_paths: dict,
                per_path: dict | None = None) -> tuple[int, int]:
    """claims: path -> bytes the suggestion claims to free for that file.

    Rules:
      * An inode is counted once (the largest claim across suggestions).
      * An inode is only freed if ALL known paths to it are included and there are no unknown
        hardlinks (nlink == number of known paths). Otherwise it frees 0.
    Returns (freed, held_by_hardlinks).
    """
    by_ino: dict[tuple, dict] = {}
    for path, claim in claims.items():
        fi = file_info.get(path)
        if not fi:
            continue
        ino = (fi["dev"], fi["inode"])
        e = by_ino.setdefault(ino, {"claim": 0, "paths": set(), "nlink": fi["nlink"]})
        e["claim"] = max(e["claim"], claim)
        e["paths"].add(path)
    freed = held = 0
    for ino, e in by_ino.items():
        known = set(inode_paths.get(ino, []))
        if e["nlink"] <= len(known) and known <= e["paths"]:
            freed += e["claim"]
            if per_path is not None:
                per_path[min(e["paths"])] = e["claim"]
        else:
            held += e["claim"]
    return freed, held


# ---------------------------------------------------------------- duplicates

@dataclass
class DupGroup:
    kind: str           # hardlink | identical | versions
    title_key: str | None
    label: dict
    files: list[FileRec]
    keep: FileRec | None
    reason_keep: dict | None = None

    @property
    def id(self) -> str:
        return hashlib.sha1((self.kind + "|" + "|".join(sorted(f.path for f in self.files))).encode()).hexdigest()[:16]


def _keep_choice(files: list[FileRec], libs: dict) -> tuple[FileRec, dict]:
    """Which file to keep: library over downloads, then managed by Radarr/Sonarr, resolution, size."""
    def rank(f: FileRec):
        lib = libs.get(f.library, {})
        return (lib.get("kind") != "downloads", f.managed, f.resolution, f.size)
    best = max(files, key=rank)
    if best.managed:
        why = L("managed by Radarr/Sonarr", "administreres av Radarr/Sonarr")
    elif libs.get(best.library, {}).get("kind") != "downloads":
        why = fmt("in the library {lib}", "ligger i biblioteket {lib}", lib=best.library)
    else:
        why = L("highest quality", "høyest kvalitet")
    if best.resolution and not best.managed and res_label(best.resolution):
        why = L(f"{why['en']}, {res_label(best.resolution)}", f"{why['nb']}, {res_label(best.resolution)}")
    return best, why


def _name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def find_duplicates(m: Model) -> list[DupGroup]:
    groups: list[DupGroup] = []
    all_files = [f for t in m.titles.values() for f in t.files] + m.downloads
    # 1) Hardlinks: same inode, several paths. Not a duplicate, nothing to gain.
    by_ino = defaultdict(list)
    for f in all_files:
        by_ino[f.ino].append(f)
    for ino, fs in by_ino.items():
        if len(fs) > 1:
            groups.append(DupGroup("hardlink", fs[0].title_key,
                                   fmt("Hardlinked: {n}", "Hardlenket: {n}", n=_name(fs[0].path)),
                                   fs, None, L("same file on disk", "samme fil på disk")))
    # 2) Identical content: same size + partial hash, different inode
    by_hash = defaultdict(dict)
    for f in all_files:
        if f.phash:
            by_hash[(f.size, f.phash)].setdefault(f.ino, f)
    identical_inos = set()
    for (size, ph), inos in by_hash.items():
        if len(inos) > 1:
            fs = list(inos.values())
            keep, why = _keep_choice(fs, m.libs)
            identical_inos.update(inos.keys())
            groups.append(DupGroup("identical", keep.title_key,
                                   fmt("Identical copies: {n}", "Identiske kopier: {n}", n=_name(keep.path)),
                                   fs, keep, why))
    # 3) Alternative versions of the same movie/episode (different content)
    for t in m.titles.values():
        buckets = defaultdict(dict)
        for f in t.videos:
            if t.kind == "movie":
                buckets["movie"].setdefault(f.ino, f)
            elif f.season is not None and f.episode is not None:
                buckets[(f.season, f.episode)].setdefault(f.ino, f)
        for b, inos in buckets.items():
            fs = list(inos.values())
            if len(fs) < 2:
                continue
            # Already covered above if they are all identical copies
            if all(f.ino in identical_inos for f in fs) and len({(f.size, f.phash) for f in fs}) == 1:
                continue
            keep, why = _keep_choice(fs, m.libs)
            where = t.name if b == "movie" else f"{t.name} S{b[0]:02d}E{b[1]:02d}"
            groups.append(DupGroup("versions", t.key, fmt("Several versions: {w}", "Flere versjoner: {w}", w=where),
                                   fs, keep, why))
    return groups


# ---------------------------------------------------------------- suggestions

@dataclass
class Suggestion:
    kind: str           # delete_title | delete_season | replace | remove_versions | remove_copy | download
    title: Title | None
    scope: str
    action: str
    label: dict
    location: str
    claims: dict = field(default_factory=dict)  # path -> bytes
    components: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    consequences: list = field(default_factory=list)
    risk: str = "medium"   # low | medium | high
    history: dict = field(default_factory=dict)
    savings_note: list = field(default_factory=list)
    name: str = ""         # what the suggestion is about (title name, file name, folder)

    @property
    def id(self) -> str:
        base = f"{self.kind}|{self.title.key if self.title else ''}|{self.scope}|{self.location}"
        return hashlib.sha1(base.encode()).hexdigest()[:16]


def _months(now: float, ts: int | None) -> float | None:
    return None if not ts else (now - ts) / MONTH


def _comp(key: str, label: dict, points: float, detail: dict, w: dict, tag: str = "") -> dict:
    out = {"key": key, "label": label, "points": round(points * w.get(key, 1.0), 1), "detail": detail}
    if tag:
        out["tag"] = tag
    return out


def _space_comp(claim_bytes: int, w: dict) -> dict:
    g = claim_bytes / GB
    pts = min(35.0, 12 * math.log2(1 + g / 10))
    return _comp("space", L("Space", "Plass"), pts, fmt("{s} can be freed", "{s} kan frigjøres", s=gb(claim_bytes)), w,
                 tag="space")


def _usage_comps(m: Model, s: dict, w: dict, plays: int, last: int | None, users: set, recent_users: set,
                 added: int | None, size_gb: float) -> list[dict]:
    a = s["analysis"]
    stale = sorted(a["stale_months"])
    out = []
    hs = m.history_start
    if plays == 0:
        if hs and added and added < hs:
            out.append(_comp("staleness", L("Never watched", "Aldri sett"), 30,
                             fmt("No plays since the history started {d}", "Ingen avspillinger siden historikken startet {d}",
                                 d=date(hs)), w))
        elif hs:
            out.append(_comp("staleness", L("Never watched", "Aldri sett"), 22,
                             fmt("No plays since it was added {d}", "Ingen avspillinger siden den ble lagt til {d}",
                                 d=date(added)), w))
        else:
            out.append(_comp("staleness", L("No history", "Ingen historikk"), 0,
                             L("Tautulli history is missing – cannot judge viewing",
                               "Tautulli-historikk mangler – kan ikke vurdere seing"), w))
    else:
        mo = _months(m.now, last) or 0
        for limit, pts in ((stale[2], 25), (stale[1], 18), (stale[0], 10)):
            if mo >= limit:
                txt = fmt("Not watched for {mo:.0f} months (≥ {lim})", "Ikke sett på {mo:.0f} måneder (≥ {lim})",
                          mo=mo, lim=limit)
                break
        else:
            if mo < 3:
                pts, txt = -20, fmt("Watched {mo:.0f} months ago", "Sett for {mo:.0f} måneder siden", mo=max(mo, 0))
            else:
                pts, txt = 0, fmt("Last watched {d}", "Sist sett {d}", d=date(last))
        out.append(_comp("staleness", L("Last watched", "Sist sett"), pts, txt, w))
        if plays <= 2 and size_gb >= 20:
            out.append(_comp("consumption", L("Little use", "Lavt konsum"), 8,
                             fmt("Only {p} play(s) for {s}", "Bare {p} avspilling(er) for {s}", p=plays,
                                 s=gb(size_gb * GB, 0)), w))
        elif plays >= 10:
            out.append(_comp("consumption", L("Much used", "Mye brukt"), -10,
                             fmt("{p} plays in total", "{p} avspillinger totalt", p=plays), w))
    if recent_users:
        n = len(recent_users)
        out.append(_comp("viewers", L("Viewers", "Seere"), -min(30, 6 * n),
                         fmt("{n} user(s) watched in the last {mo} months", "{n} bruker(e) har sett siste {mo} mnd",
                             n=n, mo=a["recent_play_months"]), w))
    elif len(users) >= 3:
        out.append(_comp("viewers", L("Viewers", "Seere"), -5,
                         fmt("{n} different users have watched before", "{n} ulike brukere har sett tidligere",
                             n=len(users)), w))
    mo_added = _months(m.now, added)
    if mo_added is not None and mo_added < a["quarantine_months"]:
        out.append(_comp("recent", L("Recently added", "Nylig lagt til"), -40,
                         fmt("Added {d} (quarantine {q} months)", "Lagt til {d} (karantene {q} mnd)",
                             d=date(added), q=a["quarantine_months"]), w))
    return out


def _arr_comp(t: Title, w: dict, season: int | None = None) -> dict | None:
    if t.radarr_id is not None:
        return (_comp("monitored", L("Radarr", "Radarr"), -8, L("Monitored in Radarr", "Overvåket i Radarr"), w)
                if t.monitored else
                _comp("monitored", L("Radarr", "Radarr"), 5, L("Not monitored in Radarr", "Ikke overvåket i Radarr"), w))
    if t.sonarr_id is not None:
        mon = t.monitored if season is None else (t.monitored and t.seasons_monitored.get(season, False))
        what_en = "The series" if season is None else f"Season {season}"
        what_nb = "Serien" if season is None else f"Sesong {season}"
        return (_comp("monitored", L("Sonarr", "Sonarr"), -8,
                      L(f"{what_en} is monitored in Sonarr", f"{what_nb} er overvåket i Sonarr"), w) if mon else
                _comp("monitored", L("Sonarr", "Sonarr"), 5,
                      L(f"{what_en} is not monitored in Sonarr", f"{what_nb} er ikke overvåket i Sonarr"), w))
    return None


def _request_comp(m: Model, t: Title, w: dict) -> dict | None:
    if not t.requests:
        return None
    if t.requested_at and _months(m.now, t.requested_at) < 12:
        return _comp("request", L("Recently requested", "Etterspurt nylig"), -15,
                     fmt("Requested by {who} {d}", "Etterspurt av {who} {d}", who=t.requested_by, d=date(t.requested_at)), w)
    who = ", ".join(sorted({r["by"] for r in t.requests}))
    unwatched = {r["by"] for r in t.requests if not r["watched"]}
    if unwatched and len(unwatched) == len({r["by"] for r in t.requests}):
        return _comp("request", L("Requested, not watched", "Etterspurt, ikke sett"), 8,
                     fmt("Requested by {who} ({d}), but none of them have watched it",
                         "Etterspurt av {who} ({d}), men ingen av dem har sett den", who=who, d=date(t.requested_at)), w)
    return _comp("request", L("Requested", "Etterspurt"), 0,
                 fmt("Requested by {who}, who have watched it", "Etterspurt av {who}, som har sett den", who=who), w)


def _consequences(t: Title | None, kind: str, season: int | None = None) -> list[dict]:
    if t is None:
        return [L("The file is in the downloads folder. If it is an active torrent, remove it in the download client – "
                  "otherwise seeding will fail.",
                  "Filen ligger i nedlastingsmappen. Er den en aktiv torrent, fjern den i nedlastingsklienten – "
                  "ellers feiler delingen.")]
    if kind == "remove_copy":
        return [L("The content still exists as an identical copy. Plex/Radarr/Sonarr are not affected as long as the "
                  "copy that is kept is the one they point to.",
                  "Innholdet finnes fortsatt i en identisk kopi. Plex/Radarr/Sonarr påvirkes ikke så lenge kopien som "
                  "beholdes er den de peker på.")]
    out = []
    if t.radarr_id is not None:
        if kind == "delete_title":
            out.append(L("Deleted through Radarr with its files, without an import exclusion. "
                         "If the files were removed directly instead, Radarr would "
                         + ("download the movie again because it is monitored." if t.monitored else "show it as missing."),
                         "Slettes via Radarr med filene, uten importekskludering. Slettes filene direkte i stedet, vil "
                         "Radarr " + ("laste filmen ned igjen fordi den er overvåket." if t.monitored
                                      else "vise den som manglende.")))
        elif kind == "replace":
            out.append(L("Use «Find a smaller version» to download a smaller release first and swap afterwards.",
                         "Bruk «Finn mindre versjon» for å laste ned en mindre utgivelse først og bytte etterpå."))
        elif kind == "remove_versions":
            out.append(L("The extra versions are not managed by Radarr; Radarr is not affected.",
                         "Ekstra versjoner administreres ikke av Radarr; Radarr påvirkes ikke."))
    elif t.sonarr_id is not None:
        if kind == "delete_title":
            out.append(L("The series is deleted in Sonarr with its files – otherwise monitored episodes would be "
                         "downloaded again.",
                         "Serien slettes i Sonarr med filene – ellers lastes overvåkede episoder ned igjen."))
        elif kind == "delete_season":
            mon = t.monitored and t.seasons_monitored.get(season, False)
            out.append(L(f"Season {season} is unmonitored in Sonarr before the files are deleted"
                         + (" (it is monitored now)." if mon else "."),
                         f"Sesong {season} avovervåkes i Sonarr før filene slettes" + (" (den er overvåket nå)." if mon else ".")))
        elif kind == "replace":
            out.append(L("Use «Find a smaller version» to download a smaller season pack first and swap afterwards.",
                         "Bruk «Finn mindre versjon» for å laste ned en mindre sesongpakke først og bytte etterpå."))
        elif kind == "remove_versions":
            out.append(L("Sonarr points to one of the files; the others are unmanaged.",
                         "Sonarr peker på én av filene; de andre er uadministrerte."))
    else:
        out.append(L("Not managed by Radarr/Sonarr – deleted on disk only.",
                     "Ikke administrert av Radarr/Sonarr – slettes bare på disk."))
    if t.plex_keys:
        out.append(L("Plex removes the title at the next library scan (with «Empty trash»). Watch history in Tautulli is kept.",
                     "Plex fjerner tittelen ved neste bibliotekskanning (med «Empty trash»). Seerhistorikken i Tautulli beholdes."))
    return out


def _risk_delete(m: Model, s: dict, t: Title, plays: int, last: int | None, recent_users: set) -> str:
    a = s["analysis"]
    recent = last and _months(m.now, last) < a["recent_play_months"]
    new = t.added and _months(m.now, t.added) < a["quarantine_months"]
    req = t.requested_at and _months(m.now, t.requested_at) < 12
    if recent or len(recent_users) >= 2 or new or req:
        return "high"
    if t.monitored or plays > 0:
        return "medium"
    return "low"


def _history(m: Model, plays, last, users, recent_users) -> dict:
    return {"plays": plays, "last_played": last, "users": sorted(users), "recent_users": sorted(recent_users),
            "history_start": m.history_start}


def make_suggestions(m: Model, s: dict, dups: list[DupGroup]) -> list[Suggestion]:
    a, w = s["analysis"], s["weights"]
    min_b = a["min_suggestion_gb"] * GB
    out: list[Suggestion] = []

    for t in m.titles.values():
        if t.protected or not t.files:
            continue
        size = t.alloc
        size_gb = size / GB
        arr = _arr_comp(t, w)
        req = _request_comp(m, t, w)

        # --- delete the whole title
        if size >= min_b:
            comps = [_space_comp(size, w)] + _usage_comps(m, s, w, t.play_count, t.last_played, t.users,
                                                         t.recent_users, t.added, size_gb)
            comps += [c for c in (arr, req) if c]
            label = L("Delete the movie", "Slett filmen") if t.kind == "movie" else L("Delete the whole series", "Slett hele serien")
            out.append(Suggestion("delete_title", t, "title", "delete", label, t.folder, name=t.name,
                                  claims={f.path: f.alloc for f in t.files}, components=comps,
                                  consequences=_consequences(t, "delete_title"),
                                  risk=_risk_delete(m, s, t, t.play_count, t.last_played, t.recent_users),
                                  history=_history(m, t.play_count, t.last_played, t.users, t.recent_users)))

        # --- delete single seasons nobody watches while other seasons are watched
        if t.kind == "series":
            seasons = defaultdict(list)
            for f in t.files:
                if f.season is not None:
                    seasons[f.season].append(f)
            if t.play_count > 0 and len(seasons) > 1:
                for sn, fs in sorted(seasons.items()):
                    ss = t.season_stats.get(sn, {"plays": 0, "last": None, "users": set(), "recent_users": set()})
                    s_size = sum(f.alloc for f in {f.ino: f for f in fs}.values())
                    mo = _months(m.now, ss["last"])
                    if s_size < min_b or (mo is not None and mo < a["stale_months"][0]):
                        continue
                    comps = [_space_comp(s_size, w)]
                    comps += _usage_comps(m, s, w, ss["plays"], ss["last"], ss["users"], ss["recent_users"],
                                          min((int(f.mtime) for f in fs), default=None), s_size / GB)
                    comps.append(_comp("consumption", L("The rest of the series is watched", "Resten av serien sees"), 0,
                                       fmt("The series has {p} plays in total, last {d}",
                                           "Serien er sett {p} ganger totalt, sist {d}", p=t.play_count,
                                           d=date(t.last_played)), w))
                    sc = _arr_comp(t, w, sn)
                    if sc:
                        comps.append(sc)
                    if req and req["points"] < 0:
                        comps.append(req)
                    risk = "medium" if (ss["plays"] or (t.monitored and t.seasons_monitored.get(sn))) else "low"
                    out.append(Suggestion("delete_season", t, f"season:{sn}", "delete",
                                          L(f"Delete season {sn}", f"Slett sesong {sn}"), t.folder,
                                          name=f"{t.name} – S{sn}",
                                          claims={f.path: f.alloc for f in fs}, components=comps,
                                          consequences=_consequences(t, "delete_season", sn), risk=risk,
                                          history=_history(m, ss["plays"], ss["last"], ss["users"], ss["recent_users"])))

        # --- replace large files with a smaller version
        if t.kind == "movie":
            big = [f for f in t.videos if f.size >= a["large_movie_gb"] * GB]
            target = a["target_movie_gb"] * GB
        else:
            big = [f for f in t.videos if f.size >= a["large_episode_gb"] * GB]
            target = a["target_episode_gb"] * GB
        if big:
            claims = {f.path: max(0, f.alloc - target) for f in big}
            claim_sum = sum(claims.values())
            if claim_sum >= min_b:
                res = res_label(max(f.resolution for f in big))
                isos = sum(1 for f in big if f.ext in (".iso", ".img"))
                detail = L(f"{len(big)} file(s) over the limit ({res or 'unknown resolution'})" + (f", {isos} ISO" if isos else ""),
                           f"{len(big)} fil(er) over grensen ({res or 'ukjent oppløsning'})" + (f", {isos} ISO" if isos else ""))
                comps = [_space_comp(claim_sum, w),
                         _comp("versions", L("Keeps the title", "Beholder tittelen"), 10,
                               L("The title is kept in a lower quality", "Tittelen beholdes i lavere kvalitet"), w),
                         _comp("space", L("Large file", "Stor fil"), 0, detail, w)]
                comps += [c for c in _usage_comps(m, s, w, t.play_count, t.last_played, t.users, t.recent_users,
                                                  t.added, size_gb) if c["key"] in ("recent",)]
                if t.play_count and _months(m.now, t.last_played) is not None and _months(m.now, t.last_played) < 6:
                    comps.append(_comp("staleness", L("Recently watched", "Sett nylig"), -5,
                                       L("In use – but the quality can still be lowered",
                                         "Brukes – men kvaliteten kan likevel senkes"), w))
                out.append(Suggestion("replace", t, "replace", "replace",
                                      L("Replace with a smaller version", "Erstatt med mindre versjon"),
                                      t.folder, name=t.name, claims=claims, components=comps,
                                      consequences=_consequences(t, "replace"), risk="medium",
                                      history=_history(m, t.play_count, t.last_played, t.users, t.recent_users),
                                      savings_note=[fmt("Estimate: down to about {s} per file", "Anslag: ned til ca. {s} per fil",
                                                        s=gb(target, 0))]))

    # --- duplicates
    titles = m.titles
    for g in dups:
        if g.kind == "hardlink" or g.keep is None:
            continue
        t = titles.get(g.keep.title_key) if g.keep.title_key else None
        removable = [f for f in g.files if f.ino != g.keep.ino and not _is_protected(f, m)]
        if not removable:
            continue
        claims = {f.path: f.alloc for f in removable}
        # Every path to the inodes must be included for the space to be freed
        for f in removable:
            for p in m.inode_paths.get(f.ino, []):
                claims.setdefault(p, f.alloc)
        if sum(claims.values()) < 100 * 1024 ** 2:
            continue
        kind = "remove_copy" if g.kind == "identical" else "remove_versions"
        comps = [_space_comp(sum(f.alloc for f in removable), w),
                 _comp("versions", L("Exists in another version", "Finnes i annen versjon"), 25,
                       fmt("Keeps: {n} ({why})", "Beholder: {n} ({why})", n=_name(g.keep.path), why=g.reason_keep), w)]
        risk = "low" if g.kind == "identical" or g.keep.managed else "medium"
        what = L("movie", "film") if (t and t.kind == "movie") else L("episode", "episode")
        reasons = [L("Partial hash (start/middle/end) and size are equal", "Delvis hash (start/midt/slutt) og størrelse er like")] \
            if g.kind == "identical" else \
            [fmt("{n} different files for the same {w}", "{n} ulike filer for samme {w}", n=len(g.files), w=what)]
        name = _name(g.keep.path) if g.kind == "identical" else (t.name if t else _name(g.keep.path))
        if g.kind == "versions" and t and t.kind != "movie":
            ep = next((f for f in g.files if f.season is not None), None)
            if ep:
                name = f"{t.name} S{ep.season:02d}E{ep.episode:02d}"
        out.append(Suggestion(kind, t, g.id, "remove",
                              L("Remove identical copy", "Fjern identisk kopi") if kind == "remove_copy"
                              else L("Keep one version", "Behold én versjon"),
                              g.keep.path.rsplit("/", 1)[0], name=name, claims=claims,
                              components=comps, reasons=reasons,
                              consequences=_consequences(t, kind) if t else _consequences(None, "download"),
                              risk=risk, history=_history(m, t.play_count, t.last_played, t.users, t.recent_users) if t else {}))

    # --- old downloads (downloads library), grouped per top-level folder
    by_top = defaultdict(list)
    for f in m.downloads:
        lib = m.libs[f.library]
        rel = f.path[len(lib["host_path"].rstrip("/")) + 1:]
        by_top[(f.library, rel.split("/", 1)[0])].append(f)
    identical_paths = {f.path for g in dups if g.kind == "identical" for f in g.files}
    for (libname, top), fs in by_top.items():
        fs = [f for f in fs if f.path not in identical_paths]
        size = sum(f.alloc for f in {f.ino: f for f in fs}.values())
        newest = max((f.mtime for f in fs), default=m.now)
        age = (m.now - newest) / MONTH
        if size < min_b or age < 1:
            continue
        comps = [_space_comp(size, w),
                 _comp("staleness", L("Age", "Alder"), min(20, age * 2),
                       fmt("Last changed {a:.0f} months ago", "Sist endret for {a:.0f} måneder siden", a=age), w),
                 _comp("monitored", L("Outside the library", "Utenfor biblioteket"), 0,
                       L("Not imported to a library (no identical copy found)",
                         "Ikke importert til et bibliotek (ingen identisk kopi funnet)"), w)]
        lib = m.libs[libname]
        out.append(Suggestion("download", None, f"download:{top}", "delete", L("Clean up download", "Rydd nedlasting"),
                              lib["host_path"].rstrip("/") + "/" + top, name=top, claims={f.path: f.alloc for f in fs},
                              components=comps, consequences=_consequences(None, "download"), risk="medium",
                              reasons=[L("In the downloads folder", "Ligger i nedlastingsmappen")]))
    return out


def _is_protected(f: FileRec, m: Model) -> bool:
    """Only for duplicate suggestions: protection counts only if it is switched on for duplicates."""
    if not settings.get()["protection"].get("include_duplicates", False):
        return False
    if m.libs.get(f.library, {}).get("protected"):
        return True
    t = m.titles.get(f.title_key) if f.title_key else None
    return bool(t and t.protected)


# ---------------------------------------------------------------- run

def run(progress) -> dict:
    s = settings.get()
    now = time.time()
    with db.conn() as c:
        progress(0.1, L("Linking files to titles", "Kobler filer til titler"))
        m = build(c, s, now)
        progress(0.4, L("Looking for duplicates and versions", "Leter etter duplikater og versjoner"))
        dups = find_duplicates(m)
        progress(0.6, L("Making suggestions", "Lager forslag"))
        sugg = make_suggestions(m, s, dups)
        file_info = {f.path: {"dev": f.dev, "inode": f.inode, "nlink": f.nlink} for f in m.files}

        progress(0.8, L("Saving results", "Lagrer resultater"))
        c.execute("BEGIN")
        for tbl in ("titles", "file_title", "suggestions", "suggestion_files", "duplicate_groups"):
            c.execute(f"DELETE FROM {tbl}")
        c.executemany("INSERT INTO titles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (t.key, t.kind, t.name, t.year, t.library, t.folder, t.radarr_id, t.sonarr_id,
             json.dumps(sorted(k for _, k in t.plex_keys)), None if t.monitored is None else int(t.monitored),
             t.added, json.dumps(t.tags + t.labels), int(t.protected), store(t.protect_reason) if t.protect_reason else None,
             t.size, t.alloc, len(t.files), len(t.videos), t.play_count, t.last_played, json.dumps(sorted(t.users)),
             len(t.users), len(t.recent_users), t.requested_by, t.requested_at, res_label(t.best_resolution),
             json.dumps({str(k): {"plays": v["plays"], "last": v["last"], "users": len(v["users"])}
                         for k, v in t.season_stats.items()}),
             json.dumps(t.requests, ensure_ascii=False))
            for t in m.titles.values()])
        c.executemany("INSERT INTO file_title VALUES(?,?,?,?)",
                      [(f.path, f.title_key, f.season, f.episode) for f in m.files if f.title_key])
        rows, frows = [], []
        for sg in sugg:
            freed, held = freed_bytes(sg.claims, file_info, m.inode_paths)
            notes = list(sg.savings_note)
            if held:
                notes.append(fmt("{s} is held by hardlinks outside the suggestion", "{s} holdes av hardlinker utenfor forslaget",
                                 s=gb(held)))
            claimed = sum(sg.claims.values())
            if held and claimed and freed < claimed:
                # The space points should reflect what is actually freed, not the file size
                for i, c_ in enumerate(sg.components):
                    if c_.get("tag") == "space":
                        sc = _space_comp(freed, s["weights"])
                        sc["detail"] = join([sc["detail"], fmt("{s} held by hardlinks", "{s} holdes av hardlinker", s=gb(held))],
                                            sep=" – ")
                        sg.components[i] = sc
                        break
            score = max(0.0, min(100.0, sum(c_["points"] for c_ in sg.components)))
            uniq = {}
            for p in sg.claims:
                f = _lookup(m, p)
                if f:
                    uniq[f.ino] = f.alloc
            size = sum(uniq.values())
            rows.append((sg.id, sg.kind, sg.title.key if sg.title else None, sg.scope, sg.action, store(sg.label),
                         sg.location, round(score, 1), sg.risk, size, freed, store(join(notes)) if notes else "",
                         json.dumps(sg.reasons, ensure_ascii=False), json.dumps(sg.consequences, ensure_ascii=False),
                         json.dumps(sg.components, ensure_ascii=False), json.dumps(sg.history), int(now), sg.name))
            frows += [(sg.id, p, cl) for p, cl in sg.claims.items()]
        c.executemany("INSERT OR REPLACE INTO suggestions(id,kind,title_key,scope,action,label,location,score,risk,size,"
                      "savings,savings_note,reasons,consequences,components,history,created,name) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT OR REPLACE INTO suggestion_files VALUES(?,?,?)", frows)
        c.executemany("INSERT INTO duplicate_groups VALUES(?,?,?,?,?,?,?)", [
            (g.id, g.kind, g.title_key, store(g.label), sum(f.size for f in g.files),
             0 if g.kind == "hardlink" else sum(f.alloc for f in g.files if g.keep and f.ino != g.keep.ino),
             json.dumps([{"path": f.path, "size": f.size, "resolution": res_label(f.resolution), "managed": f.managed,
                          "keep": bool(g.keep and f.ino == g.keep.ino), "nlink": f.nlink} for f in g.files]
                        + ([{"keep_reason": g.reason_keep}] if g.reason_keep else []), ensure_ascii=False))
            for g in dups])
        db.kv_set(c, "last_analysis", {"time": now, "titles": len(m.titles), "suggestions": len(sugg),
                                       "duplicates": len(dups), "history_start": m.history_start})
        c.execute("COMMIT")
    progress(1.0, fmt("Analysis done: {n} suggestions", "Analyse ferdig: {n} forslag", n=len(sugg)))
    return {"titles": len(m.titles), "suggestions": len(sugg), "duplicates": len(dups)}


_path_cache: dict = {}


def _lookup(m: Model, path: str):
    if _path_cache.get("_id") is not m:
        _path_cache.clear()
        _path_cache["_id"] = m
        _path_cache.update({f.path: f for f in m.files})
    return _path_cache.get(path)


def selection_savings(c, ids: list[str]) -> dict:
    """Total for the selected suggestions – each inode counted once, hardlinks taken into account."""
    if not ids:
        return {"freed": 0, "held": 0, "count": 0, "files": 0, "naive_sum": 0, "by_library": {}}
    claims: dict[str, int] = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        ph = ",".join("?" * len(chunk))
        for p, cl in c.execute(f"SELECT path, claim FROM suggestion_files WHERE suggestion_id IN ({ph})", chunk):
            claims[p] = max(claims.get(p, 0), cl)
    if not claims:
        return {"freed": 0, "held": 0, "count": len(ids), "files": 0, "naive_sum": 0, "by_library": {}}
    file_info, inode_paths, libs = {}, defaultdict(list), {}
    paths = list(claims)
    for i in range(0, len(paths), 900):
        chunk = paths[i:i + 900]
        q = ",".join("?" * len(chunk))
        for r in c.execute(f"SELECT path, dev, inode, nlink, library FROM files WHERE path IN ({q})", chunk):
            file_info[r[0]] = {"dev": r[1], "inode": r[2], "nlink": r[3]}
            libs[r[0]] = r[4]
    for p, v in file_info.items():
        if v["nlink"] <= 1:
            inode_paths[(v["dev"], v["inode"])].append(p)  # only path – no lookup needed
    linked = {(v["dev"], v["inode"]) for v in file_info.values() if v["nlink"] > 1}
    for dev, ino in linked:
        for (p,) in c.execute("SELECT path FROM files WHERE dev=? AND inode=?", (dev, ino)):
            inode_paths[(dev, ino)].append(p)
    per_path: dict = {}
    freed, held = freed_bytes(claims, file_info, inode_paths, per_path)
    by_library: dict[str, int] = defaultdict(int)
    for p, b in per_path.items():
        by_library[libs.get(p, "?")] += b
    naive = 0
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        ph = ",".join("?" * len(chunk))
        naive += sum(r[0] or 0 for r in c.execute(f"SELECT savings FROM suggestions WHERE id IN ({ph})", chunk))
    return {"freed": freed, "held": held, "count": len(ids), "files": len(claims), "naive_sum": naive,
            "by_library": dict(by_library)}
