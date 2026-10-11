"""Ende-til-ende: mock-tjenester + glisne filer på disk -> synk -> skann -> analyse -> API."""
import json
import os
import socket
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

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
    (media / "FILM/Twin (2012)/Twin.2012.1080p.en.srt").write_text("1\n00:00:01 --> 00:00:02\nHei\n")
    show = {s[0]: s for s in ms.SERIES}
    for eid, sid, sn, ep, fn, size in ms.EPISODES:
        _sparse(media / show[sid][3].lstrip("/") / fn, size)
    _sparse(media / ms.KIDS[0].lstrip("/"), ms.KIDS[1])
    # Film på disk som verken Radarr eller Plex kjenner
    _sparse(media / "FILM/Orphan (2001)/Orphan.2001.1080p.mkv", 6 * GB + 41)
    _sparse(media / "FILM/Disc (2005)/Disc.2005.iso", 30 * GB + 42)
    # Hardlink fra nedlastingsmappen til en film
    (media / "tmp").mkdir()
    os.link(media / "FILM/Hardlinked (2011)/Hardlinked.2011.mkv", media / "tmp/Hardlinked.2011.mkv")
    # Identisk kopi (ny inode) i nedlastingsmappen
    _sparse(media / "tmp/Copy.2013.mkv", ms.SIZES[6])
    # Gammel nedlasting som aldri ble importert
    _sparse(media / "tmp/Old.Download/old.mkv", 4 * GB + 99)
    old = time.time() - 200 * 86400
    os.utime(media / "tmp/Old.Download/old.mkv", (old, old))

    base = f"http://127.0.0.1:{port}"
    s = settings.get()
    s["services"]["radarr"].update(url=f"{base}/radarr", api_key=ms.KEY)
    s["services"]["sonarr"].update(url=f"{base}/sonarr", api_key=ms.KEY)
    s["services"]["plex"].update(url=f"{base}/plex", token=ms.TOKEN)
    s["services"]["tautulli"].update(url=f"{base}/tautulli", api_key=ms.KEY)
    s["services"]["seerr"].update(url=f"{base}/seerr", api_key=ms.KEY, enabled=True)
    for lib in s["libraries"]:
        lib["container_path"] = str(media / lib["name"])
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
    with TestClient(app) as c:
        yield c


def _sugg(c, **filters):
    with db.conn() as conn:
        rows = db.rows(conn, "SELECT s.*, t.name FROM suggestions s LEFT JOIN titles t ON t.key=s.title_key")
    out = []
    for r in rows:
        if all(r.get(k) == v for k, v in filters.items()):
            r["components"] = json.loads(r["components"])
            out.append(r)
    return out


def test_sync_all_services_ok(env):
    for name in ("radarr", "sonarr", "plex", "tautulli", "seerr"):
        assert not env["sync"][name].startswith("feil"), env["sync"]
    assert env["sync"]["truenas"] == "ikke konfigurert"


def test_big_unwatched_movie_is_top_low_risk(env):
    s = _sugg(None, name="Big Movie", kind="delete_title")[0]
    assert s["savings"] == 80 * GB
    assert s["risk"] == "lav"
    assert s["score"] >= 60
    labels = {c["label"] for c in s["components"]}
    assert "Aldri sett" in labels and "Plass" in labels
    rep = _sugg(None, name="Big Movie", kind="replace")[0]
    assert rep["savings"] == 80 * GB - 12 * GB


def test_popular_movie_not_recommended(env):
    s = _sugg(None, name="Popular", kind="delete_title")[0]
    assert s["score"] < 20
    assert s["risk"] == "høy"


def test_new_movie_quarantined(env):
    s = _sugg(None, name="New", kind="delete_title")[0]
    assert any(c["key"] == "recent" and c["points"] == -40 for c in s["components"])
    assert s["risk"] == "høy"


def test_hardlinked_movie_frees_nothing_alone(env):
    s = _sugg(None, name="Hardlinked", kind="delete_title")[0]
    assert s["savings"] == 0
    assert "hardlinker" in s["savings_note"]
    # Plass-poeng regnes av faktisk frigjort plass, så forslaget havner lavt
    space = [c for c in s["components"] if c["key"] == "space" and c["label"] == "Plass"][0]
    assert space["points"] == 0
    big = _sugg(None, name="Big Movie", kind="delete_title")[0]
    assert s["score"] < big["score"] - 30


