"""End to end: mock services + sparse files on disk -> sync -> scan -> analysis -> API."""
import json
import os
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.i18n import text
from app import db, scanner, settings, sync
from app.analysis import engine
from tests import mock_services as ms

GB = 1024 ** 3


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _sparse(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(ms.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    media = tmp_path_factory.mktemp("media")
    for mid, title, year, folder, fname, *_ in ms.MOVIES:
        _sparse(media / folder.lstrip("/") / fname, ms.SIZES[mid])
    _sparse(media / ms.EXTRA_TWIN[0].lstrip("/"), ms.EXTRA_TWIN[1])
    (media / "Movies/Twin (2012)/Twin.2012.1080p.en.srt").write_text("1\n00:00:01 --> 00:00:02\nHei\n")
    show = {s[0]: s for s in ms.SERIES}
    for eid, sid, sn, ep, fn, size in ms.EPISODES:
        _sparse(media / show[sid][3].lstrip("/") / fn, size)
    _sparse(media / ms.KIDS[0].lstrip("/"), ms.KIDS[1])
    # A movie on disk that neither Radarr nor Plex knows
    _sparse(media / "Movies/Orphan (2001)/Orphan.2001.1080p.mkv", 6 * GB + 41)
    _sparse(media / "Movies/Disc (2005)/Disc.2005.iso", 30 * GB + 42)
    # Hardlink from the downloads folder to a movie
    (media / "downloads").mkdir()
    os.link(media / "Movies/Hardlinked (2011)/Hardlinked.2011.mkv", media / "downloads/Hardlinked.2011.mkv")
    # Identisk kopi (ny inode) i nedlastingsmappen
    _sparse(media / "downloads/Copy.2013.mkv", ms.SIZES[6])
    # Old download that was never imported
    _sparse(media / "downloads/Old.Download/old.mkv", 4 * GB + 99)
    old = time.time() - 200 * 86400
    os.utime(media / "downloads/Old.Download/old.mkv", (old, old))

    base = f"http://127.0.0.1:{port}"
    ms.QBIT_PORT["port"] = port
    ms.reset_arr_state()
    s = settings.get()
    s["services"]["radarr"].update(url=f"{base}/radarr", api_key=ms.KEY)
    s["services"]["sonarr"].update(url=f"{base}/sonarr", api_key=ms.KEY)
    s["services"]["plex"].update(url=f"{base}/plex", token=ms.TOKEN)
    s["services"]["tautulli"].update(url=f"{base}/tautulli", api_key=ms.KEY)
    s["services"]["seerr"].update(url=f"{base}/seerr", api_key=ms.KEY, enabled=True)
    s["services"]["qbittorrent"].update(url=f"{base}/qbit", username="admin", password="secret", enabled=True)
    s["libraries"] = [
        {"name": "Movies", "host_path": "/mnt/tank/media/Movies", "kind": "movies", "protected": False},
        {"name": "TV", "host_path": "/mnt/tank/media/TV", "kind": "series", "protected": False},
        {"name": "Kids", "host_path": "/mnt/tank/media/Kids", "kind": "mixed", "protected": True},
        {"name": "downloads", "host_path": "/mnt/tank/media/downloads", "kind": "downloads", "protected": False},
    ]
    for lib in s["libraries"]:
        lib["container_path"] = str(media / lib["name"])
    s["path_mappings"] = [{"from": f"/{n}", "to": f"/mnt/tank/media/{n}"} for n in ("Movies", "TV", "Kids")] + \
        [{"from": "/downloads", "to": "/mnt/tank/media/downloads"}]
    s["protection"]["tags"] = ["keep", "behold"]
    s["protection"]["plex_labels"] = ["keep", "behold"]
    s["scanner"]["throttle_ms_per_1000"] = 0
    s["scanner"]["hash_min_size_mb"] = 1
    settings.save(s)
    db.init()
    noop = lambda *a: None  # noqa: E731
    res_sync = sync.run(noop)
    res_scan = scanner.scan(noop, full=True)
    res_an = engine.run(noop)
    yield {"sync": res_sync, "scan": res_scan, "analysis": res_an}
    server.should_exit = True


@pytest.fixture(scope="module")
def client(env):
    from app.main import app
    with TestClient(app, headers={"X-Lang": "nb"}) as c:
        yield c


def _sugg(c, **filters):
    """Suggestions straight from the database, with texts in Norwegian (like the UI in Norwegian)."""
    from app.i18n import localize
    with db.conn() as conn:
        rows = db.rows(conn, "SELECT s.*, t.name AS tname FROM suggestions s LEFT JOIN titles t ON t.key=s.title_key")
    out = []
    for r in rows:
        r["name"] = r.pop("tname") or r["name"]
        if all(r.get(k) == v for k, v in filters.items()):
            r["components"] = json.loads(r["components"])
            out.append(localize(r, "nb"))
    return out


def test_sync_all_services_ok(env):
    for name in ("radarr", "sonarr", "plex", "tautulli", "seerr"):
        assert not env["sync"][name].startswith("error"), env["sync"]
    assert env["sync"]["truenas"] == "not configured"
    assert env["sync"]["qbittorrent"].startswith("4 torrents"), env["sync"]


def test_big_unwatched_movie_is_top_low_risk(env):
    s = _sugg(None, name="Big Movie", kind="delete_title")[0]
    assert s["savings"] == 80 * GB
    assert s["risk"] == "low"
    assert s["score"] >= 60
    labels = {c["label"] for c in s["components"]}
    assert "Aldri sett" in labels and "Plass" in labels
    rep = _sugg(None, name="Big Movie", kind="replace")[0]
    assert rep["savings"] == 80 * GB - 12 * GB


def test_popular_movie_not_recommended(env):
    s = _sugg(None, name="Popular", kind="delete_title")[0]
    assert s["score"] < 20
    assert s["risk"] == "high"


def test_new_movie_quarantined(env):
    s = _sugg(None, name="New", kind="delete_title")[0]
    assert any(c["key"] == "recent" and c["points"] == -40 for c in s["components"])
    assert s["risk"] == "high"


def test_hardlinked_movie_frees_nothing_alone(env):
    s = _sugg(None, name="Hardlinked", kind="delete_title")[0]
    assert s["savings"] == 0
    assert "hardlinker" in s["savings_note"]
    # Space points are based on what is actually freed, so the suggestion ends up low
    space = [c for c in s["components"] if c["key"] == "space" and c["label"] == "Plass"][0]
    assert space["points"] == 0
    big = _sugg(None, name="Big Movie", kind="delete_title")[0]
    assert s["score"] < big["score"] - 30


def test_identical_copy_removes_download_copy(env):
    s = _sugg(None, kind="remove_copy")
    assert len(s) == 1
    with db.conn() as c:
        paths = [r[0] for r in c.execute("SELECT path FROM suggestion_files WHERE suggestion_id=?", (s[0]["id"],))]
    assert paths == ["/mnt/tank/media/downloads/Copy.2013.mkv"]
    assert s[0]["savings"] == ms.SIZES[6]


def test_versions_keep_radarr_file(env):
    s = _sugg(None, name="Twin", kind="remove_versions")
    assert len(s) == 1
    with db.conn() as c:
        paths = [r[0] for r in c.execute("SELECT path FROM suggestion_files WHERE suggestion_id=?", (s[0]["id"],))]
    assert paths == ["/mnt/tank/media/Movies/Twin (2012)/Twin.2012.2160p.mkv"]
    assert s[0]["savings"] == ms.EXTRA_TWIN[1]
    # The hardlink is not a duplicate
    with db.conn() as c:
        kinds = {r[0]: r[1] for r in c.execute("SELECT kind, reclaimable FROM duplicate_groups")}
    assert kinds["hardlink"] == 0


def test_protection(env):
    with db.conn() as c:
        prot = {r[0]: r[1] for r in c.execute("SELECT name, protect_reason FROM titles WHERE protected=1")}
    assert "Kids Movie" in prot and "Kids" in prot["Kids Movie"]
    assert "Keeper" in prot and "keep" in prot["Keeper"]
    assert not _sugg(None, name="Kids Movie")
    assert not _sugg(None, name="Keeper")


def test_play_fallback_by_name(env):
    with db.conn() as c:
        plays = c.execute("SELECT play_count FROM titles WHERE name='Keeper'").fetchone()[0]
    assert plays == 1  # rating key 999 does not exist, but name + year match


def test_series_and_seasons_no_double_count(env, client):
    series = _sugg(None, name="Old Show", kind="delete_title")[0]
    s2 = [s for s in _sugg(None, name="Old Show", kind="delete_season") if s["scope"] == "season:2"][0]
    total_series = sum(size for eid, sid, sn, ep, fn, size in ms.EPISODES if sid == 1)
    assert series["savings"] == total_series
    r = client.post("/api/selection", json={"ids": [series["id"], s2["id"]]}).json()
    assert r["freed"] == total_series
    assert r["naive_sum"] > r["freed"]


def test_large_episodes_replace(env):
    s = _sugg(None, name="Hot Show", kind="replace")[0]
    assert s["savings"] == sum(size - int(2.5 * GB) for eid, sid, sn, ep, fn, size in ms.EPISODES if sid == 2)


def test_old_download_suggested(env):
    s = _sugg(None, kind="download")
    assert len(s) == 1 and s[0]["savings"] == 4 * GB + 99


def test_api_overview_and_lists(client):
    o = client.get("/api/overview").json()
    assert o["counts"]["movies"] == 10 and o["counts"]["series"] == 2 and o["counts"]["episodes"] == 6
    libs = {l["library"]: l for l in o["libraries"]}
    # The hardlink is counted once per library
    assert libs["downloads"]["alloc"] == ms.SIZES[5] + ms.SIZES[6] + 4 * GB + 99
    assert o["savings"]["freed"] > 0
    assert o["top_suggestions"][0]["score"] >= o["top_suggestions"][-1]["score"]
    lst = client.get("/api/suggestions", params={"min_score": 0, "q": "Twin"}).json()
    assert lst["total"] >= 2
    d = client.get(f"/api/suggestions/{lst['items'][0]['id']}").json()
    assert d["files"]
    t = client.get(f"/api/titles/{d['title_key']}").json()
    assert t["name"] == "Twin" and len(t["files"]) == 3
    assert client.get("/api/duplicates").json()["items"]
    assert client.get("/api/files/largest", params={"limit": 3}).json()["items"][0]["size"] == 80 * GB
    st = client.get("/api/settings").json()
    assert st["services"]["radarr"]["api_key"] == settings.MASK
    csv = client.get("/api/export/suggestions.csv")
    assert csv.status_code == 200 and "Big Movie" in csv.text


def test_settings_mask_roundtrip(client):
    st = client.get("/api/settings").json()
    st["analysis"]["min_score"] = 25
    client.put("/api/settings", json=st)
    assert settings.get()["services"]["radarr"]["api_key"] == ms.KEY  # not overwritten with the mask
    assert settings.get()["analysis"]["min_score"] == 25


def test_service_test_endpoint(client):
    assert client.post("/api/services/radarr/test").json()["ok"] is True
    bad = client.post("/api/services/radarr/test", json={"api_key": "feil"}).json()
    assert bad["ok"] is False and "Autentisering" in bad["error"]


def test_unreachable_service_does_not_crash():
    s = settings.get()
    s["services"]["tautulli"]["url"] = "http://127.0.0.1:1"
    from app.clients.base import ServiceError
    from app.clients import tautulli
    with pytest.raises(ServiceError):
        tautulli.fetch_history({**s["services"]["tautulli"]}, None)


def _title(name):
    with db.conn() as c:
        r = db.rows(c, "SELECT * FROM titles WHERE name=?", (name,))[0]
    r["requests"] = json.loads(r["requests"] or "[]")
    from app.i18n import localize
    return localize(r, "nb")


def test_seerr_requests_mapped_and_watched_by_username(env):
    big = _title("Big Movie")
    assert [r["by"] for r in big["requests"]] == ["Bjørn B."] and big["requests"][0]["watched"] is False
    # Anna så Popular: Tautulli viser «Anna» (visningsnavn) / «anna» (brukernavn), Seerr har plexUsername «anna»
    pop = _title("Popular")
    assert pop["requests"][0]["watched"] is True
    # Kids Movie is not in Radarr – linked through the Plex ratingKey
    assert _title("Kids Movie")["requests"][0]["by"] == "Anna"
    assert _title("Old Show")["requested_by"] == "Bjørn B."


def test_seerr_affects_score_transparently(env):
    big = _sugg(None, name="Big Movie", kind="delete_title")[0]
    c = [x for x in big["components"] if x["key"] == "request"][0]
    assert c["points"] == 8 and "Bjørn B." in c["detail"] and "ingen av dem har sett" in c["detail"]
    twin = _sugg(None, name="Twin", kind="delete_title")[0]
    c = [x for x in twin["components"] if x["key"] == "request"][0]
    assert c["points"] == -15 and "Cecilie" in c["detail"]
    pop = _sugg(None, name="Popular", kind="delete_title")[0]
    assert [x for x in pop["components"] if x["key"] == "request"][0]["points"] == 0


def test_requesters_api_and_filter(client):
    r = {x["name"]: x for x in client.get("/api/requesters").json()["items"]}
    assert r["Bjørn B."]["titles"] == 2 and r["Bjørn B."]["not_watched_by_requester"] == 2
    assert r["Anna"]["titles"] == 2 and r["Anna"]["not_watched_by_requester"] == 1  # Kids Movie not watched
    lst = client.get("/api/suggestions", params={"requested_by": "Bjørn B.", "min_score": 0}).json()
    names = {i["title_name"] for i in lst["items"]}
    assert names == {"Big Movie", "Old Show"}
    assert lst["items"][0]["requested_by"] == "Bjørn B."
    t = client.get("/api/titles", params={"requested_by": "Anna"}).json()
    assert {i["name"] for i in t["items"]} == {"Popular", "Kids Movie"}


def test_posters_from_plex_cached_and_radarr_fallback(client):
    key = _title("Big Movie")["key"]
    before = ms.POSTER_HITS["plex"]
    r = client.get(f"/api/poster/{key}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert "max-age" in r.headers["cache-control"]
    client.get(f"/api/poster/{key}")
    assert ms.POSTER_HITS["plex"] == before + 1          # second time from the cache
    # Keeper has no poster in Plex -> fetched from Radarr
    r = client.get(f"/api/poster/{_title('Keeper')['key']}")
    assert r.status_code == 200 and ms.POSTER_HITS["radarr"] >= 1
    # Series with the poster on the show item in Plex
    assert client.get(f"/api/poster/{_title('Old Show')['key']}").status_code == 200
    assert client.get("/api/poster/finnes:ikke").status_code == 404



def test_library_views(client):
    r = client.get("/api/library/movie", params={"sort": "score"}).json()
    s = r["summary"]
    assert s["count"] == 10 and s["never"]["count"] >= 3 and s["freed"] > 0
    assert any(a["kind"] == "delete_title" for a in s["actions"])
    assert r["items"][0]["best"]["score"] >= r["items"][-1]["best"]["score"] if r["items"][-1]["best"] else True
    big = next(i for i in r["items"] if i["name"] == "Big Movie")
    assert big["delete_id"] and big["best"]["kind"] == "delete_title"
    never = client.get("/api/library/movie", params={"view": "never"}).json()
    assert all(not i["play_count"] for i in never["items"])
    prot = client.get("/api/library/movie", params={"view": "protected"}).json()
    assert {i["name"] for i in prot["items"]} == {"Kids Movie", "Keeper"}
    tv = client.get("/api/library/series", params={"sort": "size"}).json()
    assert tv["summary"]["count"] == 2 and tv["items"][0]["name"] == "Hot Show"
    assert client.get("/api/library/musikk").status_code == 404


def test_requester_page(client):
    r = client.get("/api/requesters/Bjørn B.").json()
    s = r["summary"]
    assert s["count"] == 2 and s["unwatched_by_user"]["count"] == 2 and s["movies"]["count"] == 1
    assert s["unwatched_delete"]["count"] == 2 and s["unwatched_delete"]["freed"] > 0
    anna = client.get("/api/requesters/Anna", params={"view": "unwatched"}).json()
    assert [i["name"] for i in anna["items"]] == ["Kids Movie"] and anna["items"][0]["protected"]
    assert anna["summary"]["unwatched_delete"]["count"] == 0  # protected titles are left out


def test_find_smaller_movie_versions(client):
    r = client.get(f"/api/releases/{_title('Big Movie')['key']}").json()
    assert r["service"] == "radarr" and r["current_size"] == 80 * GB and r["total"] == 6
    names = [x["title"] for x in r["releases"]]
    assert "Big.Movie.2010.2160p.REMUX" not in names                # not smaller
    top = r["releases"][0]
    assert top["title"] == "Big.Movie.2010.1080p.BluRay.x264" and top["recommended"]
    assert any("mindre" in x for x in top["reasons"])
    zero = next(x for x in r["releases"] if x["title"].endswith("WEB.x265"))
    assert not zero["recommended"] and "Ingen delere" in zero["warnings"]
    banned = next(x for x in r["releases"] if "HDTV" in x["title"])
    assert "Release is banned" in banned["warnings"]
    assert not any("preference" in w for x in r["releases"] for w in x["warnings"])  # forventet avvisning skjules
    # Second time from the cache – no new indexer search
    n = len(ms.RELEASE_CALLS)
    assert client.get(f"/api/releases/{_title('Big Movie')['key']}").json()["cached"] is True
    assert len(ms.RELEASE_CALLS) == n


def test_find_smaller_season_pack(client):
    key = _title("Hot Show")["key"]
    assert client.get(f"/api/releases/{key}").status_code == 400      # a season must be chosen
    r = client.get(f"/api/releases/{key}", params={"season": 1}).json()
    assert r["episode_releases"] == 1 and [x["title"] for x in r["releases"]] == ["Hot.Show.S01.1080p.WEB.x265"]
    assert r["episodes"] == 2


def test_swap_download_first_then_replace(client):
    key = _title("Big Movie")["key"]
    rel = next(r for r in client.get(f"/api/releases/{key}").json()["releases"] if r["recommended"])
    body = {"key": key, "guid": rel["guid"], "indexer_id": rel["indexer_id"], "after_swap": "unmonitor"}
    _enable_actions(client, False)
    assert client.post("/api/swaps", json=body).status_code == 403
    _enable_actions(client, True)
    try:
        sw = client.post("/api/swaps", json=body).json()
        assert sw["state"] == "waiting" and sw["old_size"] == 80 * GB
        assert ("POST", "/radarr/api/v3/release", {}, {"guid": rel["guid"], "indexerId": 1}) in ms.WRITES
        assert client.post("/api/swaps", json=body).status_code == 400          # ett bytte om gangen
        n = len(ms.WRITES)
        ms.QUEUE[:] = [{"title": rel["title"], "downloadId": "DL1", "size": 100, "sizeleft": 40, "status": "downloading",
                        "trackedDownloadState": "downloading", "trackedDownloadStatus": "ok"}]
        sw = client.post(f"/api/swaps/{sw['id']}/poll").json()
        assert sw["state"] == "downloading" and sw["download_id"] == "DL1" and len(ms.WRITES) == n
        # Finished, but with a rejection that is not about upgrading → nothing is deleted
        ms.QUEUE[0].update(sizeleft=0, status="completed", trackedDownloadState="importPending")
        ms.MANUAL[:] = [{"path": "/downloads/x/Big.mkv", "quality": {}, "rejections": [{"reason": "Sample"}]}]
        sw = client.post(f"/api/swaps/{sw['id']}/poll").json()
        assert sw["state"] == "needs_help" and "Sample" in sw["message"] and len(ms.WRITES) == n
        # New attempt where only «not an upgrade» is in the way
        sw = client.post("/api/swaps", json=body).json()
        ms.MANUAL[:] = [{"path": "/downloads/x/Big.mkv", "quality": {"quality": {"id": 7}},
                         "rejections": [{"reason": "Not an upgrade for existing movie file(s)"}]}]
        sw = client.post(f"/api/swaps/{sw['id']}/poll").json()
        assert sw["state"] == "importing"
        new = ms.WRITES[n:]
        assert ("DELETE", "/radarr/api/v3/moviefile/301", {}, None) in new
        imp = next(w for w in new if w[0] == "POST" and w[3].get("name") == "ManualImport")
        assert imp[3]["files"][0]["path"] == "/downloads/x/Big.mkv" and imp[3]["files"][0]["movieId"] == 1
        assert new.index(("DELETE", "/radarr/api/v3/moviefile/301", {}, None)) < new.index(imp)  # delete before import
        ms.QUEUE[:] = []
        sw = client.post(f"/api/swaps/{sw['id']}/poll").json()
        assert sw["state"] == "done" and "Avovervåket" in sw["message"]
        put = next(w for w in ms.WRITES if w[0] == "PUT" and w[1] == "/radarr/api/v3/movie/1")
        assert put[3]["monitored"] is False
        assert len(client.get(f"/api/swaps?key={key}").json()["items"]) == 2
        assert [p["name"] for p in client.get("/api/quality-profiles/radarr").json()["items"]] == ["Any", "HD-1080p"]
    finally:
        _enable_actions(client, False)
        ms.QUEUE[:] = []
        ms.MANUAL[:] = []
        ms.WRITES.clear()


def test_quality_overview_and_batch_swap(client):
    r = client.get("/api/quality").json()
    big = next(i for i in r["items"] if i["name"] == "Big Movie")
    assert big["season"] is None and big["size"] == 80 * GB and big["estimate"] == 68 * GB
    assert not any(i["name"] == "Popular" for i in r["items"])          # under grensen
    assert all(i["name"] != "Big Movie" for i in client.get("/api/quality", params={"min_movie_gb": 100}).json()["items"])
    client.get(f"/api/releases/{big['key']}")                              # fyller cachen
    big = next(i for i in client.get("/api/quality").json()["items"] if i["name"] == "Big Movie")
    rel = big["search"]["release"]
    assert rel["title"] == "Big.Movie.2010.1080p.BluRay.x264"
    item = {"key": big["key"], "guid": rel["guid"], "indexer_id": rel["indexer_id"]}
    _enable_actions(client, False)
    assert client.post("/api/swaps/batch", json={"items": [item]}).status_code == 403
    _enable_actions(client, True)
    try:
        res = client.post("/api/swaps/batch", json={"items": [item, {**item, "key": "movie:r:999"}], "after_swap": "unmonitor"}).json()
        assert res["started"] == 1 and res["failed"] == 1
        big = next(i for i in client.get("/api/quality").json()["items"] if i["name"] == "Big Movie")
        assert big["swap"]["state"] == "waiting"
        client.post(f"/api/swaps/{big['swap']['id']}/cancel")
    finally:
        _enable_actions(client, False)
        ms.WRITES.clear()


def _enable_actions(client, on):
    st = client.get("/api/settings").json()
    st["actions"] = {**st.get("actions", {}), "enabled": on}
    client.put("/api/settings", json=st)


def test_downloads_overview(client):
    r = client.get("/api/downloads").json()
    by = {i["name"]: i for i in r["items"]}
    assert by["Hardlinked.2011.mkv"]["status"] == "hardlinked" and by["Hardlinked.2011.mkv"]["freed"] == 0
    assert by["Copy.2013.mkv"]["status"] == "copied" and by["Copy.2013.mkv"]["title_name"] == "Copy"
    old = by["Old.Download"]
    assert old["status"] == "not_imported" and old["advice"] == "consider" and old["is_dir"]
    assert r["summary"]["count"] == 3


def test_plex_check(client):
    r = client.get("/api/plex-check").json()
    assert r["available"]
    names = {g["name"]: g for g in r["items"]}
    assert "Orphan" in names and "Disc" in names
    assert "ISO" in names["Disc"]["reason"]
    assert "Kids Movie" not in names and "Big Movie" not in names
    assert not any("/downloads" in g["folder"] for g in r["items"])            # the downloads folder is left out
    m = client.get("/api/plex-check", params={"view": "missing"}).json()
    assert [g["name"] for g in m["items"]] == ["Gone"] and m["items"][0]["files"][0]["path"] == "/mnt/tank/media/Movies/Gone (1999)/Gone.1999.mkv"
    res = client.post("/api/plex-check/rescan", json={"folder": "/mnt/tank/media/Movies/Orphan (2001)"}).json()
    assert res["ok"] and ms.PLEX_REFRESH[-1] == ("1", "/Movies/Orphan (2001)")
    assert client.post("/api/plex-check/rescan", json={"folder": "/mnt/tank/media/downloads/x"}).status_code == 400


# ------------------------------------------------------------------ deletion (runs last)

def _sid(name, kind, scope=None):
    for s in _sugg(None, name=name, kind=kind):
        if scope is None or s["scope"] == scope:
            return s["id"]
    raise AssertionError((name, kind, scope))


@pytest.fixture
def no_refresh(monkeypatch):
    from app import jobs
    calls = []
    monkeypatch.setattr(jobs, "enqueue", lambda kind: calls.append(kind) or {"id": 0})
    return calls


def _enable(client, on=True):
    st = client.get("/api/settings").json()
    st["actions"] = {"enabled": on}
    client.put("/api/settings", json=st)


def test_delete_disabled_by_default(client, no_refresh):
    _enable(client, False)
    big = _sid("Big Movie", "delete_title")
    p = client.post("/api/actions/plan", json={"ids": [big]}).json()
    assert p["enabled"] is False
    r = client.post("/api/actions/execute", json={"ids": [big], "token": p["token"]})
    assert r.status_code == 403
    assert not ms.WRITES


def test_delete_plan_rules(client, no_refresh):
    _enable(client)
    ids = [_sid("Big Movie", "delete_title"), _sid("Big Movie", "replace"),
           _sid("Old Show", "delete_title"), _sid("Old Show", "delete_season", "season:2")]
    p = client.post("/api/actions/plan", json={"ids": ids}).json()
    by = {i["id"]: i for i in p["items"]}
    assert by[ids[0]]["executable"] and by[ids[0]]["service"] == "radarr"
    assert not by[ids[1]]["executable"] and "Bytt kvalitet" in by[ids[1]]["reason"]
    assert by[ids[2]]["executable"] and by[ids[2]]["service"] == "sonarr"
    assert not by[ids[3]]["executable"] and "hele serien" in by[ids[3]]["reason"]
    assert p["executable"] == 2 and p["freed"] > 0
    # Endret utvalg -> gammel token avvises
    r = client.post("/api/actions/execute", json={"ids": ids[:1], "token": p["token"]})
    assert r.status_code == 409


def test_protected_never_executable():
    from app import actions
    d = actions._describe({"id": "x", "label": "K", "location": "", "kind": "delete_title", "risk": "low",
                           "savings": 1, "title_key": "k", "scope": "title"},
                          {"protected": 1, "protect_reason": "Biblioteket Kids er beskyttet", "radarr_id": 9,
                           "sonarr_id": None})
    assert d["executable"] is False and "Kids" in text(d["reason"], "nb")


def test_delete_movie_via_radarr(client, no_refresh):
    _enable(client)
    big = _sid("Big Movie", "delete_title")
    p = client.post("/api/actions/plan", json={"ids": [big]}).json()
    r = client.post("/api/actions/execute", json={"ids": [big], "token": p["token"]}).json()
    assert r["done"] == 1 and r["results"][0]["status"] == "done"
    assert ("DELETE", "/radarr/api/v3/movie/1", {"deleteFiles": "true", "addImportExclusion": "false"}, None) in ms.WRITES
    assert r["freed_estimate"] == 80 * GB
    assert no_refresh == ["refresh"]
    h = client.get("/api/actions/history").json()["items"]
    assert h[0]["title"] == "Big Movie" and h[0]["status"] == "done"


def test_delete_season_unmonitors_then_deletes_files(client, no_refresh):
    _enable(client)
    s2 = _sid("Old Show", "delete_season", "season:2")
    p = client.post("/api/actions/plan", json={"ids": [s2]}).json()
    assert p["items"][0]["executable"]
    ms.WRITES.clear()
    r = client.post("/api/actions/execute", json={"ids": [s2], "token": p["token"]}).json()
    assert r["done"] == 1, r
    put = [w for w in ms.WRITES if w[0] == "PUT"][0]
    assert {s["seasonNumber"]: s["monitored"] for s in put[3]["seasons"]} == {1: True, 2: False}
    bulk = [w for w in ms.WRITES if w[1].endswith("/bulk")][0]
    assert sorted(bulk[3]["episodeFileIds"]) == [13, 14]
    assert ms.WRITES.index(put) < ms.WRITES.index(bulk)  # unmonitor before deleting


def test_delete_stops_when_folder_changed(client, no_refresh):
    _enable(client)
    twin = _sid("Twin", "delete_title")
    ms.PATH_OVERRIDE[("movie", 3)] = "/Movies/Noe annet (2012)"
    ms.WRITES.clear()
    p = client.post("/api/actions/plan", json={"ids": [twin]}).json()
    r = client.post("/api/actions/execute", json={"ids": [twin], "token": p["token"]}).json()
    assert r["results"][0]["status"] == "failed" and "stemmer ikke" in r["results"][0]["detail"]
    assert not [w for w in ms.WRITES if w[0] == "DELETE"]
    assert no_refresh == []
    ms.PATH_OVERRIDE.clear()


# ------------------------------------------------------------------ duplicates (changes files on disk – runs last of all)

def _enable_files(client, on=True):
    st = client.get("/api/settings").json()
    st["actions"] = {**st.get("actions", {}), "files_enabled": on}
    client.put("/api/settings", json=st)


def _media_root():
    return settings.get()["libraries"][0]["container_path"].rsplit("/", 1)[0]


def test_duplicates_overview(client):
    r = client.get("/api/duplicates").json()
    s = r["summary"]
    assert s["identical"]["groups"] == 1 and s["identical"]["in_downloads"] == 1
    assert s["versions"]["groups"] == 1 and s["versions"]["reclaimable"] == ms.EXTRA_TWIN[1]
    assert s["hardlink"]["groups"] == 1 and s["hardlink"]["reclaimable"] == 0
    only_dl = client.get("/api/duplicates", params={"where": "downloads"}).json()
    assert {g["kind"] for g in only_dl["items"]} == {"identical", "hardlink"}
    twin = client.get("/api/duplicates", params={"kind": "versions", "q": "twin"}).json()["items"][0]
    assert twin["title_name"] == "Twin" and any(f["managed"] for f in twin["files"])


def test_duplicate_delete_disabled(client, no_refresh):
    _enable_files(client, False)
    g = client.get("/api/duplicates", params={"kind": "identical"}).json()["items"][0]
    p = client.post("/api/duplicates/plan", json={"groups": [{"id": g["id"]}]}).json()
    assert p["enabled"] is False
    r = client.post("/api/duplicates/execute", json={"groups": [{"id": g["id"]}], "token": p["token"]})
    assert r.status_code == 403


def test_duplicate_managed_file_swapped_via_radarr(client, no_refresh):
    """Keep the unmanaged version: Radarr deletes its file and rescans the folder."""
    import os
    _enable_files(client)
    g = client.get("/api/duplicates", params={"kind": "versions"}).json()["items"][0]
    unmanaged = next(f["path"] for f in g["files"] if not f["managed"])
    p = client.post("/api/duplicates/plan", json={"groups": [{"id": g["id"], "keep": unmanaged}]}).json()
    f = p["items"][0]["files"][0]
    assert f["ok"] and f["via"] == "radarr" and f["path"].endswith("Twin.2012.1080p.mkv")
    ms.WRITES.clear()
    r = client.post("/api/duplicates/execute",
                    json={"groups": [{"id": g["id"], "keep": unmanaged}], "token": p["token"]}).json()
    assert r["done"] == 1, r
    assert ("DELETE", "/radarr/api/v3/moviefile/303", {}, None) in ms.WRITES
    cmd = [w for w in ms.WRITES if w[0] == "POST"][0]
    assert cmd[3] == {"name": "RescanMovie", "movieId": 3}
    assert ms.WRITES.index(("DELETE", "/radarr/api/v3/moviefile/303", {}, None)) < ms.WRITES.index(cmd)
    # The app did not touch the files on disk itself
    root = _media_root()
    assert os.path.exists(f"{root}/Movies/Twin (2012)/Twin.2012.1080p.mkv")
    h = client.get("/api/actions/history").json()["items"][0]
    assert h["service"] == "radarr" and h["status"] == "done"


def test_duplicate_managed_refused_when_keep_outside_folder(client, no_refresh):
    _enable_files(client)
    g = client.get("/api/duplicates", params={"kind": "identical"}).json()["items"][0]
    tmp_copy = next(f["path"] for f in g["files"] if f["in_downloads"])
    p = client.post("/api/duplicates/plan", json={"groups": [{"id": g["id"], "keep": tmp_copy}]}).json()
    f = p["items"][0]["files"][0]
    assert not f["ok"] and "utenfor mappen" in f["reason"]


def test_duplicate_delete_identical_copy_from_disk(client, no_refresh):
    import os
    _enable_files(client)
    g = client.get("/api/duplicates", params={"kind": "identical"}).json()["items"][0]
    p = client.post("/api/duplicates/plan", json={"groups": [{"id": g["id"]}]}).json()
    it = p["items"][0]
    assert it["executable"] and it["keep"] == "/mnt/tank/media/Movies/Copy (2013)/Copy.2013.mkv"
    assert [f["path"] for f in it["files"]] == ["/mnt/tank/media/downloads/Copy.2013.mkv"] and it["warn_downloads"]
    assert p["freed"] == ms.SIZES[6]
    root = _media_root()
    assert os.path.exists(f"{root}/downloads/Copy.2013.mkv")
    r = client.post("/api/duplicates/execute", json={"groups": [{"id": g["id"]}], "token": p["token"]}).json()
    assert r["done"] == 1, r
    assert not os.path.exists(f"{root}/downloads/Copy.2013.mkv")
    assert os.path.exists(f"{root}/Movies/Copy (2013)/Copy.2013.mkv")  # beholdt
    assert no_refresh == ["refresh"]
    h = client.get("/api/actions/history").json()["items"][0]
    assert h["service"] == "disk" and h["status"] == "done"


def test_duplicate_delete_refuses_changed_file(client, no_refresh):
    import os
    _enable_files(client)
    g = client.get("/api/duplicates", params={"kind": "versions"}).json()["items"][0]
    p = client.post("/api/duplicates/plan", json={"groups": [{"id": g["id"]}]}).json()
    assert p["items"][0]["executable"]
    extra = f"{_media_root()}/Movies/Twin (2012)/Twin.2012.2160p.mkv"
    os.utime(extra, (1_000_000_000, 1_000_000_000))  # endres etter skanning
    r = client.post("/api/duplicates/execute", json={"groups": [{"id": g["id"]}], "token": p["token"]})
    # The plan is rebuilt at execution; the change makes the file undeletable -> the token differs or the file is refused
    if r.status_code == 200:
        assert r.json()["done"] == 0
    else:
        assert r.status_code == 409
    assert os.path.exists(extra)



def test_duplicate_protection_setting(monkeypatch):
    from app import dupes
    lib = {"name": "Kids", "host_path": "/mnt/tank/media/Kids", "container_path": "/x", "protected": True}
    s = settings.get()
    s["protection"]["include_duplicates"] = False
    monkeypatch.setattr(settings, "get", lambda: s)
    assert dupes.protection_applies() is False
    # With protection off for duplicates, a protected title/library does not stop the check
    r = dupes._check_file({"path": "/mnt/tank/media/Kids/a.mkv"}, {"size": 1, "mtime": 0, "inode": 1}, set(), False)
    assert r is None or "beskyttet" not in r
    s["protection"]["include_duplicates"] = True
    assert dupes.protection_applies() is True
    r = dupes._check_file({"path": "/mnt/tank/media/Kids/a.mkv"}, {"size": 1, "mtime": 0, "inode": 1}, set(), True)
    assert "beskyttet" in text(r, "nb")



def test_downloads_delete_folder(client, no_refresh):
    import os
    _enable_files(client)
    path = "/mnt/tank/media/downloads/Old.Download"
    p = client.post("/api/downloads/plan", json={"paths": [path, "/mnt/tank/media/Movies/Big Movie (2010)"]}).json()
    assert p["count"] == 1 and p["items"][1]["ok"] is False
    r = client.post("/api/downloads/execute", json={"paths": [path, "/mnt/tank/media/Movies/Big Movie (2010)"], "token": p["token"]}).json()
    assert r["done"] == 1
    root = _media_root()
    assert not os.path.exists(f"{root}/downloads/Old.Download")
    assert os.path.exists(f"{root}/Movies/Big Movie (2010)")


def test_plex_remove_missing_item(client, no_refresh):
    _enable(client, False)
    p = client.post("/api/plex-check/remove/plan", json={"keys": ["movie:199"]}).json()
    assert p["enabled"] is False and p["count"] == 1 and p["items"][0]["calls"][0]["rating_key"] == "199"
    assert client.post("/api/plex-check/remove/execute", json={"keys": ["movie:199"], "token": p["token"]}).status_code == 403
    _enable(client, True)
    try:
        # Big Movie exists on disk → no calls
        p = client.post("/api/plex-check/remove/plan", json={"keys": ["movie:199", "movie:101"]}).json()
        bad = next(i for i in p["items"] if i["key"] == "movie:101")
        assert not bad["ok"] and "finnes" in bad["reason"]
        assert client.post("/api/plex-check/remove/execute", json={"keys": ["movie:199"], "token": "feil"}).status_code == 409
        r = client.post("/api/plex-check/remove/execute", json={"keys": ["movie:199", "movie:101"], "token": p["token"]}).json()
        assert r["done"] == 1 and ms.PLEX_DELETES == ["/library/metadata/199"]
    finally:
        _enable(client, False)


def test_delete_orphan_folder_from_disk(client, no_refresh):
    from pathlib import Path
    root = Path(_media_root())
    orphan = _title("Orphan")["key"]
    assert orphan.startswith("dir:")
    _enable_files(client, True)
    try:
        p = client.post("/api/plex-check/delete/plan", json={"keys": [orphan, _title("Big Movie")["key"]]}).json()
        ok = next(i for i in p["items"] if i["key"] == orphan)
        assert ok["ok"] and ok["freed"] == 6 * GB + 41 and p["count"] == 1
        assert "Radarr" in next(i for i in p["items"] if i["key"] != orphan)["reason"]
        # ny fil siden skanning → stopper
        extra = root / "Movies/Orphan (2001)/ny.nfo"
        extra.write_text("x")
        p2 = client.post("/api/plex-check/delete/plan", json={"keys": [orphan]}).json()
        assert not p2["items"][0]["ok"] and "endret" in p2["items"][0]["reason"]
        extra.unlink()
        assert client.post("/api/plex-check/delete/execute", json={"keys": [orphan], "token": "feil"}).status_code == 409
        p = client.post("/api/plex-check/delete/plan", json={"keys": [orphan]}).json()
        r = client.post("/api/plex-check/delete/execute", json={"keys": [orphan], "token": p["token"]}).json()
        assert r["done"] == 1 and not (root / "Movies/Orphan (2001)").exists() and (root / "Movies").exists()
    finally:
        _enable_files(client, False)


def test_other_storage_breakdown(client):
    from app import db as _db
    assert client.get("/api/other-storage").json()["available"] is False
    lib_total = client.get("/api/other-storage").json()["libs_total"]
    with _db.conn() as c:
        _db.kv_set(c, "truenas", {"pool": {"name": "tank", "size": 1000 * GB, "allocated": lib_total + 300 * GB, "free": 100 * GB},
                                  "datasets": [
                                      {"name": "tank", "mountpoint": "/mnt/tank", "used": lib_total + 280 * GB,
                                       "referenced": lib_total + 50 * GB, "usedbysnapshots": 30 * GB},
                                      {"name": "tank/.ix-apps", "mountpoint": "/mnt/.ix-apps", "used": 200 * GB,
                                       "referenced": 200 * GB, "usedbysnapshots": 0}],
                                  "fetched": 1})
    try:
        r = client.get("/api/other-storage").json()
        assert r["available"] and r["other"] == 300 * GB and r["snapshots"] == 30 * GB
        top = r["items"][0]
        assert top["name"] == "tank/.ix-apps" and top["kind"].startswith("TrueNAS-apper")
        root = next(i for i in r["items"] if i["name"] == "tank")
        assert root["other"] == 50 * GB and set(root["libraries"]) >= {"Movies", "TV"}
        assert r["overhead"] == 300 * GB - 280 * GB
    finally:
        with _db.conn() as c:
            _db.kv_set(c, "truenas", None)


# ------------------------------------------------------------------ 1.0: language, setup, overview

def test_language_follows_header(client):
    big = _title("Big Movie")["key"]
    nb = client.get(f"/api/titles/{big}").json()["suggestions"][0]
    en = client.get(f"/api/titles/{big}", headers={"X-Lang": "en"}).json()["suggestions"][0]
    assert nb["label"] == "Slett filmen" and en["label"] == "Delete the movie"
    assert any(c["label"] == "Aldri sett" for c in nb["components"])
    assert any(c["label"] == "Never watched" for c in en["components"])
    # Accept-Language works too, and errors are translated
    r = client.get("/api/titles/finnes:ikke", headers={"X-Lang": "", "Accept-Language": "en-GB,en;q=0.8"})
    assert r.status_code == 404 and r.json()["detail"] == "Title not found"
    assert client.get("/api/titles/finnes:ikke").json()["detail"] == "Fant ikke tittelen"
    # CSV follows the language
    assert client.get("/api/export/suggestions.csv", headers={"X-Lang": "en"}).text.lstrip("﻿").startswith("score,risk,action")


def test_overview_recommended_and_areas(client):
    o = client.get("/api/overview").json()
    rec, all_ = o["savings"]["recommended"], o["savings"]
    assert rec["min_score"] == 50 and 0 < rec["freed"] <= all_["freed"]
    a = o["areas"]
    assert a["duplicates"]["freed"] > 0 and "total" in a["downloads"] and a["quality"]["count"] >= 1
    assert a["plex"]["available"] and a["plex"]["not_in_plex"]["groups"] >= 1
    r = client.get("/api/suggestions", params={"recommended": "true"}).json()
    assert r["items"] and all(s["score"] >= 50 and s["risk"] != "high" for s in r["items"])


def test_setup_checklist_and_path_suggestions(client):
    from app import db as _db
    st = client.get("/api/setup", headers={"X-Lang": "en"}).json()
    steps = {s["id"]: s for s in st["steps"]}
    assert steps["libraries"]["done"] and steps["services"]["done"] and steps["refresh"]["done"]
    assert steps["paths"]["done"], st["paths"]
    # A root folder the mappings do not cover gets a suggestion from the folder name
    with _db.conn() as c:
        roots = _db.kv_get(c, "root_folders", {})
        _db.kv_set(c, "root_folders", {**roots, "radarr": roots.get("radarr", []) + ["/data/media/Movies"]})
    try:
        st = client.get("/api/setup").json()
        p = next(x for x in st["paths"] if x["path"] == "/data/media/Movies")
        assert not p["ok"] and p["suggestion"] == {"from": "/data/media/Movies", "to": "/mnt/tank/media/Movies", "library": "Movies"}
        assert not next(s for s in st["steps"] if s["id"] == "paths")["done"]
    finally:
        with _db.conn() as c:
            _db.kv_set(c, "root_folders", roots)


def test_legacy_status_values_are_migrated(client):
    from app import actions as _actions, db as _db, swaps as _swaps
    with _db.conn() as c:
        sid = c.execute("INSERT INTO swaps(title_key, state, log) VALUES('x', 'trenger_hjelp', '[]')").lastrowid
        aid = c.execute("INSERT INTO actions(ts, status, detail) VALUES(1, 'utført', 'gammel tekst')").lastrowid
    _swaps.init()
    _actions.init()
    with _db.conn() as c:
        assert c.execute("SELECT state FROM swaps WHERE id=?", (sid,)).fetchone()[0] == "needs_help"
        assert c.execute("SELECT status FROM actions WHERE id=?", (aid,)).fetchone()[0] == "done"
        c.execute("DELETE FROM swaps WHERE id=?", (sid,))
        c.execute("DELETE FROM actions WHERE id=?", (aid,))


def test_sonarr_episodefile_404_falls_back_and_skips(env):
    """Some Sonarr setups answer 404 on /episodefile?seriesId=; one missing series must not fail the sync."""
    from app.clients import arr
    from app.i18n import text
    cfg = settings.get()["services"]["sonarr"]
    ms.EPISODEFILE_404.add(2)
    ms.GONE_SERIES.add(1)
    try:
        series, files, skipped = arr.fetch_sonarr(cfg, lambda p: p)
        assert skipped == ["Old Show"]
        assert sorted(f[0] for f in files) == [21, 22]           # read through /episode?includeEpisodeFile=true
        assert {f[2] for f in files} == {1}                      # season number kept
        ms.GONE_SERIES.add(2)
        with pytest.raises(arr.ServiceError):
            arr.fetch_sonarr(cfg, lambda p: p)
        assert arr.episode_files(cfg["url"], {"X-Api-Key": ms.KEY}, 2) is None
        with pytest.raises(arr.ServiceError) as e:  # the error carries the service's own explanation
            arr.get_json(f"{cfg['url']}/api/v3/episodefile", params={"seriesId": 2}, headers={"X-Api-Key": ms.KEY})
        assert "does not exist" in text(e.value.msg, "en")
    finally:
        ms.EPISODEFILE_404.clear()
        ms.GONE_SERIES.clear()


# ------------------------------------------------------------------ download rules

def _arr_setup(client):
    r = client.get("/api/arr-setup")
    assert r.status_code == 200, r.text
    return r.json()


def test_arr_setup_overview(client):
    ms.reset_arr_state()
    d = _arr_setup(client)
    radarr = d["services"]["radarr"]
    prof = {p["name"]: p for p in radarr["profiles"]}
    assert prof["Any"]["count"] == 1 and prof["HD-1080p"]["count"] == 6
    kinds = {f["id"].split(":", 2)[2] for f in prof["Any"]["findings"]}
    assert {"remux", "disc", "cf:1", "unlimited"} <= kinds
    assert not any(f["id"].endswith(":remux") for f in prof["HD-1080p"]["findings"])
    assert prof["HD-1080p"]["allowed"][0] == "Bluray-1080p" and prof["HD-1080p"]["cutoff"] == "Bluray-1080p"
    remux = next(x for x in radarr["definitions"] if x["name"] == "Remux-2160p")
    assert remux["max"] is None and remux["presets"]["balanced"] == [187.4, 500, 600]
    # the 80 GB remux runs at ~680 MB/min – above the balanced ceiling
    assert any(r[0] > 600 for r in radarr["files"]["Bluray-2160p"])
    assert [r["key"] for r in radarr["recipes"]] == ["hd", "web", "uhd"]
    client_ = radarr["seeding"]["clients"][0]
    assert client_["remove_completed"] is False and client_["finding"]["change"]["op"] == "remove_completed"
    assert radarr["seeding"]["indexers"][0]["prowlarr"] is True
    # Seerr: same Radarr instance (profile names match), default «Any» allows remuxes
    seerr = {s["kind"]: s for s in d["seerr"]["servers"]}
    assert seerr["radarr"]["same_instance"] and seerr["radarr"]["slots"][0]["allows_remux"]
    assert 4 in seerr["radarr"]["slots"][0]["finding"]["alternatives"]
    assert [s["field"] for s in seerr["sonarr"]["slots"]] == ["activeProfileId", "activeAnimeProfileId"]
    # qBittorrent: only Radarr/Sonarr categories; imported ones can be removed
    q = d["qbit"]
    t = {x["hash"]: x for x in q["torrents"]}
    assert set(t) == {"aaa", "bbb", "ccc"}
    assert t["aaa"]["import_status"] == "hardlinked" and t["aaa"]["removable"]
    assert t["bbb"]["import_status"] == "copied" and t["bbb"]["removable"]
    assert t["ccc"]["import_status"] == "not_imported" and not t["ccc"]["removable"]
    assert q["finding"]["change"]["op"] == "qbit_prefs"
    assert q["url_hint"].endswith("/qbit")


def _changes(d):
    radarr = d["services"]["radarr"]
    defs = {x["name"]: x["presets"]["balanced"] for x in radarr["definitions"] if "balanced" in x["presets"]}
    return [
        {"op": "definitions", "service": "radarr", "values": defs},
        {"op": "disallow", "service": "radarr", "profile": 1, "qualities": ["Remux-1080p", "Remux-2160p", "BR-DISK", "Raw-HD"]},
        {"op": "cf_score", "service": "radarr", "profile": 1, "format": 1, "score": 0},
        {"op": "create_profile", "service": "radarr", "recipe": "uhd", "base": 1},
        {"op": "remove_completed", "service": "radarr", "client": 1},
        {"op": "seerr_profile", "kind": "radarr", "server": 0, "field": "activeProfileId", "profile": 4, "name": "HD-1080p"},
        {"op": "qbit_prefs", "ratio": 1.0, "minutes": 1440},
        {"op": "qbit_limits", "hashes": ["aaa"]},
        {"op": "qbit_remove", "hashes": ["bbb", "ccc"]},
    ]


def test_arr_setup_changes_need_switch_and_token(client, no_refresh):
    ms.reset_arr_state()
    _enable(client, False)
    changes = _changes(_arr_setup(client))
    p = client.post("/api/arr-setup/plan", json={"changes": changes}).json()
    assert p["enabled"] is False and not p["errors"]
    assert client.post("/api/arr-setup/execute", json={"changes": changes, "token": p["token"]}).status_code == 403
    _enable(client, True)
    try:
        # something changes in Radarr after the summary -> refused
        ms.ARR_STATE["radarr"]["profiles"][4]["upgradeAllowed"] = False
        r = client.post("/api/arr-setup/execute", json={"changes": changes, "token": p["token"]})
        assert r.status_code == 409
    finally:
        _enable(client, False)


def test_arr_setup_apply_and_restore(client, no_refresh):
    import os as _os
    ms.reset_arr_state()
    ms.WRITES.clear()
    _enable(client, True)
    try:
        changes = _changes(_arr_setup(client))
        p = client.post("/api/arr-setup/plan", json={"changes": changes}).json()
        assert not p["errors"], p["errors"]
        whats = " | ".join(r["what"] for r in p["rows"])
        assert "Remux" in whats and "UHD Bluray + WEB" in whats and "Etterspurt" not in whats
        skipped = [r for r in p["rows"] if r.get("skipped")]
        assert len(skipped) == 1 and "Old.Download" in skipped[0]["what"]
        r = client.post("/api/arr-setup/execute", json={"changes": changes, "token": p["token"]}).json()
        assert r["failed"] == 0, r
        st = ms.ARR_STATE["radarr"]
        remux = next(x for x in st["definitions"] if x["quality"]["name"] == "Remux-2160p")
        assert remux["maxSize"] == 600 and remux["preferredSize"] == 500
        any_ = st["profiles"][1]
        from app.arrsetup import allowed_qualities, cutoff_name
        assert not set(allowed_qualities(any_)) & {"Remux-1080p", "Remux-2160p", "BR-DISK", "Raw-HD"}
        assert cutoff_name(any_) == "HDTV-720p"  # unchanged – still allowed
        assert next(f for f in any_["formatItems"] if f["format"] == 1)["score"] == 0
        new = next(p_ for p_ in st["profiles"].values() if p_["name"] == "UHD Bluray + WEB")
        assert sorted(allowed_qualities(new)) == ["Bluray-2160p", "WEBDL-2160p", "WEBRip-2160p"] and cutoff_name(new) == "Bluray-2160p"
        assert next(f for f in new["formatItems"] if f["format"] == 2)["score"] == -10000  # carried over from the base
        assert st["clients"][1]["removeCompletedDownloads"] is True
        assert ms.SEERR_SERVERS["radarr"][0]["activeProfileId"] == 4
        assert ms.SEERR_SERVERS["radarr"][0]["activeProfileName"] == "HD-1080p"
        assert ms.QBIT["prefs"]["max_ratio_enabled"] and ms.QBIT["prefs"]["max_seeding_time"] == 1440
        assert ms.QBIT["torrents"]["aaa"]["ratio_limit"] == -2
        assert "bbb" not in ms.QBIT["torrents"] and "ccc" in ms.QBIT["torrents"]
        delete = next(x for x in ms.QBIT["log"] if x[0] == "delete")
        assert delete[1]["deleteFiles"] == "true" and delete[1]["hashes"] == "bbb"
        assert no_refresh == ["refresh"]
        # backup kept, with mode 600 (it contains Seerr's copy of the Radarr key)
        name = r["backup"]
        path = settings.DATA_DIR / "backups" / name
        assert oct(_os.stat(path).st_mode & 0o777) == "0o600"
        assert any(b["name"] == name for b in client.get("/api/arr-setup/backups").json()["items"])
        log = client.get("/api/actions/history").json()
        assert any(x["action"] == "arr_setup" and "UHD Bluray + WEB" in x["detail"] for x in log["items"])
        # restore puts everything back and deletes the created profile
        rr = client.post("/api/arr-setup/restore", json={"name": name}).json()
        assert rr["failed"] == 0, rr
        assert next(x for x in st["definitions"] if x["quality"]["name"] == "Remux-2160p")["maxSize"] is None
        assert "Remux-2160p" in allowed_qualities(st["profiles"][1])
        assert all(p_["name"] != "UHD Bluray + WEB" for p_ in st["profiles"].values())
        assert st["clients"][1]["removeCompletedDownloads"] is False
        assert ms.SEERR_SERVERS["radarr"][0]["activeProfileId"] == 1
        assert ms.QBIT["prefs"]["max_ratio_enabled"] is False
        assert client.post("/api/arr-setup/restore", json={"name": "../settings.json"}).status_code == 400
    finally:
        _enable(client, False)
        ms.reset_arr_state()


def test_disallow_splits_mixed_groups():
    from app.arrsetup import allowed_qualities, cutoff_name, disallow
    p = ms._profiles("radarr")[1]
    p["cutoff"] = 1003  # WEB 2160p group
    done = disallow(p, {"WEBRip-2160p", "Remux-2160p"})
    assert set(done) == {"WEBRip-2160p", "Remux-2160p"}
    assert "WEBDL-2160p" in allowed_qualities(p) and "WEBRip-2160p" not in allowed_qualities(p)
    assert cutoff_name(p) == "WEBDL-2160p"  # a one-quality group becomes a plain quality
    ms._validate_profile(p)


def test_disallow_leaves_no_single_quality_group():
    """Sonarr refuses «Groups must contain multiple qualities» (seen with an anime remux profile)."""
    from app.arrsetup import allowed_qualities, cutoff_name, disallow
    p = ms._profiles("sonarr")[1]
    remux = {"quality": {"id": 20, "name": "Bluray-1080p Remux"}, "items": [], "allowed": True}
    blu = {"quality": {"id": 7, "name": "Bluray-1080p"}, "items": [], "allowed": True}
    p["items"] = [x for x in p["items"] if x.get("quality", {}).get("name") not in ("Bluray-1080p", "Bluray-1080p Remux")]
    p["items"].append({"name": "Remux-1080p", "id": 1005, "allowed": True, "items": [remux, blu]})
    p["cutoff"] = 1005
    disallow(p, {"Bluray-1080p Remux"})
    assert all(len(it["items"]) != 1 for it in p["items"])
    assert "Bluray-1080p" in allowed_qualities(p) and "Bluray-1080p Remux" not in allowed_qualities(p)
    assert cutoff_name(p) == "Bluray-1080p"
    ms._validate_profile(p)  # would be accepted by Sonarr
