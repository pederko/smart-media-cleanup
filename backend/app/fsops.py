"""Shared helpers for the (optional) direct file deletion features.

Direct deletion on disk is used for duplicates, downloads and folders that no service knows about.
It needs two deliberate choices by the user:
  1. the library folders are mounted read-write (no `:ro`) in the app's compose file, and
  2. «Allow deleting files» is switched on under Settings → Deletion.
"""
from __future__ import annotations

import os
import stat as _stat

from . import settings
from .i18n import L, fmt

VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".m2ts", ".iso", ".wmv", ".mov", ".mpg", ".mpeg", ".webm"}


def files_enabled() -> bool:
    return bool(settings.get().get("actions", {}).get("files_enabled", False))


def container_path(host_path: str) -> tuple[str | None, dict | None]:
    """Host path (as on the NAS) -> path inside this container, and the library it belongs to."""
    for lib in settings.get()["libraries"]:
        h = lib["host_path"].rstrip("/")
        if host_path == h or host_path.startswith(h + "/"):
            return lib["container_path"].rstrip("/") + host_path[len(h):], lib
    return None, None


def writable_libraries() -> dict[str, bool]:
    out = {}
    for lib in settings.get()["libraries"]:
        p = lib.get("container_path")
        out[lib["name"]] = bool(p and os.path.isdir(p) and os.access(p, os.W_OK))
    return out


def managed_paths(c) -> set[str]:
    """Every file path Radarr or Sonarr knows about."""
    s = {r[0] for r in c.execute("SELECT file_path FROM radarr_movies WHERE file_path IS NOT NULL")}
    s |= {r[0] for r in c.execute("SELECT path FROM sonarr_files WHERE path IS NOT NULL")}
    return s


def check_entry(host_path: str, *, top_level_of: str | None = None) -> tuple[str | None, dict | None, dict | None]:
    """Common checks before deleting a file or folder on disk.

    Returns (container_path, library, reason). ``reason`` is a bilingual message when the entry
    must NOT be deleted: outside the libraries, the library root itself, a symlink, gone, or the
    folder is read-only. With ``top_level_of="downloads"`` only entries directly under a downloads
    library are accepted.
    """
    cpath, lib = container_path(host_path)
    if not cpath or not lib:
        return None, None, L("Outside the configured libraries", "Ligger utenfor bibliotekene")
    if top_level_of == "downloads":
        h = lib["host_path"].rstrip("/")
        if lib.get("kind") != "downloads" or "/" in host_path[len(h) + 1:]:
            return None, None, L("Only entries directly under the downloads folder can be deleted here",
                                 "Bare oppføringer rett under nedlastingsmappen kan slettes her")
    root = os.path.realpath(lib["container_path"])
    real = os.path.realpath(cpath)
    if real == root or not real.startswith(root + os.sep):
        return None, None, L("Points outside the library", "Peker utenfor biblioteket")
    try:
        st = os.lstat(cpath)
    except FileNotFoundError:
        return None, None, L("No longer exists", "Finnes ikke lenger")
    if _stat.S_ISLNK(st.st_mode):
        return None, None, L("Is a symbolic link", "Er en symbolsk lenke")
    if not os.access(os.path.dirname(cpath), os.W_OK):
        return None, None, read_only(lib)
    return cpath, lib, None


def read_only(lib: dict | None) -> dict:
    name = lib["name"] if lib else "?"
    return fmt("No write access – {lib} is mounted read-only (:ro)", "Ingen skrivetilgang – {lib} er montert skrivebeskyttet (:ro)",
               lib=name)
