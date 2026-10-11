from app import db, settings, updates


def test_version_compare():
    assert updates.is_newer("0.3.1", "0.3.0")
    assert updates.is_newer("v1.0.0", "0.9.9")
    assert not updates.is_newer("0.3.0", "0.3.0")
    assert not updates.is_newer("0.2.9", "0.3.0")
    assert not updates.is_newer(None, "0.3.0")
    assert updates.is_newer("0.3.1", "0.3.0-edge")  # edge-bygg sammenlignes på grunnversjonen


def test_check_reports_new_release_and_caches(monkeypatch):
    db.init()
    calls = []
    monkeypatch.setattr(updates, "current_version", lambda: "0.3.0")
    monkeypatch.setattr(updates, "_fetch_latest", lambda: calls.append(1) or
                        {"tag": "v0.4.0", "url": "https://example.invalid/r", "notes": "Nytt", "published": None})
    s = updates.check(force=True)
    assert s["available"] and s["latest"] == "0.4.0" and s["current"] == "0.3.0"
    updates.check()  # innenfor 6 timer -> ingen nytt kall
    assert len(calls) == 1


def test_check_fails_quietly(monkeypatch):
    db.init()
    def boom():
        raise OSError("ingen nett")
    monkeypatch.setattr(updates, "_fetch_latest", boom)
    s = updates.check(force=True)
    assert s["ok"] is False  # ingen unntak, appen fortsetter


def test_check_can_be_disabled(monkeypatch):
    db.init()
    s = settings.get()
    s["updates"] = {"check": False}
    monkeypatch.setattr(settings, "get", lambda: s)
    monkeypatch.setattr(updates, "_fetch_latest", lambda: (_ for _ in ()).throw(AssertionError("skal ikke kalles")))
    assert updates.check(force=True)["available"] is False
