"""Jobbene med ekte fremdriftsrapportering (regresjon: «database is locked» under skanning)."""
import time

from app import db, jobs, settings


def test_scan_job_with_many_files_and_real_progress(tmp_path, monkeypatch):
    root = tmp_path / "Movies"
    for d in range(30):
        folder = root / f"Film {d} (2000)"
        folder.mkdir(parents=True)
        for i in range(100):  # 3000 filer -> fremdrift rapporteres flere ganger midt i skanningen
            (folder / f"f{i}.srt").write_text("x")
    s = settings.get()
    s["libraries"] = [{"name": "Movies", "host_path": "/mnt/tank/media/Movies", "container_path": str(root),
                       "kind": "movies", "protected": False}]
    s["scanner"]["throttle_ms_per_1000"] = 0
    monkeypatch.setattr(settings, "get", lambda: s)
    db.init()
    with db.conn() as c:
        jid = c.execute("INSERT INTO jobs(kind,status,progress,message,started) VALUES('scan','running',0,'',?)",
                        (time.time(),)).lastrowid
    # Progress must be reportable often without locking the database
    monkeypatch.setattr(jobs, "PROGRESS_INTERVAL", 0.0)
    s["scanner"]["throttle_ms_per_1000"] = 400  # skanningen varer et par sekunder
    seen = []
    real = jobs._set_live
    monkeypatch.setattr(jobs, "_set_live", lambda j, p, m: (seen.append((p, m)), real(j, p, m)))

    # Other writers in other threads (API, scheduler) must get in while the scan runs
    import threading
    done, errors, writes = threading.Event(), [], [0]

    def other_writer():
        while not done.is_set():
            try:
                with db.conn() as c:
                    db.kv_set(c, "ping", time.time())
                writes[0] += 1
            except Exception as e:  # pragma: no cover
                errors.append(e)
            time.sleep(0.05)

    t = threading.Thread(target=other_writer)
    t.start()
    try:
        result = jobs._run(jid, "scan")
    finally:
        done.set()
        t.join()
    assert not errors, errors
    assert writes[0] > 5
    assert result["files"] == 3000
    assert len(seen) >= 3 and any("Skanner Movies" in m["nb"] for _, m in seen)
    with db.conn() as c:
        c.execute("DELETE FROM files")
        c.execute("DELETE FROM dirs")


def test_live_progress_overlay():
    jobs._set_live(999, 0.42, "Skanner TV: 5000 oppføringer")
    rows = jobs.overlay([{"id": 999, "status": "running", "progress": 0, "message": "Starter"},
                         {"id": 1, "status": "done", "progress": 1, "message": "Ferdig"}])
    assert rows[0]["progress"] == 0.42 and rows[0]["message"].startswith("Skanner TV")
    assert rows[1]["message"] == "Ferdig"
    jobs._clear_live(999)