def test_identical_copy_removes_download_copy(env):
    s = _sugg(None, kind="remove_copy")
    assert len(s) == 1
    with db.conn() as c:
        paths = [r[0] for r in c.execute("SELECT path FROM suggestion_files WHERE suggestion_id=?", (s[0]["id"],))]
    assert paths == ["/mnt/pool1/tmp/Copy.2013.mkv"]
    assert s[0]["savings"] == ms.SIZES[6]


def test_versions_keep_radarr_file(env):
    s = _sugg(None, name="Twin", kind="remove_versions")
    assert len(s) == 1
    with db.conn() as c:
        paths = [r[0] for r in c.execute("SELECT path FROM suggestion_files WHERE suggestion_id=?", (s[0]["id"],))]
    assert paths == ["/mnt/pool1/FILM/Twin (2012)/Twin.2012.2160p.mkv"]
    assert s[0]["savings"] == ms.EXTRA_TWIN[1]
    # Hardlinken er ikke et duplikat
    with db.conn() as c:
        kinds = {r[0]: r[1] for r in c.execute("SELECT kind, reclaimable FROM duplicate_groups")}
    assert kinds["hardlink"] == 0


def test_protection(env):
    with db.conn() as c:
        prot = {r[0]: r[1] for r in c.execute("SELECT name, protect_reason FROM titles WHERE protected=1")}
    assert "Kids Movie" in prot and "Barn" in prot["Kids Movie"]
    assert "Keeper" in prot and "keep" in prot["Keeper"]
    assert not _sugg(None, name="Kids Movie")
    assert not _sugg(None, name="Keeper")


def test_play_fallback_by_name(env):
    with db.conn() as c:
        plays = c.execute("SELECT play_count FROM titles WHERE name='Keeper'").fetchone()[0]
    assert plays == 1  # rating key 999 finnes ikke, men navn+år matcher


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
    # Hardlinken telles bare én gang per bibliotek
    assert libs["tmp"]["alloc"] == ms.SIZES[5] + ms.SIZES[6] + 4 * GB + 99
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
    assert settings.get()["services"]["radarr"]["api_key"] == ms.KEY  # ikke overskrevet med maske
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
    return r


def test_seerr_requests_mapped_and_watched_by_username(env):
    big = _title("Big Movie")
    assert [r["by"] for r in big["requests"]] == ["Bjørn B."] and big["requests"][0]["watched"] is False
    # Anna så Popular: Tautulli viser «Anna» (visningsnavn) / «anna» (brukernavn), Seerr har plexUsername «anna»
    pop = _title("Popular")
    assert pop["requests"][0]["watched"] is True
    # Kids Movie finnes ikke i Radarr – koblet via Plex ratingKey
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
    assert r["Anna"]["titles"] == 2 and r["Anna"]["not_watched_by_requester"] == 1  # Kids Movie ikke sett
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
    assert ms.POSTER_HITS["plex"] == before + 1          # andre gang fra cache
    # Keeper har ingen plakat i Plex -> hentes fra Radarr
    r = client.get(f"/api/poster/{_title('Keeper')['key']}")
    assert r.status_code == 200 and ms.POSTER_HITS["radarr"] >= 1
    # Serie med plakat på serie-elementet i Plex
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
    assert anna["summary"]["unwatched_delete"]["count"] == 0  # beskyttet tas ikke med


def test_find_smaller_movie_versions(client):
    r = client.get(f"/api/releases/{_title('Big Movie')['key']}").json()
    assert r["service"] == "radarr" and r["current_size"] == 80 * GB and r["total"] == 6
    names = [x["title"] for x in r["releases"]]
    assert "Big.Movie.2010.2160p.REMUX" not in names                # ikke mindre
    top = r["releases"][0]
    assert top["title"] == "Big.Movie.2010.1080p.BluRay.x264" and top["recommended"]
    assert any("mindre" in x for x in top["reasons"])
    zero = next(x for x in r["releases"] if x["title"].endswith("WEB.x265"))
    assert not zero["recommended"] and "Ingen delere" in zero["warnings"]
    banned = next(x for x in r["releases"] if "HDTV" in x["title"])
    assert "Release is banned" in banned["warnings"]
    assert not any("preference" in w for x in r["releases"] for w in x["warnings"])  # forventet avvisning skjules
    # Andre gang fra cache – ingen nytt søk mot indekserne
    n = len(ms.RELEASE_CALLS)
    assert client.get(f"/api/releases/{_title('Big Movie')['key']}").json()["cached"] is True
    assert len(ms.RELEASE_CALLS) == n


