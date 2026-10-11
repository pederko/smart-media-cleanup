"""Bilingual messages (English / Norwegian Bokmål).

Messages are created as ``L(en, nb)`` – a small dict with both languages. They can be returned
from the API as-is, nested anywhere in a response, or stored in the database (``store()``
serialises them to JSON text). ``LocalizedJSONResponse`` replaces every such message with the
language of the current request just before the response is sent.

The language comes from the ``X-Lang`` header (set by the web UI), falling back to
``Accept-Language`` and then English.
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from fastapi.responses import JSONResponse

LANGS = ("en", "nb")
DEFAULT = "en"
lang_var: ContextVar[str] = ContextVar("smc_lang", default=DEFAULT)
_PREFIX = '{"en":'


def L(en: str, nb: str) -> dict:
    """A message in both languages."""
    return {"en": en, "nb": nb}


def is_msg(v: Any) -> bool:
    return isinstance(v, dict) and len(v) == 2 and "en" in v and "nb" in v


def store(msg: Any) -> str:
    """Serialise a message (or plain string) for a TEXT column."""
    if is_msg(msg):
        return json.dumps(msg, ensure_ascii=False)
    return msg if isinstance(msg, str) else json.dumps(msg, ensure_ascii=False)


def parse_lang(header: str | None) -> str:
    """Pick a supported language from an X-Lang or Accept-Language header."""
    if not header:
        return DEFAULT
    for part in header.split(","):
        code = part.split(";")[0].strip().lower()
        if code.startswith(("nb", "no", "nn")):
            return "nb"
        if code.startswith("en"):
            return "en"
    return DEFAULT


def text(msg: Any, lang: str | None = None) -> str:
    """One message as plain text in the given (or current) language."""
    lang = lang or lang_var.get()
    if is_msg(msg):
        return msg.get(lang) or msg.get(DEFAULT) or ""
    if isinstance(msg, str) and msg.startswith(_PREFIX):
        try:
            return text(json.loads(msg), lang)
        except ValueError:
            return msg
    return "" if msg is None else str(msg)


def localize(obj: Any, lang: str | None = None) -> Any:
    """Recursively replace bilingual messages (also JSON-encoded ones) with one language."""
    lang = lang or lang_var.get()
    if is_msg(obj):
        return obj.get(lang) or obj.get(DEFAULT)
    if isinstance(obj, dict):
        return {k: localize(v, lang) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [localize(v, lang) for v in obj]
    if isinstance(obj, str) and obj.startswith(_PREFIX):
        try:
            return localize(json.loads(obj), lang)
        except ValueError:
            return obj
    return obj


class LocalizedJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(localize(content))


def join(parts: list, sep: str = "; ") -> dict:
    """Join several messages (or plain strings) into one bilingual message."""
    return L(sep.join(text(p, "en") for p in parts if p), sep.join(text(p, "nb") for p in parts if p))


# ---------------------------------------------------------------- number and date formatting

GB = 1024 ** 3


def num(v: float, lang: str, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    if lang == "nb":
        s = s.replace(",", " ").replace(".", ",")
    return s


def gb(b: float, dec: int = 1) -> dict:
    """«12.5 GB» / «12,5 GB» as a bilingual message fragment."""
    return L(f"{num(b / GB, 'en', dec)} GB", f"{num(b / GB, 'nb', dec)} GB")


def date(ts: float | None) -> dict:
    import time
    if not ts:
        return L("unknown", "ukjent")
    t = time.localtime(ts)
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return L(f"{t.tm_mday} {months[t.tm_mon - 1]} {t.tm_year}", time.strftime("%d.%m.%Y", t))


def _param(v: Any, lang: str) -> Any:
    if is_msg(v) or (isinstance(v, str) and v.startswith(_PREFIX)):
        return text(v, lang)
    return v


def fmt(en: str, nb: str, **params) -> dict:
    """Template message. Parameters may be bilingual themselves (e.g. gb(), date() or stored messages)."""
    return L(en.format(**{k: _param(v, "en") for k, v in params.items()}),
             nb.format(**{k: _param(v, "nb") for k, v in params.items()}))


# ---------------------------------------------------------------- errors with bilingual messages

class AppError(Exception):
    """An error meant for the user. ``msg`` may be bilingual; ``status`` is the HTTP status."""
    status = 400

    def __init__(self, msg):
        super().__init__(text(msg, "en"))
        self.msg = msg


class ActionError(AppError):
    status = 400


class Forbidden(AppError):
    """The action is switched off in the settings."""
    status = 403


class Conflict(AppError):
    """What was confirmed no longer matches the current state – show the summary again."""
    status = 409
