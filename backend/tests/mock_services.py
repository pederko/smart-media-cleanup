"""Minimale etterligninger av Radarr/Sonarr/Plex/Tautulli for ende-til-ende-test.

Feltene speiler de virkelige API-svarene som appen leser (ingen ekstra felter brukes).
"""
from __future__ import annotations

import time

from fastapi import FastAPI, Header, HTTPException, Request

GB = 1024 ** 3
NOW = time.time()
DAY = 86400


def iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.1234567Z", time.gmtime(ts))


# (radarr_id, tittel, år, mappe, filnavn (styrt av Radarr), monitored, lagt til, oppløsning, plex rk)
MOVIES = [
    (1, "Big Movie", 2010, "/FILM/Big Movie (2010)", "Big.Movie.2010.2160p.REMUX.mkv", False, NOW - 2000 * DAY, 2160, "101"),
    (2, "Popular", 2015, "/FILM/Popular (2015)", "Popular.2015.1080p.mkv", True, NOW - 1500 * DAY, 1080, "102"),
    (3, "Twin", 2012, "/FILM/Twin (2012)", "Twin.2012.1080p.mkv", True, NOW - 1500 * DAY, 1080, "103"),
    (4, "New", 2026, "/FILM/New (2026)", "New.2026.1080p.mkv", True, NOW - 30 * DAY, 1080, "104"),
    (5, "Hardlinked", 2011, "/FILM/Hardlinked (2011)", "Hardlinked.2011.mkv", False, NOW - 1500 * DAY, 1080, "105"),
    (6, "Copy", 2013, "/FILM/Copy (2013)", "Copy.2013.mkv", False, NOW - 1500 * DAY, 1080, "106"),
    (7, "Keeper", 2009, "/FILM/Keeper (2009)", "Keeper.2009.mkv", False, NOW - 1500 * DAY, 1080, "107"),
]
SIZES = {1: 80 * GB, 2: 10 * GB + 1, 3: 15 * GB + 2, 4: 30 * GB + 3, 5: 20 * GB + 4, 6: 7 * GB + 5, 7: 9 * GB + 6}
SERIES = [
    (1, "Old Show", 2005, "/TV/Old Show", True, NOW - 2500 * DAY, {1: True, 2: True}, "201"),
    (2, "Hot Show", 2024, "/TV/Hot Show", True, NOW - 400 * DAY, {1: True}, "202"),
]
EPISODES = [  # (id, series, season, ep, filename, size)
    (11, 1, 1, 1, "Season 01/Old.Show.S01E01.mkv", 3 * GB + 11),
    (12, 1, 1, 2, "Season 01/Old.Show.S01E02.mkv", 3 * GB + 12),
    (13, 1, 2, 1, "Season 02/Old.Show.S02E01.mkv", 3 * GB + 13),
    (14, 1, 2, 2, "Season 02/Old.Show.S02E02.mkv", 3 * GB + 14),
    (21, 2, 1, 1, "Season 01/Hot.Show.S01E01.mkv", 9 * GB + 21),
    (22, 2, 1, 2, "Season 01/Hot.Show.S01E02.mkv", 9 * GB + 22),
]
KIDS = ("/Barn/Kids Movie (2018)/Kids.Movie.2018.mkv", 5 * GB + 31, "301")
EXTRA_TWIN = ("/FILM/Twin (2012)/Twin.2012.2160p.mkv", 60 * GB + 7)

PLAYS = [  # (row_id, dager siden, bruker, media_type, rating_key, grandparent, season)
    (1, 10, "anna", "movie", "102", "", None),
    (2, 20, "bjorn", "movie", "102", "", None),
    (3, 40, "cecilie", "movie", "102", "", None),
    (4, 1100, "anna", "episode", "2011", "201", 1),
    (5, 1100, "anna", "episode", "2012", "201", 1),
    (6, 5, "bjorn", "episode", "2021", "202", 1),
    (7, 500, "anna", "movie", "103", "", None),
    (8, 3, "anna", "movie", "999", "", None),  # rating key som ikke finnes lenger -> navnematch
]
PLAY_TITLES = {"999": ("Keeper", 2009)}

