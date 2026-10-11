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
    assert o["counts"]["movies"] == 8 and o["counts"]["series"] == 2 and o["counts"]["episodes"] == 6
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
