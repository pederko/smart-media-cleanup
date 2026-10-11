import os
import time

from app import db, scanner, settings
from app.analysis.engine import GB, freed_bytes
from app.analysis.linking import res_rank
from app.clients.base import ts


def test_path_mapping_longest_prefix():
    s = {"path_mappings": [{"from": "/FILM", "to": "/mnt/pool1/FILM"},
                           {"from": "/FILM/4K", "to": "/mnt/pool1/FILM4K"}]}
    assert settings.map_service_path("/FILM/A (2010)/a.mkv", s) == "/mnt/pool1/FILM/A (2010)/a.mkv"
    assert settings.map_service_path("/FILM/4K/b.mkv", s) == "/mnt/pool1/FILM4K/b.mkv"
    assert settings.map_service_path("/FILMER/c.mkv", s) == "/FILMER/c.mkv"  # ikke delvis navnetreff
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
    # Samme fil i to forslag (serie + sesong) -> maks krav, ikke summen
    assert freed_bytes({"/a": 5 * GB}, info, {(1, 10): ["/a"]}) == (5 * GB, 0)


def test_freed_bytes_hardlinks():
    info = {"/lib/a": _fi(1, 10, 2), "/dl/a": _fi(1, 10, 2)}
    paths = {(1, 10): ["/lib/a", "/dl/a"]}
    # Bare den ene stien valgt -> ingenting frigjøres
    assert freed_bytes({"/lib/a": GB}, info, paths) == (0, GB)
    # Begge stier valgt -> frigjøres én gang
    assert freed_bytes({"/lib/a": GB, "/dl/a": GB}, info, paths) == (GB, 0)
    # Ukjent hardlink utenfor skannede mapper (nlink 3, bare 2 kjente) -> holdes
    info3 = {k: _fi(1, 10, 3) for k in info}
    assert freed_bytes({"/lib/a": GB, "/dl/a": GB}, info3, paths) == (0, GB)


def test_scanner_incremental_and_removal(tmp_path, monkeypatch):
    root = tmp_path / "FILM"
    (root / "A (2010)").mkdir(parents=True)
    (root / "A (2010)" / "a.mkv").write_bytes(b"x" * 1000)
    (root / "B (2011)").mkdir()
    (root / "B (2011)" / "b.mkv").write_bytes(b"y" * 2000)
    s = settings.get()
    s["libraries"] = [{"name": "FILM", "host_path": "/mnt/pool1/FILM", "container_path": str(root), "kind": "movies"}]
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
    assert paths == {"/mnt/pool1/FILM/A (2010)/a.mkv", "/mnt/pool1/FILM/A (2010)/a.srt"}
    # Full skanning stat'er alt
    r4 = scanner.scan(noop, full=True)
    assert r4["stat_calls"] == 2
    with db.conn() as c:
        c.execute("DELETE FROM files")
        c.execute("DELETE FROM dirs")
