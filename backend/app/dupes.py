"""Duplikater: oversikt, filtrering og (valgfri) sletting av overflødige filer.

Overflødige versjoner og kopier administreres normalt IKKE av Radarr/Sonarr, så de kan bare
fjernes direkte i filsystemet. Det krever to bevisste valg:
  1. mappene er montert med skrivetilgang (ikke `:ro`) i appens YAML, og
  2. «Tillat sletting av duplikatfiler» er slått på under Innstillinger.

Harde regler (sjekkes på serveren rett før hver fil slettes):
  * filen tilhører en duplikatgruppe fra siste analyse, og er ikke filen som beholdes
  * filen som beholdes finnes fortsatt, og minst én fil i gruppen blir igjen
  * filen administreres ikke av Radarr/Sonarr (da må den slettes der)
  * tittelen/biblioteket er ikke beskyttet
  * filen er en vanlig fil (ikke symlenke) inne i et konfigurert bibliotek
  * størrelse, mtime og inode er uendret siden skanningen
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from . import db, jobs, settings
from .analysis import engine

KIND_LABEL = {"identical": "Identiske kopier", "versions": "Flere versjoner", "hardlink": "Hardlenker"}


def enabled() -> bool:
    return bool(settings.get().get("actions", {}).get("files_enabled", False))


def _libs():
    return {l["name"]: l for l in settings.get()["libraries"]}


def _container_path(host_path: str) -> tuple[str | None, dict | None]:
    for lib in settings.get()["libraries"]:
        h = lib["host_path"].rstrip("/")
        if host_path.startswith(h + "/"):
            return lib["container_path"].rstrip("/") + host_path[len(h):], lib
    return None, None


def writable_libraries() -> dict[str, bool]:
    out = {}
    for lib in settings.get()["libraries"]:
        p = lib.get("container_path")
        out[lib["name"]] = bool(p and os.path.isdir(p) and os.access(p, os.W_OK))
    return out


def _managed_paths(c) -> set[str]:
    s = {r[0] for r in c.execute("SELECT file_path FROM radarr_movies WHERE file_path IS NOT NULL")}
    s |= {r[0] for r in c.execute("SELECT path FROM sonarr_files WHERE path IS NOT NULL")}
    return s


def _load_groups(c) -> list[dict]:
    groups = db.rows(c, """SELECT g.id, g.kind, g.title_key, g.label, g.total, g.reclaimable, g.files,
                                  t.name AS title_name, t.year, t.kind AS title_kind, t.protected, t.protect_reason
                           FROM duplicate_groups g LEFT JOIN titles t ON t.key = g.title_key""")
    paths = set()
    for g in groups:
        fs = json.loads(g["files"] or "[]")
        g["keep_reason"] = next((x["keep_reason"] for x in fs if "keep_reason" in x), None)
        g["files"] = [x for x in fs if "path" in x]
        paths |= {f["path"] for f in g["files"]}
    info = {}
    plist = list(paths)
    for i in range(0, len(plist), 900):
        chunk = plist[i:i + 900]
        q = ",".join("?" * len(chunk))
        for r in db.rows(c, f"SELECT path, library, size, alloc, mtime, inode, dev, nlink, ext FROM files WHERE path IN ({q})", chunk):
            info[r["path"]] = r
    managed = _managed_paths(c)
    libs = _libs()
    for g in groups:
        for f in g["files"]:
            fi = info.get(f["path"], {})
            f.update({k: fi.get(k) for k in ("library", "alloc", "mtime", "nlink", "ext")})
            f["managed"] = f["path"] in managed
            f["in_downloads"] = libs.get(fi.get("library"), {}).get("kind") == "downloads"
            f["missing"] = not fi
        g["in_downloads"] = any(f["in_downloads"] for f in g["files"])
        g["libraries"] = sorted({f["library"] for f in g["files"] if f.get("library")})
    return groups


def overview(kind: str = "", q: str = "", library: str = "", where: str = "", sort: str = "reclaimable",
             order: str = "desc", limit: int = 200, offset: int = 0) -> dict:
    with db.conn() as c:
        groups = _load_groups(c)
    summary = {}
    for k in KIND_LABEL:
        gs = [g for g in groups if g["kind"] == k]
        summary[k] = {"groups": len(gs), "files": sum(len(g["files"]) for g in gs),
                      "reclaimable": sum(g["reclaimable"] or 0 for g in gs),
                      "in_downloads": sum(1 for g in gs if g["in_downloads"]),
                      "in_downloads_bytes": sum(g["reclaimable"] or 0 for g in gs if g["in_downloads"])}
    items = [g for g in groups if not kind or g["kind"] == kind]
    if q:
        ql = q.lower()
        items = [g for g in items if ql in (g["title_name"] or g["label"] or "").lower()
                 or any(ql in f["path"].lower() for f in g["files"])]
    if library:
        items = [g for g in items if library in g["libraries"]]
    if where == "downloads":
        items = [g for g in items if g["in_downloads"]]
    elif where == "library":
        items = [g for g in items if not g["in_downloads"]]
    keyf = {"reclaimable": lambda g: g["reclaimable"] or 0, "size": lambda g: g["total"] or 0,
            "name": lambda g: (g["title_name"] or g["label"] or "").lower(), "files": lambda g: len(g["files"])}
    items.sort(key=keyf.get(sort, keyf["reclaimable"]), reverse=order != "asc")
    total = len(items)
    page = items[offset:offset + max(1, min(limit, 1000))]
    w = writable_libraries()
    return {"summary": summary, "total": total, "total_reclaimable": sum(g["reclaimable"] or 0 for g in items),
            "items": page, "files_enabled": enabled(), "writable": w}


# ------------------------------------------------------------------ sletting

def _check_file(f: dict, fi: dict | None, managed: set[str], protected: bool) -> str | None:
    """Returnerer grunn til at filen IKKE kan slettes, eller None."""
    if fi is None:
        return "Finnes ikke lenger i skanningen"
    if protected:
        return "Tittelen eller biblioteket er beskyttet"
    if f["path"] in managed:
        return "Administreres av Radarr/Sonarr – slett den der"
    cpath, lib = _container_path(f["path"])
    if not cpath or not lib:
        return "Ligger utenfor bibliotekene"
    if lib.get("protected"):
        return f"Biblioteket {lib['name']} er beskyttet"
    root = os.path.realpath(lib["container_path"])
    if not os.path.realpath(cpath).startswith(root + os.sep):
        return "Peker utenfor biblioteket"
    try:
        st = os.lstat(cpath)
    except FileNotFoundError:
        return "Filen finnes ikke lenger"
    import stat as _stat
    if not _stat.S_ISREG(st.st_mode):
        return "Ikke en vanlig fil"
    if st.st_size != fi["size"] or abs(st.st_mtime - fi["mtime"]) > 1 or st.st_ino != fi["inode"]:
        return "Filen er endret siden skanningen – kjør ny skanning"
    if not os.access(os.path.dirname(cpath), os.W_OK):
        return "Ingen skrivetilgang (mappen er montert :ro)"
    return None


def plan(choices: list[dict]) -> dict:
    """choices: [{"id": gruppe-id, "keep": sti som skal beholdes}]"""
    with db.conn() as c:
        groups = {g["id"]: g for g in _load_groups(c)}
        managed = _managed_paths(c)
        file_rows = {}
        all_paths = [f["path"] for ch in choices for f in groups.get(ch.get("id"), {}).get("files", [])]
        for i in range(0, len(all_paths), 900):
            chunk = all_paths[i:i + 900]
            q = ",".join("?" * len(chunk))
            for r in db.rows(c, f"SELECT path, size, alloc, mtime, inode, dev, nlink FROM files WHERE path IN ({q})", chunk):
                file_rows[r["path"]] = r
        items, claims, h = [], {}, hashlib.sha256()
        for ch in choices[:500]:
            g = groups.get(ch.get("id"))
            if not g:
                items.append({"id": ch.get("id"), "label": "?", "executable": False,
                              "reason": "Gruppen finnes ikke lenger (ny analyse er kjørt)", "files": []})
                continue
            keep = ch.get("keep") or next((f["path"] for f in g["files"] if f.get("keep")), None)
            paths = [f["path"] for f in g["files"]]
            base = {"id": g["id"], "label": g["title_name"] or g["label"], "kind": g["kind"], "keep": keep}
            if g["kind"] == "hardlink":
                items.append({**base, "executable": False, "reason": "Hardlenker tar ikke ekstra plass", "files": []})
                continue
            if keep not in paths:
                items.append({**base, "executable": False, "reason": "Filen som skal beholdes er ikke i gruppen", "files": []})
                continue
            kf = next(f for f in g["files"] if f["path"] == keep)
            keep_c, _ = _container_path(keep)
            if not keep_c or not os.path.isfile(keep_c):
                items.append({**base, "executable": False, "reason": "Filen som skal beholdes finnes ikke på disk", "files": []})
                continue
            to_delete = []
            kr = file_rows.get(keep, {})
            for f in g["files"]:
                fr = file_rows.get(f["path"], {})
                if f["path"] == keep or (fr and fr.get("inode") == kr.get("inode") and fr.get("dev") == kr.get("dev")):
                    continue  # samme fil som den som beholdes (hardlink)
                reason = _check_file(f, file_rows.get(f["path"]), managed, bool(g["protected"]))
                to_delete.append({"path": f["path"], "size": f["size"], "alloc": f.get("alloc"),
                                  "ok": reason is None, "reason": reason, "managed": f["managed"],
                                  "in_downloads": f["in_downloads"]})
            ok = [f for f in to_delete if f["ok"]]
            for f in ok:
                claims[f["path"]] = f["alloc"] or f["size"]
                h.update(f["path"].encode())
            h.update((g["id"] + "|" + keep).encode())
            items.append({**base, "executable": bool(ok), "files": to_delete,
                          "reason": None if ok else (to_delete[0]["reason"] if to_delete else "Ingenting å slette"),
                          "keep_managed": kf.get("managed"), "warn_downloads": any(f["in_downloads"] for f in ok)})
        info = {p: {"dev": r["dev"], "inode": r["inode"], "nlink": r["nlink"]} for p, r in file_rows.items()}
        inode_paths: dict = {}
        for p, r in file_rows.items():
            inode_paths.setdefault((r["dev"], r["inode"]), []).append(p)
        # hardlinker utenfor utvalget: be databasen om alle kjente stier for inodene
        for (dev, ino) in list(inode_paths):
            inode_paths[(dev, ino)] = [x[0] for x in c.execute("SELECT path FROM files WHERE dev=? AND inode=?", (dev, ino))]
        freed, held = engine.freed_bytes(claims, info, inode_paths)
    return {"enabled": enabled(), "writable": writable_libraries(), "items": items,
            "files": len(claims), "freed": freed, "held": held, "token": h.hexdigest()[:24]}


def execute(choices: list[dict], token: str) -> dict:
    if not enabled():
        raise PermissionError("Sletting av duplikatfiler er slått av under Innstillinger")
    p = plan(choices)
    if p["token"] != token:
        raise ValueError("Utvalget eller analysen er endret siden oppsummeringen ble vist. Åpne den på nytt.")
    results, deleted_bytes = [], 0
    with db.conn() as c:
        managed = _managed_paths(c)
        for it in p["items"]:
            for f in it.get("files", []):
                if not f["ok"]:
                    results.append({"path": f["path"], "status": "hoppet over", "detail": f["reason"]})
                    continue
                # Ny kontroll rett før sletting
                fi = db.rows(c, "SELECT path, size, alloc, mtime, inode, dev, nlink FROM files WHERE path=?", (f["path"],))
                reason = _check_file(f, fi[0] if fi else None, managed, False)
                keep_c, _ = _container_path(it["keep"])
                if reason is None and not (keep_c and os.path.isfile(keep_c)):
                    reason = "Filen som skal beholdes finnes ikke lenger"
                if reason:
                    status, detail = "feilet", reason
                else:
                    cpath, _ = _container_path(f["path"])
                    try:
                        os.remove(cpath)
                        status, detail = "utført", f"Slettet (beholdt {os.path.basename(it['keep'])})"
                        deleted_bytes += f["alloc"] or f["size"] or 0
                    except OSError as e:
                        status, detail = "feilet", f"{type(e).__name__}: {e}"
                c.execute("INSERT INTO actions(ts,suggestion_id,title_key,title,action,service,status,detail,bytes) "
                          "VALUES(?,?,?,?,?,?,?,?,?)",
                          (time.time(), it["id"], None, f"{it['label']}: {os.path.basename(f['path'])}",
                           "delete_file", "filsystem", status, detail, (f["alloc"] or f["size"]) if status == "utført" else 0))
                db.audit(c, "delete_file", {"path": f["path"], "keep": it["keep"], "status": status, "detail": detail})
                results.append({"path": f["path"], "status": status, "detail": detail})
    done = sum(r["status"] == "utført" for r in results)
    if done:
        jobs.enqueue("refresh")
    return {"results": results, "done": done, "failed": sum(r["status"] == "feilet" for r in results),
            "freed_estimate": min(deleted_bytes, p["freed"]) if p["freed"] else deleted_bytes}
