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
            items.append({"ratingKey": rk, "title": title, "year": year, "addedAt": int(added), "Media": media})
    elif key == "3" and typ == 1:
        items.append({"ratingKey": KIDS[2], "title": "Kids Movie", "year": 2018, "addedAt": int(NOW - 900 * DAY),
                      "Media": _media(KIDS[0], KIDS[1], "1080")})
    elif key == "2" and typ == 2:
        items = [{"ratingKey": rk, "title": t, "year": y, "addedAt": int(a)} for _, t, y, _, _, a, _, rk in SERIES]
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