# Seerr-forespørsler: (id, type, tmdb, tvdb, visningsnavn, plex-brukernavn, dager siden, plex ratingKey)
REQUESTS = [
    (1, "movie", 1001, None, "Bjørn B.", "bjorn", 1200, "101"),   # Big Movie – aldri sett av noen
    (2, "movie", 1002, None, "Anna", "anna", 600, "102"),          # Popular – Anna har sett den
    (3, "movie", 1003, None, "Cecilie", "cecilie", 60, "103"),     # Twin – nylig etterspurt
    (4, "movie", None, None, "Anna", "anna", 800, "301"),          # Kids Movie – bare via Plex ratingKey
    (5, "tv", None, 2001, "Bjørn B.", "bjorn", 1500, "201"),       # Old Show – Bjørn har ikke sett den
]

KEY = "testkey"
TOKEN = "testtoken"

app = FastAPI()


def _check(k):
    if k != KEY:
        raise HTTPException(401)


def _qual(res):
    return {"quality": {"name": f"Bluray-{res}p", "resolution": res}}


@app.get("/radarr/api/v3/system/status")
def r_status(x_api_key: str = Header(None)):
    _check(x_api_key)
    return {"version": "6.4.4", "appName": "Radarr"}


@app.get("/radarr/api/v3/tag")
@app.get("/sonarr/api/v3/tag")
def tags(x_api_key: str = Header(None)):
    _check(x_api_key)
    return [{"id": 1, "label": "keep"}]


@app.get("/radarr/api/v3/movie")
def r_movies(x_api_key: str = Header(None)):
    _check(x_api_key)
    out = []
    for mid, title, year, folder, fname, mon, added, res, _ in MOVIES:
        out.append({"id": mid, "title": title, "year": year, "tmdbId": 1000 + mid, "path": folder,
                    "monitored": mon, "added": iso(added), "tags": [1] if title == "Keeper" else [],
                    "hasFile": True,
                    "movieFile": {"path": f"{folder}/{fname}", "size": SIZES[mid], "dateAdded": iso(added),
                                  "quality": _qual(res), "mediaInfo": {"videoCodec": "x265"}}})
    return out


@app.get("/sonarr/api/v3/series")
def s_series(x_api_key: str = Header(None)):
    _check(x_api_key)
    return [{"id": sid, "title": t, "year": y, "tvdbId": 2000 + sid, "path": p, "monitored": mon,
             "added": iso(a), "tags": [], "status": "ended",
             "seasons": [{"seasonNumber": n, "monitored": m} for n, m in seasons.items()]}
            for sid, t, y, p, mon, a, seasons, _ in SERIES]