def test_find_smaller_season_pack(client):
    key = _title("Hot Show")["key"]
    assert client.get(f"/api/releases/{key}").status_code == 400      # sesong må velges
    r = client.get(f"/api/releases/{key}", params={"season": 1}).json()
    assert r["episode_releases"] == 1 and [x["title"] for x in r["releases"]] == ["Hot.Show.S01.1080p.WEB.x265"]
    assert r["episodes"] == 2


def test_downloads_overview(client):
    r = client.get("/api/downloads").json()
    by = {i["name"]: i for i in r["items"]}
    assert by["Hardlinked.2011.mkv"]["status"] == "hardlenket" and by["Hardlinked.2011.mkv"]["freed"] == 0
    assert by["Copy.2013.mkv"]["status"] == "kopiert" and by["Copy.2013.mkv"]["title_name"] == "Copy"
    old = by["Old.Download"]
    assert old["status"] == "ikke_importert" and old["advice"] == "vurder" and old["is_dir"]
    assert r["summary"]["count"] == 3


def test_plex_check(client):
    r = client.get("/api/plex-check").json()
    assert r["available"]
    names = {g["name"]: g for g in r["items"]}
    assert "Orphan" in names and "Disc" in names
    assert "ISO" in names["Disc"]["reason"]
    assert "Kids Movie" not in names and "Big Movie" not in names
    assert not any("tmp" in g["folder"] for g in r["items"])            # nedlastingsmappen tas ikke med
    m = client.get("/api/plex-check", params={"view": "missing"}).json()
    assert [g["name"] for g in m["items"]] == ["Gone"] and m["items"][0]["files"][0]["path"] == "/mnt/pool1/FILM/Gone (1999)/Gone.1999.mkv"
    res = client.post("/api/plex-check/rescan", json={"folder": "/mnt/pool1/FILM/Orphan (2001)"}).json()
    assert res["ok"] and ms.PLEX_REFRESH[-1] == ("1", "/FILM/Orphan (2001)")
    assert client.post("/api/plex-check/rescan", json={"folder": "/mnt/pool1/tmp/x"}).status_code == 400


# ------------------------------------------------------------------ sletting (kjøres sist)

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
    assert not by[ids[1]]["executable"] and "kvalitetsprofil" in by[ids[1]]["reason"]
    assert by[ids[2]]["executable"] and by[ids[2]]["service"] == "sonarr"
    assert not by[ids[3]]["executable"] and "hele serien" in by[ids[3]]["reason"]
    assert p["executable"] == 2 and p["freed"] > 0
    # Endret utvalg -> gammel token avvises
    r = client.post("/api/actions/execute", json={"ids": ids[:1], "token": p["token"]})
    assert r.status_code == 409


def test_protected_never_executable():
    from app import actions
    d = actions._describe({"id": "x", "label": "K", "location": "", "kind": "delete_title", "risk": "lav",
                           "savings": 1, "title_key": "k", "scope": "title"},
                          {"protected": 1, "protect_reason": "Biblioteket Barn er beskyttet", "radarr_id": 9,
                           "sonarr_id": None})
    assert d["executable"] is False and "Barn" in d["reason"]


def test_delete_movie_via_radarr(client, no_refresh):
    _enable(client)
    big = _sid("Big Movie", "delete_title")
    p = client.post("/api/actions/plan", json={"ids": [big]}).json()
    r = client.post("/api/actions/execute", json={"ids": [big], "token": p["token"]}).json()
    assert r["done"] == 1 and r["results"][0]["status"] == "utført"
    assert ("DELETE", "/radarr/api/v3/movie/1", {"deleteFiles": "true", "addImportExclusion": "false"}, None) in ms.WRITES
    assert r["freed_estimate"] == 80 * GB
    assert no_refresh == ["refresh"]
    h = client.get("/api/actions/history").json()["items"]
    assert h[0]["title"] == "Big Movie" and h[0]["status"] == "utført"


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
    assert ms.WRITES.index(put) < ms.WRITES.index(bulk)  # avovervåk før sletting


def test_delete_stops_when_folder_changed(client, no_refresh):
    _enable(client)
    twin = _sid("Twin", "delete_title")
    ms.PATH_OVERRIDE[("movie", 3)] = "/FILM/Noe annet (2012)"
    ms.WRITES.clear()
    p = client.post("/api/actions/plan", json={"ids": [twin]}).json()
    r = client.post("/api/actions/execute", json={"ids": [twin], "token": p["token"]}).json()
    assert r["results"][0]["status"] == "feilet" and "stemmer ikke" in r["results"][0]["detail"]
    assert not [w for w in ms.WRITES if w[0] == "DELETE"]
    assert no_refresh == []
    ms.PATH_OVERRIDE.clear()


