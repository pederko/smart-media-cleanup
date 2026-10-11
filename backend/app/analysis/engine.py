"""Duplikater, forslag, forklarbar score og plassbesparelse uten dobbelttelling."""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .. import db, settings
from .linking import MONTH, FileRec, Model, Title, build, res_label

GB = 1024 ** 3


def _gb(b: float, dec: int = 1) -> str:
    """Norsk tallformat: 1 234,5"""
    return f"{b / GB:,.{dec}f}".replace(",", " ").replace(".", ",")


# ---------------------------------------------------------------- gevinst

def freed_bytes(claims: dict[str, int], file_info: dict[str, dict], inode_paths: dict,
                per_path: dict | None = None) -> tuple[int, int]:
    """claims: sti -> byte som forslaget hevder frigjøres for den filen.

    Regler:
      * Én inode telles én gang (maks krav på tvers av forslag).
      * En inode frigjøres bare hvis ALLE kjente stier til den er med, og ingen ukjente
        hardlinker finnes (nlink == antall kjente stier). Ellers 0.
    Returnerer (frigjort, holdt_igjen_av_hardlinker).
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


# ---------------------------------------------------------------- duplikater

@dataclass
class DupGroup:
    kind: str           # hardlink | identical | versions
    title_key: str | None
    label: str
    files: list[FileRec]
    keep: FileRec | None
    reason_keep: str = ""

    @property
    def id(self) -> str:
        return hashlib.sha1((self.kind + "|" + "|".join(sorted(f.path for f in self.files))).encode()).hexdigest()[:16]


def _keep_choice(files: list[FileRec], libs: dict) -> tuple[FileRec, str]:
    def rank(f: FileRec):
        lib = libs.get(f.library, {})
        return (lib.get("kind") != "downloads", f.managed, f.resolution, f.size)
    best = max(files, key=rank)
    if best.managed:
        why = "administreres av Radarr/Sonarr"
    elif libs.get(best.library, {}).get("kind") != "downloads":
        why = f"ligger i biblioteket {best.library}"
    else:
        why = "høyest kvalitet"
    if best.resolution and not best.managed:
        why += f", {res_label(best.resolution) or ''}".rstrip(", ")
    return best, why


def find_duplicates(m: Model) -> list[DupGroup]:
    groups: list[DupGroup] = []
    all_files = [f for t in m.titles.values() for f in t.files] + m.downloads
    # 1) Hardlinker: samme inode, flere stier. Ikke duplikat, ingen gevinst.
    by_ino = defaultdict(list)
    for f in all_files:
        by_ino[f.ino].append(f)
    for ino, fs in by_ino.items():
        if len(fs) > 1:
            groups.append(DupGroup("hardlink", fs[0].title_key, f"Hardlenket: {fs[0].path.rsplit('/', 1)[-1]}",
                                   fs, None, "samme fil på disk"))
    # 2) Identisk innhold: samme størrelse + delvis hash, ulik inode
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
            groups.append(DupGroup("identical", keep.title_key, f"Identiske kopier: {keep.path.rsplit('/', 1)[-1]}",
                                   fs, keep, why))
    # 3) Alternative versjoner av samme film/episode (ulikt innhold)
    for t in m.titles.values():
        buckets = defaultdict(dict)
        for f in t.videos:
            if t.kind == "movie":
                buckets["film"].setdefault(f.ino, f)
            elif f.season is not None and f.episode is not None:
                buckets[(f.season, f.episode)].setdefault(f.ino, f)
        for b, inos in buckets.items():
            fs = list(inos.values())
            if len(fs) < 2:
                continue
            # Hvis alle er identiske kopier, er det allerede dekket over
            if all(f.ino in identical_inos for f in fs) and len({(f.size, f.phash) for f in fs}) == 1:
                continue
            keep, why = _keep_choice(fs, m.libs)
            where = t.name if b == "film" else f"{t.name} S{b[0]:02d}E{b[1]:02d}"
            groups.append(DupGroup("versions", t.key, f"Flere versjoner: {where}", fs, keep, why))
    return groups


# ---------------------------------------------------------------- forslag

@dataclass
class Suggestion:
    kind: str           # delete_title | delete_season | replace | remove_versions | remove_copy | download
    title: Title | None
    scope: str
    action: str
    label: str
    location: str
    claims: dict = field(default_factory=dict)  # sti -> byte
    components: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    consequences: list = field(default_factory=list)
    risk: str = "middels"
    history: dict = field(default_factory=dict)
    savings_note: str = ""

    @property
    def id(self) -> str:
        base = f"{self.kind}|{self.title.key if self.title else ''}|{self.scope}|{self.location}"
        return hashlib.sha1(base.encode()).hexdigest()[:16]


def _months(now: float, ts: int | None) -> float | None:
    return None if not ts else (now - ts) / MONTH


def _fmt_date(ts: int | None) -> str:
    return time.strftime("%d.%m.%Y", time.localtime(ts)) if ts else "ukjent"


def _comp(key, label, points, detail, w):
    return {"key": key, "label": label, "points": round(points * w.get(key, 1.0), 1), "detail": detail}


def _space_comp(claim_bytes: int, w: dict) -> dict:
    gb = claim_bytes / GB
    pts = min(35.0, 12 * math.log2(1 + gb / 10))
    return _comp("space", "Plass", pts, f"{_gb(claim_bytes)} GB kan frigjøres", w)


def _usage_comps(m: Model, s: dict, w: dict, plays: int, last: int | None, users: set, recent_users: set,
                 added: int | None, size_gb: float) -> list[dict]:
    a = s["analysis"]
    stale = sorted(a["stale_months"])
    out = []
    hs = m.history_start
    if plays == 0:
        if hs and added and added < hs:
            out.append(_comp("staleness", "Aldri sett", 30, f"Ingen avspillinger siden historikken startet {_fmt_date(hs)}", w))
        elif hs:
            out.append(_comp("staleness", "Aldri sett", 22, f"Ingen avspillinger siden den ble lagt til {_fmt_date(added)}", w))
        else:
            out.append(_comp("staleness", "Ingen historikk", 0, "Tautulli-historikk mangler – kan ikke vurdere seing", w))
    else:
        mo = _months(m.now, last) or 0
        if mo >= stale[2]:
            pts, txt = 25, f"Ikke sett på {mo:.0f} måneder (≥ {stale[2]})"
        elif mo >= stale[1]:
            pts, txt = 18, f"Ikke sett på {mo:.0f} måneder (≥ {stale[1]})"
        elif mo >= stale[0]:
            pts, txt = 10, f"Ikke sett på {mo:.0f} måneder (≥ {stale[0]})"
        elif mo < 3:
            pts, txt = -20, f"Sett for {max(mo, 0):.0f} måneder siden"
        else:
            pts, txt = 0, f"Sist sett {_fmt_date(last)}"
        out.append(_comp("staleness", "Sist sett", pts, txt, w))
        if plays <= 2 and size_gb >= 20:
            out.append(_comp("consumption", "Lavt konsum", 8, f"Bare {plays} avspilling(er) for {_gb(size_gb * GB, 0)} GB", w))
        elif plays >= 10:
            out.append(_comp("consumption", "Mye brukt", -10, f"{plays} avspillinger totalt", w))
    if recent_users:
        n = len(recent_users)
        out.append(_comp("viewers", "Seere", -min(30, 6 * n),
                         f"{n} bruker(e) har sett siste {a['recent_play_months']} mnd", w))
    elif len(users) >= 3:
        out.append(_comp("viewers", "Seere", -5, f"{len(users)} ulike brukere har sett tidligere", w))
    mo_added = _months(m.now, added)
    if mo_added is not None and mo_added < a["quarantine_months"]:
        out.append(_comp("recent", "Nylig lagt til", -40,
                         f"Lagt til {_fmt_date(added)} (karantene {a['quarantine_months']} mnd)", w))
    return out


def _arr_comp(t: Title, w: dict, season: int | None = None) -> dict | None:
    if t.radarr_id is not None:
        return (_comp("monitored", "Radarr", -8, "Overvåket i Radarr", w) if t.monitored
                else _comp("monitored", "Radarr", 5, "Ikke overvåket i Radarr", w))
    if t.sonarr_id is not None:
        mon = t.monitored if season is None else (t.monitored and t.seasons_monitored.get(season, False))
        what = "Serien" if season is None else f"Sesong {season}"
        return (_comp("monitored", "Sonarr", -8, f"{what} er overvåket i Sonarr", w) if mon
                else _comp("monitored", "Sonarr", 5, f"{what} er ikke overvåket i Sonarr", w))
    return None


def _request_comp(m: Model, t: Title, w: dict) -> dict | None:
    if not t.requests:
        return None
    if t.requested_at and _months(m.now, t.requested_at) < 12:
        return _comp("request", "Etterspurt nylig", -15, f"Etterspurt av {t.requested_by} {_fmt_date(t.requested_at)}", w)
    who = sorted({r["by"] for r in t.requests})
    unwatched = sorted({r["by"] for r in t.requests if not r["watched"]})
    if unwatched and len(unwatched) == len(who):
        return _comp("request", "Etterspurt, ikke sett", 8,
                     f"Etterspurt av {', '.join(who)} ({_fmt_date(t.requested_at)}), men ingen av dem har sett den", w)
    return _comp("request", "Etterspurt", 0, f"Etterspurt av {', '.join(who)}, som har sett den", w)


def _consequences(t: Title | None, kind: str, season: int | None = None) -> list[str]:
    out = []
    if t is None:
        return ["Filen ligger i nedlastingsmappen. Er den en aktiv torrent, fjern den via qBittorrent – ellers feiler seedingen."]
    if kind == "remove_copy":
        return ["Innholdet finnes fortsatt i en identisk kopi. Plex/Radarr/Sonarr påvirkes ikke hvis kopien som "
                "beholdes er den de peker på."]
    if t.radarr_id is not None:
        if kind == "delete_title":
            out.append("Slett via Radarr («Delete» med «Delete files» og importekskludering) – slettes filene "
                       "direkte, vil Radarr " + ("laste filmen ned igjen fordi den er overvåket." if t.monitored
                                                 else "vise den som manglende."))
        elif kind == "replace":
            out.append("Endre kvalitetsprofil i Radarr til 1080p og søk på nytt – Radarr erstatter filen selv.")
        elif kind == "remove_versions":
            out.append("Ekstra versjoner er ikke administrert av Radarr; Radarr påvirkes ikke.")
    elif t.sonarr_id is not None:
        if kind == "delete_title":
            out.append("Slett serien i Sonarr med «Delete files» – ellers lastes overvåkede episoder ned igjen.")
        elif kind == "delete_season":
            mon = t.monitored and t.seasons_monitored.get(season, False)
            out.append(f"Avovervåk sesong {season} i Sonarr før sletting" + (" (den er overvåket nå)." if mon else "."))
        elif kind == "replace":
            out.append("Endre kvalitetsprofil i Sonarr og søk etter sesongen på nytt.")
        elif kind == "remove_versions":
            out.append("Sonarr peker på én av filene; de andre er uadministrerte.")
    else:
        out.append("Ikke administrert av Radarr/Sonarr – slettes kun i filsystemet.")
    if t.plex_keys:
        out.append("Plex fjerner tittelen ved neste bibliotekskanning (krever «Empty trash»). "
                   "Seerhistorikken i Tautulli beholdes.")
    return out


def _risk_delete(m: Model, s: dict, t: Title, plays: int, last: int | None, recent_users: set) -> str:
    a = s["analysis"]
    recent = last and _months(m.now, last) < a["recent_play_months"]
    new = t.added and _months(m.now, t.added) < a["quarantine_months"]
    req = t.requested_at and _months(m.now, t.requested_at) < 12
    if recent or len(recent_users) >= 2 or new or req:
        return "høy"
    if t.monitored or plays > 0:
        return "middels"
    return "lav"


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

        # --- slett hele tittelen
        if size >= min_b:
            comps = [_space_comp(size, w)] + _usage_comps(m, s, w, t.play_count, t.last_played, t.users,
                                                         t.recent_users, t.added, size_gb)
            comps += [c for c in (arr, req) if c]
            label = "Slett filmen" if t.kind == "movie" else "Slett hele serien"
            sg = Suggestion("delete_title", t, "title", label, t.name, t.folder,
                            claims={f.path: f.alloc for f in t.files}, components=comps,
                            consequences=_consequences(t, "delete_title"),
                            risk=_risk_delete(m, s, t, t.play_count, t.last_played, t.recent_users),
                            history=_history(m, t.play_count, t.last_played, t.users, t.recent_users))
            out.append(sg)

        # --- slett enkeltsesonger som ingen ser, når andre sesonger er sett
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
                    comps.append(_comp("consumption", "Resten av serien sees", 0,
                                       f"Serien er sett {t.play_count} ganger totalt, sist {_fmt_date(t.last_played)}", w))
                    sc = _arr_comp(t, w, sn)
                    if sc:
                        comps.append(sc)
                    if req and req["points"] < 0:
                        comps.append(req)
                    risk = "middels" if (ss["plays"] or (t.monitored and t.seasons_monitored.get(sn))) else "lav"
                    out.append(Suggestion("delete_season", t, f"season:{sn}", f"Slett sesong {sn}",
                                          f"{t.name} – sesong {sn}", t.folder,
                                          claims={f.path: f.alloc for f in fs}, components=comps,
                                          consequences=_consequences(t, "delete_season", sn), risk=risk,
                                          history=_history(m, ss["plays"], ss["last"], ss["users"], ss["recent_users"])))

        # --- erstatt store filer med mindre versjon
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
                res = res_label(max(f.resolution for f in big)) or "ukjent oppløsning"
                isos = sum(1 for f in big if f.ext in (".iso", ".img"))
                detail = f"{len(big)} fil(er) over grensen ({res})" + (f", {isos} ISO" if isos else "")
                comps = [_space_comp(claim_sum, w),
                         _comp("versions", "Beholder tittelen", 10, "Tittelen beholdes i lavere kvalitet", w),
                         _comp("space", "Stor fil", 0, detail, w)]
                comps += [c for c in _usage_comps(m, s, w, t.play_count, t.last_played, t.users, t.recent_users,
                                                  t.added, size_gb) if c["key"] in ("recent",)]
                if t.play_count and _months(m.now, t.last_played) is not None and _months(m.now, t.last_played) < 6:
                    comps.append(_comp("staleness", "Sett nylig", -5, "Brukes – men kvaliteten kan likevel senkes", w))
                out.append(Suggestion("replace", t, "replace", "Erstatt med mindre versjon",
                                      t.name, t.folder, claims=claims, components=comps,
                                      consequences=_consequences(t, "replace"), risk="middels",
                                      history=_history(m, t.play_count, t.last_played, t.users, t.recent_users),
                                      savings_note=f"Anslag: ned til ca. {_gb(target, 0)} GB per fil"))

    # --- duplikater
    titles = m.titles
    for g in dups:
        if g.kind == "hardlink" or g.keep is None:
            continue
        t = titles.get(g.keep.title_key) if g.keep.title_key else None
        removable = [f for f in g.files if f.ino != g.keep.ino and not _is_protected(f, m)]
        if not removable:
            continue
        claims = {f.path: f.alloc for f in removable}
        # Alle stier til inodene må med for at plassen frigjøres
        for f in removable:
            for p in m.inode_paths.get(f.ino, []):
                claims.setdefault(p, f.alloc)
        if sum(claims.values()) < 100 * 1024 ** 2:
            continue
        kind = "remove_copy" if g.kind == "identical" else "remove_versions"
        comps = [_space_comp(sum(f.alloc for f in removable), w),
                 _comp("versions", "Finnes i annen versjon", 25, f"Beholder: {g.keep.path.rsplit('/', 1)[-1]} ({g.reason_keep})", w)]
        risk = "lav" if g.kind == "identical" or g.keep.managed else "middels"
        reasons = ["Delvis hash (start/midt/slutt) og størrelse er like"] if g.kind == "identical" else \
                  [f"{len(g.files)} ulike filer for samme {'film' if (t and t.kind == 'movie') else 'episode'}"]
        out.append(Suggestion(kind, t, g.id, "Fjern identisk kopi" if kind == "remove_copy" else "Behold én versjon",
                              g.label.split(": ", 1)[-1], g.keep.path.rsplit("/", 1)[0], claims=claims,
                              components=comps, reasons=reasons,
                              consequences=_consequences(t, kind) if t else _consequences(None, "download"),
                              risk=risk, history=_history(m, t.play_count, t.last_played, t.users, t.recent_users) if t else {}))

    # --- gamle nedlastinger (nedlastingsmappen), gruppert per toppmappe
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
        comps = [_space_comp(size, w), _comp("staleness", "Alder", min(20, age * 2),
                                             f"Sist endret for {age:.0f} måneder siden", w),
                 _comp("monitored", "Utenfor biblioteket", 0, "Ikke importert til FILM/TV (ingen identisk kopi funnet)", w)]
        lib = m.libs[libname]
        out.append(Suggestion("download", None, f"download:{top}", "Rydd nedlasting", top,
                              lib["host_path"].rstrip("/") + "/" + top, claims={f.path: f.alloc for f in fs},
                              components=comps, consequences=_consequences(None, "download"), risk="middels",
                              reasons=["Ligger i nedlastingsmappen"]))
    return out


def _is_protected(f: FileRec, m: Model) -> bool:
    if m.libs.get(f.library, {}).get("protected"):
        return True
    t = m.titles.get(f.title_key) if f.title_key else None
    return bool(t and t.protected)


# ---------------------------------------------------------------- kjøring

def run(progress) -> dict:
    s = settings.get()
    now = time.time()
    with db.conn() as c:
        progress(0.1, "Kobler filer til titler")
        m = build(c, s, now)
        progress(0.4, "Leter etter duplikater og versjoner")
        dups = find_duplicates(m)
        progress(0.6, "Lager forslag")
        sugg = make_suggestions(m, s, dups)
        file_info = {f.path: {"dev": f.dev, "inode": f.inode, "nlink": f.nlink} for f in m.files}
        tn = db.kv_get(c, "truenas") or {}
        snaps = tn.get("root_snapshots")
        snap_note = (f"Holdes av {snaps} snapshot(s) på {tn.get('root_dataset')} til de utløper"
                     if snaps else "")

        progress(0.8, "Lagrer resultater")
        c.execute("BEGIN")
        for tbl in ("titles", "file_title", "suggestions", "suggestion_files", "duplicate_groups"):
            c.execute(f"DELETE FROM {tbl}")
        c.executemany("INSERT INTO titles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (t.key, t.kind, t.name, t.year, t.library, t.folder, t.radarr_id, t.sonarr_id,
             json.dumps(sorted(k for _, k in t.plex_keys)), None if t.monitored is None else int(t.monitored),
             t.added, json.dumps(t.tags + t.labels), int(t.protected), t.protect_reason, t.size, t.alloc,
             len(t.files), len(t.videos), t.play_count, t.last_played, json.dumps(sorted(t.users)), len(t.users),
             len(t.recent_users), t.requested_by, t.requested_at, res_label(t.best_resolution),
             json.dumps({str(k): {"plays": v["plays"], "last": v["last"], "users": len(v["users"])}
                         for k, v in t.season_stats.items()}),
             json.dumps(t.requests, ensure_ascii=False))
            for t in m.titles.values()])
        c.executemany("INSERT INTO file_title VALUES(?,?,?,?)",
                      [(f.path, f.title_key, f.season, f.episode) for f in m.files if f.title_key])
        rows, frows = [], []
        for sg in sugg:
            freed, held = freed_bytes(sg.claims, file_info, m.inode_paths)
            note = sg.savings_note
            if held:
                note = (note + "; " if note else "") + f"{_gb(held)} GB holdes av hardlinker utenfor forslaget"
            if snap_note:
                note = (note + "; " if note else "") + snap_note
            claimed = sum(sg.claims.values())
            if held and claimed and freed < claimed:
                # Plass-poengene skal gjenspeile det som faktisk frigjøres, ikke filstørrelsen
                for i, c_ in enumerate(sg.components):
                    if c_["key"] == "space" and c_["label"] == "Plass":
                        sc = _space_comp(freed, s["weights"])
                        sc["detail"] += f" ({_gb(held)} GB holdes av hardlinker)"
                        sg.components[i] = sc
                        break
            score = max(0.0, min(100.0, sum(c_["points"] for c_ in sg.components)))
            uniq = {}
            for p in sg.claims:
                f = _lookup(m, p)
                if f:
                    uniq[f.ino] = f.alloc
            size = sum(uniq.values())
            rows.append((sg.id, sg.kind, sg.title.key if sg.title else None, sg.scope, sg.action, sg.label,
                         sg.location, round(score, 1), sg.risk, size, freed, note,
                         json.dumps(sg.reasons, ensure_ascii=False), json.dumps(sg.consequences, ensure_ascii=False),
                         json.dumps(sg.components, ensure_ascii=False), json.dumps(sg.history), int(now)))
            frows += [(sg.id, p, cl) for p, cl in sg.claims.items()]
        c.executemany("INSERT OR REPLACE INTO suggestions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.executemany("INSERT OR REPLACE INTO suggestion_files VALUES(?,?,?)", frows)
        c.executemany("INSERT INTO duplicate_groups VALUES(?,?,?,?,?,?,?)", [
            (g.id, g.kind, g.title_key, g.label, sum(f.size for f in g.files),
             0 if g.kind == "hardlink" else sum(f.alloc for f in g.files if g.keep and f.ino != g.keep.ino),
             json.dumps([{"path": f.path, "size": f.size, "resolution": res_label(f.resolution), "managed": f.managed,
                          "keep": bool(g.keep and f.ino == g.keep.ino), "nlink": f.nlink} for f in g.files]
                        + ([{"keep_reason": g.reason_keep}] if g.reason_keep else []), ensure_ascii=False))
            for g in dups])
        db.kv_set(c, "last_analysis", {"time": now, "titles": len(m.titles), "suggestions": len(sugg),
                                       "duplicates": len(dups), "history_start": m.history_start})
        c.execute("COMMIT")
    progress(1.0, f"Analyse ferdig: {len(sugg)} forslag")
    return {"titles": len(m.titles), "suggestions": len(sugg), "duplicates": len(dups)}


_path_cache: dict = {}


def _lookup(m: Model, path: str):
    if _path_cache.get("_id") is not m:
        _path_cache.clear()
        _path_cache["_id"] = m
        _path_cache.update({f.path: f for f in m.files})
    return _path_cache.get(path)


def selection_savings(c, ids: list[str]) -> dict:
    """Sum for valgte forslag – hver inode telles én gang, hardlinker tas hensyn til."""
    if not ids:
        return {"freed": 0, "held": 0, "count": 0, "files": 0}
    ph = ",".join("?" * len(ids))
    claims: dict[str, int] = {}
    for p, cl in c.execute(f"SELECT path, claim FROM suggestion_files WHERE suggestion_id IN ({ph})", ids):
        claims[p] = max(claims.get(p, 0), cl)
    if not claims:
        return {"freed": 0, "held": 0, "count": len(ids), "files": 0}
    file_info, inode_paths = {}, defaultdict(list)
    paths = list(claims)
    for i in range(0, len(paths), 900):
        chunk = paths[i:i + 900]
        q = ",".join("?" * len(chunk))
        for r in c.execute(f"SELECT path, dev, inode, nlink FROM files WHERE path IN ({q})", chunk):
            file_info[r[0]] = {"dev": r[1], "inode": r[2], "nlink": r[3]}
    libs = {}
    for i in range(0, len(paths), 900):
        chunk = paths[i:i + 900]
        q = ",".join("?" * len(chunk))
        for r in c.execute(f"SELECT path, library FROM files WHERE path IN ({q})", chunk):
            libs[r[0]] = r[1]
    for p, v in file_info.items():
        if v["nlink"] <= 1:
            inode_paths[(v["dev"], v["inode"])].append(p)  # eneste sti – ingen oppslag nødvendig
    linked = {(v["dev"], v["inode"]) for v in file_info.values() if v["nlink"] > 1}
    for dev, ino in linked:
        for (p,) in c.execute("SELECT path FROM files WHERE dev=? AND inode=?", (dev, ino)):
            inode_paths[(dev, ino)].append(p)
    per_path: dict = {}
    freed, held = freed_bytes(claims, file_info, inode_paths, per_path)
    by_library: dict[str, int] = defaultdict(int)
    for p, b in per_path.items():
        by_library[libs.get(p, "?")] += b
    naive = sum(r[0] for r in c.execute(f"SELECT savings FROM suggestions WHERE id IN ({ph})", ids))
    return {"freed": freed, "held": held, "count": len(ids), "files": len(claims), "naive_sum": naive,
            "by_library": dict(by_library)}