@app.get("/sonarr/api/v3/episodefile")
def s_files(seriesId: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    folder = {s[0]: s[3] for s in SERIES}[seriesId]
    return [{"id": eid, "seriesId": sid, "seasonNumber": sn, "path": f"{folder}/{fn}", "size": size,
             "dateAdded": iso(NOW - 900 * DAY), "quality": _qual(1080), "mediaInfo": {"videoCodec": "h264"}}
            for eid, sid, sn, ep, fn, size in EPISODES if sid == seriesId]


def _plex_auth(token):
    if token != TOKEN:
        raise HTTPException(401)


@app.get("/plex/identity")
def p_identity(x_plex_token: str = Header(None)):
    return {"MediaContainer": {"version": "1.43.4"}}


@app.get("/plex/library/sections")
def p_sections(x_plex_token: str = Header(None)):
    _plex_auth(x_plex_token)
    return {"MediaContainer": {"Directory": [
        {"key": "1", "title": "Filmer", "type": "movie", "Location": [{"path": "/FILM"}]},
        {"key": "2", "title": "Serier", "type": "show", "Location": [{"path": "/TV"}]},
        {"key": "3", "title": "Barn", "type": "movie", "Location": [{"path": "/Barn"}]},
    ]}}


def _media(path, size, res):
    return [{"id": abs(hash(path)) % 100000, "videoResolution": res, "videoCodec": "hevc", "bitrate": 9000,
             "Part": [{"file": path, "size": size}]}]


PLEX_REFRESH: list = []


@app.get("/plex/library/sections/{key}/refresh")
def p_refresh(key: str, path: str, x_plex_token: str = Header(None)):
    _plex_auth(x_plex_token)
    PLEX_REFRESH.append((key, path))
    return {}


PLEX_DELETES: list = []


@app.delete("/plex/library/metadata/{rk}")
@app.delete("/plex/library/metadata/{rk}/media/{mid}")
def p_delete(rk: str, request: Request, mid: str | None = None, x_plex_token: str = Header(None)):
    _plex_auth(x_plex_token)
    PLEX_DELETES.append(request.url.path.replace("/plex", "", 1))
    return {}


@app.get("/plex/library/sections/{key}/label")
def p_labels(key: str, x_plex_token: str = Header(None)):
    return {"MediaContainer": {"Directory": []}}


@app.get("/plex/library/sections/{key}/all")
def p_all(key: str, request: Request, x_plex_token: str = Header(None)):
    _plex_auth(x_plex_token)
    q = request.query_params
    typ = int(q.get("type", 1))
    items = []
    if key == "1" and typ == 1:
        for mid, title, year, folder, fname, _, added, res, rk in MOVIES:
            media = _media(f"{folder}/{fname}", SIZES[mid], "4k" if res == 2160 else str(res))
            if mid == 3:
                media += _media(EXTRA_TWIN[0], EXTRA_TWIN[1], "4k")
            thumb = None if title == "Keeper" else f"/library/metadata/{rk}/thumb/1700000000"
            items.append({"ratingKey": rk, "title": title, "year": year, "addedAt": int(added), "Media": media,
                          "thumb": thumb})
        # Plex peker på en fil som ikke finnes på disk lenger
        items.append({"ratingKey": "199", "title": "Gone", "year": 1999, "addedAt": int(NOW - 3000 * DAY),
                      "Media": _media("/FILM/Gone (1999)/Gone.1999.mkv", 4 * GB, "1080")})
    elif key == "3" and typ == 1:
        items.append({"ratingKey": KIDS[2], "title": "Kids Movie", "year": 2018, "addedAt": int(NOW - 900 * DAY),
                      "Media": _media(KIDS[0], KIDS[1], "1080")})
    elif key == "2" and typ == 2:
        items = [{"ratingKey": rk, "title": t, "year": y, "addedAt": int(a), "thumb": f"/library/metadata/{rk}/thumb/1"}
                 for _, t, y, _, _, a, _, rk in SERIES]
    elif key == "2" and typ == 4:
        show = {s[0]: s for s in SERIES}
        for eid, sid, sn, ep, fn, size in EPISODES:
            s = show[sid]
            items.append({"ratingKey": f"20{sid}{eid % 10}" if False else f"{s[7]}{eid}", "title": f"Ep {ep}",
                          "grandparentRatingKey": s[7], "grandparentTitle": s[1], "parentIndex": sn, "index": ep,
                          "addedAt": int(NOW - 900 * DAY), "Media": _media(f"{s[3]}/{fn}", size, "1080")})
    start = int(q.get("X-Plex-Container-Start", 0))
    size = int(q.get("X-Plex-Container-Size", 50))
    page = items[start:start + size]
    return {"MediaContainer": {"size": len(page), "totalSize": len(items), "Metadata": page}}


@app.get("/seerr/api/v1/status")
def seerr_status(x_api_key: str = Header(None)):
    _check(x_api_key)
    return {"version": "3.5.0"}


@app.get("/seerr/api/v1/request")
def seerr_requests(take: int = 20, skip: int = 0, x_api_key: str = Header(None)):
    _check(x_api_key)
    rows = [{"id": rid, "type": typ, "status": 2, "createdAt": iso(NOW - days * DAY),
             "requestedBy": {"displayName": name, "plexUsername": pu, "username": None},
             "media": {"mediaType": typ, "tmdbId": tmdb, "tvdbId": tvdb, "ratingKey": rk}}
            for rid, typ, tmdb, tvdb, name, pu, days, rk in REQUESTS]
    return {"pageInfo": {"pages": 1, "results": len(rows)}, "results": rows[skip:skip + take]}


# Minste gyldige JPEG (1x1) + litt fyll så den passerer størrelsessjekken
JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9") + b"\x00" * 200
POSTER_HITS = {"plex": 0, "radarr": 0}


@app.get("/plex/photo/:/transcode")
def p_transcode(url: str, width: int, height: int, x_plex_token: str = Header(None)):
    from fastapi import Response
    _plex_auth(x_plex_token)
    POSTER_HITS["plex"] += 1
    return Response(JPEG, media_type="image/jpeg")


@app.get("/radarr/api/v3/mediacover/{mid}/{name}")
def r_cover(mid: int, name: str, x_api_key: str = Header(None)):
    from fastapi import Response
    _check(x_api_key)
    POSTER_HITS["radarr"] += 1
    return Response(JPEG, media_type="image/jpeg")


# ---- skrivende kall (sletting) – registreres i WRITES ----
WRITES: list = []
RELEASE_CALLS: list = []
DELETED: set = set()
PATH_OVERRIDE: dict = {}


@app.get("/radarr/api/v3/movie/{mid}")
def r_movie(mid: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    if ("movie", mid) in DELETED:
        raise HTTPException(404)
    m = next(m for m in MOVIES if m[0] == mid)
    return {"id": mid, "title": m[1], "path": PATH_OVERRIDE.get(("movie", mid), m[3]), "hasFile": True, "monitored": True,
            "qualityProfileId": 1}


@app.put("/radarr/api/v3/movie/{mid}")
async def r_movie_put(mid: int, request: Request, x_api_key: str = Header(None)):
    _check(x_api_key)
    body = await request.json()
    WRITES.append(("PUT", f"/radarr/api/v3/movie/{mid}", {}, body))
    return body


# ---- bytte: grab, kø, manuell import, kvalitetsprofiler
QUEUE: list = []          # elementer som returneres fra queue/details
MANUAL: list = []         # import-forslag fra manualimport


@app.post("/radarr/api/v3/release")
@app.post("/sonarr/api/v3/release")
async def arr_grab(request: Request, x_api_key: str = Header(None)):
    _check(x_api_key)
    body = await request.json()
    WRITES.append(("POST", request.url.path, {}, body))
    return {"guid": body["guid"]}


@app.get("/radarr/api/v3/queue/details")
@app.get("/sonarr/api/v3/queue/details")
def arr_queue(x_api_key: str = Header(None)):
    _check(x_api_key)
    return QUEUE


@app.get("/radarr/api/v3/manualimport")
@app.get("/sonarr/api/v3/manualimport")
def arr_manual(downloadId: str, x_api_key: str = Header(None)):
    _check(x_api_key)
    return MANUAL


@app.get("/radarr/api/v3/qualityprofile")
@app.get("/sonarr/api/v3/qualityprofile")
def arr_profiles(x_api_key: str = Header(None)):
    _check(x_api_key)
    return [{"id": 1, "name": "Any"}, {"id": 4, "name": "HD-1080p"}]


@app.delete("/radarr/api/v3/movie/{mid}")
def r_movie_delete(mid: int, request: Request, x_api_key: str = Header(None)):
    _check(x_api_key)
    WRITES.append(("DELETE", f"/radarr/api/v3/movie/{mid}", dict(request.query_params), None))
    DELETED.add(("movie", mid))
    return {}


@app.get("/radarr/api/v3/moviefile")
def r_moviefiles(movieId: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    m = next(m for m in MOVIES if m[0] == movieId)
    return [{"id": 300 + movieId, "movieId": movieId, "path": f"{m[3]}/{m[4]}"}]


@app.delete("/radarr/api/v3/moviefile/{fid}")
def r_moviefile_delete(fid: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    WRITES.append(("DELETE", f"/radarr/api/v3/moviefile/{fid}", {}, None))
    return {}


@app.post("/radarr/api/v3/command")
@app.post("/sonarr/api/v3/command")
async def arr_command(request: Request, x_api_key: str = Header(None)):
    _check(x_api_key)
    body = await request.json()
    WRITES.append(("POST", request.url.path, {}, body))
    return {"id": 1, **body}


@app.get("/sonarr/api/v3/episodefile/{fid:int}")
def s_episodefile(fid: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    e = next(e for e in EPISODES if e[0] == fid)
    folder = {s[0]: s[3] for s in SERIES}[e[1]]
    return {"id": fid, "seriesId": e[1], "seasonNumber": e[2], "path": f"{folder}/{e[4]}"}


@app.delete("/sonarr/api/v3/episodefile/{fid:int}")
def s_episodefile_delete(fid: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    WRITES.append(("DELETE", f"/sonarr/api/v3/episodefile/{fid}", {}, None))
    return {}


def _rel(title, size_gb, res, seeders, protocol="torrent", rejections=(), full_season=None, cf=0):
    return {"title": title, "size": int(size_gb * GB), "quality": {"quality": {"name": f"WEBDL-{res}p", "resolution": res}},
            "indexer": "TestIndexer", "protocol": protocol, "seeders": seeders, "leechers": 1, "age": 100,
            "languages": [{"name": "English"}], "rejected": bool(rejections), "rejections": list(rejections),
            "customFormatScore": cf, "fullSeason": full_season, "guid": title, "indexerId": 1}


@app.get("/radarr/api/v3/release")
def r_release(movieId: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    RELEASE_CALLS.append(movieId)
    up = ["Existing file on disk is of equal or higher preference: Remux-2160p"]
    return [
        _rel("Big.Movie.2010.2160p.REMUX", 82, 2160, 50),                      # større – filtreres bort
        _rel("Big.Movie.2010.1080p.BluRay.x264", 14, 1080, 40, rejections=up),  # anbefalt
        _rel("Big.Movie.2010.1080p.WEB.x265", 6, 1080, 0, rejections=up),       # ingen delere
        _rel("Big.Movie.2010.2160p.WEB.HEVC", 25, 2160, 12, rejections=up),
        _rel("Big.Movie.2010.720p.HDTV", 3, 720, 3, rejections=up + ["Release is banned"]),
        _rel("Big.Movie.2010.1080p.NZB", 10, 1080, None, protocol="usenet", rejections=up),
    ]


@app.get("/sonarr/api/v3/release")
def s_release(seriesId: int, seasonNumber: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    return [
        _rel("Hot.Show.S01.1080p.WEB.x265", 4, 1080, 30, full_season=True),
        _rel("Hot.Show.S01E01.1080p", 2, 1080, 30, full_season=False),
        _rel("Hot.Show.S01.2160p.REMUX", 40, 2160, 30, full_season=True),
    ]


def _series_obj(sid):
    s = next(x for x in SERIES if x[0] == sid)
    return {"id": sid, "title": s[1], "path": PATH_OVERRIDE.get(("series", sid), s[3]),
            "seasons": [{"seasonNumber": n, "monitored": m} for n, m in s[6].items()]}


@app.get("/sonarr/api/v3/series/{sid}")
def s_one(sid: int, x_api_key: str = Header(None)):
    _check(x_api_key)
    if ("series", sid) in DELETED:
        raise HTTPException(404)
    return _series_obj(sid)


@app.put("/sonarr/api/v3/series/{sid}")
async def s_put(sid: int, request: Request, x_api_key: str = Header(None)):
    _check(x_api_key)
    body = await request.json()
    WRITES.append(("PUT", f"/sonarr/api/v3/series/{sid}", {}, body))
    return body


@app.delete("/sonarr/api/v3/series/{sid}")
def s_delete(sid: int, request: Request, x_api_key: str = Header(None)):
    _check(x_api_key)
    WRITES.append(("DELETE", f"/sonarr/api/v3/series/{sid}", dict(request.query_params), None))
    DELETED.add(("series", sid))
    return {}


@app.delete("/sonarr/api/v3/episodefile/bulk")
async def s_bulk(request: Request, x_api_key: str = Header(None)):
    _check(x_api_key)
    WRITES.append(("DELETE", "/sonarr/api/v3/episodefile/bulk", {}, await request.json()))
    return {}


@app.get("/tautulli/api/v2")
def t_api(apikey: str, cmd: str, start: int = 0, length: int = 25):
    if apikey != KEY:
        return {"response": {"result": "error", "message": "Invalid apikey"}}
    if cmd == "get_tautulli_info":
        return {"response": {"result": "success", "data": {"tautulli_version": "v2.18.2"}}}
    if cmd == "get_history":
        rows = []
        for rid, days, user, mt, rk, gk, sn in PLAYS:
            title, year = PLAY_TITLES.get(rk, (None, None))
            rows.append({"row_id": rid, "date": int(NOW - days * DAY), "friendly_name": user.capitalize(),
                         "user": user, "media_type": mt,
                         "rating_key": rk, "grandparent_rating_key": gk, "parent_media_index": sn,
                         "title": title, "grandparent_title": "", "year": year, "play_duration": 3000,
                         "percent_complete": 95})
        page = rows[start:start + length]
        return {"response": {"result": "success", "data": {"recordsFiltered": len(rows), "data": page}}}
    return {"response": {"result": "error", "message": "unknown"}}
