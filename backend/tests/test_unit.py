import os
import time

from app import db, scanner, settings
from app.analysis.engine import GB, freed_bytes
from app.analysis.linking import res_rank
from app.clients.base import ts


def test_path_mapping_longest_prefix():
    s = {"path_mappings": [{"from": "/Movies", "to": "/mnt/tank/media/Movies"},
                           {"from": "/Movies/4K", "to": "/mnt/tank/media/Movies4K"}]}
    assert settings.map_service_path("/Movies/A (2010)/a.mkv", s) == "/mnt/tank/media/Movies/A (2010)/a.mkv"
    assert settings.map_service_path("/Movies/4K/b.mkv", s) == "/mnt/tank/media/Movies4K/b.mkv"
    assert settings.map_service_path("/MoviesER/c.mkv", s) == "/MoviesER/c.mkv"  # not a partial name match
    assert settings.map_service_path(None, s) is None


def test_ts_parses_arr_dates():
    assert ts("2020-01-01T00:00:00Z") == 1577836800
    assert ts("2020-01-01T00:00:00.1234567Z") == 1577836800
    assert ts("0001-01-01T00:00:00Z") is None
    assert ts(None) is None


def test_res_rank():
    assert res_rank("4k") == 2160
    assert res_rank("2160p") == 2160
    assert res_rank("1080") == 1080
    assert res_rank("sd") == 480
    assert res_rank(None) == 0


def test_backup_rotates():
    db.init()
    for _ in range(3):
        db.backup(keep=2)
        time.sleep(1.05)
    files = sorted((settings.DATA_DIR / "backups").glob("smc-*.sqlite3"))
    assert len(files) == 2
    import sqlite3
    assert sqlite3.connect(files[-1]).execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] > 5


def test_is_extra():
    assert scanner.is_extra("Film (2010)/Featurettes/making of.mkv")
    assert scanner.is_extra("Film (2010)/film-trailer.mkv")
    assert scanner.is_extra("Film (2010)/sample.mkv")
    assert not scanner.is_extra("Film (2010)/Film.2010.1080p.mkv")
    assert not scanner.is_extra("Samplers (2012)/Samplers.2012.mkv")


def _fi(dev, ino, nlink):
    return {"dev": dev, "inode": ino, "nlink": nlink}


def test_freed_bytes_counts_inode_once():
    info = {"/a": _fi(1, 10, 1)}
    # The same file in two suggestions (series + season) -> the largest claim, not the sum
    assert freed_bytes({"/a": 5 * GB}, info, {(1, 10): ["/a"]}) == (5 * GB, 0)


def test_freed_bytes_hardlinks():
    info = {"/lib/a": _fi(1, 10, 2), "/dl/a": _fi(1, 10, 2)}
    paths = {(1, 10): ["/lib/a", "/dl/a"]}
    # Only one of the paths selected -> nothing is freed
    assert freed_bytes({"/lib/a": GB}, info, paths) == (0, GB)
    # Both paths selected -> freed once
    assert freed_bytes({"/lib/a": GB, "/dl/a": GB}, info, paths) == (GB, 0)
    # Unknown hardlink outside the scanned folders (nlink 3, only 2 known) -> held
    info3 = {k: _fi(1, 10, 3) for k in info}
    assert freed_bytes({"/lib/a": GB, "/dl/a": GB}, info3, paths) == (0, GB)


def test_scanner_incremental_and_removal(tmp_path, monkeypatch):
    root = tmp_path / "Movies"
    (root / "A (2010)").mkdir(parents=True)
    (root / "A (2010)" / "a.mkv").write_bytes(b"x" * 1000)
    (root / "B (2011)").mkdir()
    (root / "B (2011)" / "b.mkv").write_bytes(b"y" * 2000)
    s = settings.get()
    s["libraries"] = [{"name": "Movies", "host_path": "/mnt/tank/media/Movies", "container_path": str(root), "kind": "movies"}]
    s["scanner"]["throttle_ms_per_1000"] = 0
    monkeypatch.setattr(settings, "get", lambda: s)
    db.init()
    noop = lambda *a: None  # noqa: E731

    r1 = scanner.scan(noop, full=False)
    assert r1["files"] == 2 and r1["stat_calls"] == 2
    # Ingen endring -> ingen stat av filer
    r2 = scanner.scan(noop, full=False)
    assert r2["files"] == 2 and r2["stat_calls"] == 0
    # Ny fil + slettet fil oppdages
    time.sleep(0.01)
    os.remove(root / "B (2011)" / "b.mkv")
    (root / "A (2010)" / "a.srt").write_text("sub")
    r3 = scanner.scan(noop, full=False)
    assert r3["files"] == 2
    with db.conn() as c:
        paths = {r[0] for r in c.execute("SELECT path FROM files")}
    assert paths == {"/mnt/tank/media/Movies/A (2010)/a.mkv", "/mnt/tank/media/Movies/A (2010)/a.srt"}
    # Full skanning stat'er alt
    r4 = scanner.scan(noop, full=True)
    assert r4["stat_calls"] == 2
    with db.conn() as c:
        c.execute("DELETE FROM files")
        c.execute("DELETE FROM dirs")


def test_guess_library_kind():
    from app.settings import guess_kind
    assert [guess_kind(n) for n in ("Movies", "FILM", "TV", "Series", "Downloads", "tmp", "Kids", "Anime")] == \
        ["movies", "movies", "series", "series", "downloads", "downloads", "mixed", "series"]


def test_detect_libraries_from_mounts(tmp_path, monkeypatch):
    from app import settings
    for n in ("Movies", "TV", "downloads", ".hidden"):
        (tmp_path / n).mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(settings, "_mounts", lambda: {str(tmp_path / "Movies"): ("/media/Movies", "zfs", "tank")})
    libs = {l["name"]: l for l in settings.detect_libraries()}
    assert set(libs) == {"Movies", "TV", "downloads"}
    assert libs["Movies"]["host_path"] == "/mnt/tank/media/Movies" and libs["Movies"]["kind"] == "movies"
    assert libs["TV"]["host_path"] == str(tmp_path / "TV")          # not a zfs bind mount: container path
    assert libs["downloads"]["kind"] == "downloads"


def test_i18n_helpers():
    from app.i18n import L, fmt, gb, localize, parse_lang, store, text
    m = fmt("{s} can be freed", "{s} kan frigjøres", s=gb(1.5 * 1024 ** 3))
    assert m == {"en": "1.5 GB can be freed", "nb": "1,5 GB kan frigjøres"}
    stored = store(L("Hello", "Hei"))
    assert text(stored, "nb") == "Hei" and localize({"a": [stored]}, "en") == {"a": ["Hello"]}
    assert fmt("Protected: {r}", "Beskyttet: {r}", r=stored)["en"] == "Protected: Hello"
    assert parse_lang("nn-NO,en;q=0.5") == "nb" and parse_lang("de-DE") == "en" and parse_lang(None) == "en"