# ------------------------------------------------------------------ duplikater (endrer filer på disk – kjøres helt sist)

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
    """Behold den uadministrerte versjonen: Radarr sletter sin fil og skanner mappen på nytt."""
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
    # Appen rørte ikke filene på disk selv
    root = _media_root()
    assert os.path.exists(f"{root}/FILM/Twin (2012)/Twin.2012.1080p.mkv")
    h = client.get("/api/actions/history").json()["items"][0]
    assert h["service"] == "radarr" and h["status"] == "utført"


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
    assert it["executable"] and it["keep"] == "/mnt/pool1/FILM/Copy (2013)/Copy.2013.mkv"
    assert [f["path"] for f in it["files"]] == ["/mnt/pool1/tmp/Copy.2013.mkv"] and it["warn_downloads"]
    assert p["freed"] == ms.SIZES[6]
    root = _media_root()
    assert os.path.exists(f"{root}/tmp/Copy.2013.mkv")
    r = client.post("/api/duplicates/execute", json={"groups": [{"id": g["id"]}], "token": p["token"]}).json()
    assert r["done"] == 1, r
    assert not os.path.exists(f"{root}/tmp/Copy.2013.mkv")
    assert os.path.exists(f"{root}/FILM/Copy (2013)/Copy.2013.mkv")  # beholdt
    assert no_refresh == ["refresh"]
    h = client.get("/api/actions/history").json()["items"][0]
    assert h["service"] == "filsystem" and h["status"] == "utført"


def test_duplicate_delete_refuses_changed_file(client, no_refresh):
    import os
    _enable_files(client)
    g = client.get("/api/duplicates", params={"kind": "versions"}).json()["items"][0]
    p = client.post("/api/duplicates/plan", json={"groups": [{"id": g["id"]}]}).json()
    assert p["items"][0]["executable"]
    extra = f"{_media_root()}/FILM/Twin (2012)/Twin.2012.2160p.mkv"
    os.utime(extra, (1_000_000_000, 1_000_000_000))  # endres etter skanning
    r = client.post("/api/duplicates/execute", json={"groups": [{"id": g["id"]}], "token": p["token"]})
    # Planen bygges på nytt ved utførelse; endringen gjør filen ikke-slettbar -> token avviker eller filen avvises
    if r.status_code == 200:
        assert r.json()["done"] == 0
    else:
        assert r.status_code == 409
    assert os.path.exists(extra)



def test_duplicate_protection_setting(monkeypatch):
    from app import dupes
    lib = {"name": "Barn", "host_path": "/mnt/pool1/Barn", "container_path": "/x", "protected": True}
    s = settings.get()
    s["protection"]["include_duplicates"] = False
    monkeypatch.setattr(settings, "get", lambda: s)
    assert dupes.protection_applies() is False
    # Med beskyttelse av for duplikater stopper ikke beskyttet tittel/bibliotek sjekken
    r = dupes._check_file({"path": "/mnt/pool1/Barn/a.mkv"}, {"size": 1, "mtime": 0, "inode": 1}, set(), False)
    assert r is None or "beskyttet" not in r
    s["protection"]["include_duplicates"] = True
    assert dupes.protection_applies() is True
    r = dupes._check_file({"path": "/mnt/pool1/Barn/a.mkv"}, {"size": 1, "mtime": 0, "inode": 1}, set(), True)
    assert "beskyttet" in r



def test_downloads_delete_folder(client, no_refresh):
    import os
    _enable_files(client)
    path = "/mnt/pool1/tmp/Old.Download"
    p = client.post("/api/downloads/plan", json={"paths": [path, "/mnt/pool1/FILM/Big Movie (2010)"]}).json()
    assert p["count"] == 1 and p["items"][1]["ok"] is False
    r = client.post("/api/downloads/execute", json={"paths": [path, "/mnt/pool1/FILM/Big Movie (2010)"], "token": p["token"]}).json()
    assert r["done"] == 1
    root = _media_root()
    assert not os.path.exists(f"{root}/tmp/Old.Download")
    assert os.path.exists(f"{root}/FILM/Big Movie (2010)")
