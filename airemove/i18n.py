"""Translations, the way LightCraft does them: the text is written in English (the source language) and each other
language is a catalog, locales/<code>.json, that maps an English text to its translation. A missing or empty entry
falls back to the English text, so a half-done translation never breaks anything.

    from i18n import _, _n
    _("Remove selection")                          -> "Rimuovi selezione"
    _("Loading {model}", model="SDXL")             -> placeholders are str.format fields, kept in translations
    _n("{n} variant", "{n} variants", n)           -> the singular or plural text, then translated
    N_("text")                                     -> marks a text defined in a table, translated later with _()
    num(6.8)                                       -> "6,8": a number with the language's decimal separator

The language: AIREMOVE_LANG, else the one picked in AI Remove's window (work/settings.json "language"), else
LightCraft's own (its ui.json), else the system's, else English. Adding a language = a locales/<code>.json catalog
and an entry in LANGUAGES; tools/i18n_check.py lists what a catalog is missing.

Standard library only: the installer and the MCP server use it too.
"""
import json
import locale
import os
import subprocess
import sys
from pathlib import Path

import system

SOURCE = "en"
LANGUAGES = {"en": "English", "it": "Italiano"}  # code: the language's own name (shown in the menu)
LOCALES = Path(__file__).resolve().parent / "locales"
SETTINGS = system.ROOT / "work" / "settings.json"

_lang = None
_catalog = {}


def parse_tag(tag):
    """'it', 'it-IT', 'it_IT.UTF-8', 'Italian_Italy.1252' -> a shipped code, else None."""
    if not tag:
        return None
    t = str(tag).split(".")[0].split("@")[0].replace("_", "-").strip().lower()
    if t in LANGUAGES:
        return t
    base = t.split("-")[0]
    if base in LANGUAGES:
        return base
    names = {"english": "en", "italian": "it", "italiano": "it"}  # Windows' locale names
    return names.get(base)


def system_language():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        code = parse_tag((os.environ.get(var) or "").split(":")[0])
        if code:
            return code
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultUILanguage and \
                    ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                return parse_tag(buf.value)
        except Exception:
            pass
    if sys.platform == "darwin":  # apps started from Finder have no LANG
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                                 timeout=5).stdout
            first = next((ln.strip(' ",()') for ln in out.splitlines() if ln.strip(' ",()')), "")
            if parse_tag(first):
                return parse_tag(first)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        return parse_tag(locale.getlocale()[0])
    except (ValueError, TypeError):
        return None


def app_language():
    """The language LightCraft's interface is in (its ui.json "language"), else Chromaforge's, if one we ship."""
    for host in system.HOSTS:
        try:
            data = json.loads(host.ui_json().read_text(encoding="utf-8-sig"))
            if parse_tag(data.get("language")):
                return parse_tag(data.get("language"))
        except (OSError, ValueError, AttributeError):
            pass
    return None


def chosen_language():
    """The language picked in AI Remove's window ("auto" or absent: follow LightCraft or Chromaforge)."""
    try:
        return parse_tag(json.loads(SETTINGS.read_text(encoding="utf-8-sig")).get("language"))
    except (OSError, ValueError, AttributeError):
        return None


def detect():
    return (parse_tag(os.environ.get("AIREMOVE_LANG")) or chosen_language() or app_language()
            or system_language() or SOURCE)


def set_language(code):
    """Use this language from now on (texts already on screen are not redrawn)."""
    global _lang, _catalog
    _lang = parse_tag(code) or SOURCE
    _catalog = {}
    if _lang != SOURCE:
        try:
            data = json.loads((LOCALES / f"{_lang}.json").read_text(encoding="utf-8"))
            _catalog = {k: v for k, v in data.items() if isinstance(v, str) and v and not k.startswith("@")}
        except (OSError, ValueError) as e:  # a broken catalog degrades to English, never takes the app down
            print(f"i18n: catalog {_lang} unreadable ({e}); using English", file=sys.stderr)
    return _lang


def language():
    if _lang is None:
        set_language(detect())
    return _lang


def _(text, **fields):
    """The text in the current language; {fields} filled in after the lookup."""
    language()
    out = _catalog.get(text, text)
    if fields:
        try:
            return out.format(**fields)
        except (KeyError, IndexError, ValueError):  # a translation with a broken placeholder: the English one
            return text.format(**fields)
    return out


def N_(text):
    """Marks a text for translation where it is defined (a table, a constant); _(it) translates it where shown."""
    return text


def _n(singular, plural, n, **fields):
    """Singular for n == 1, plural otherwise (English and Italian agree on this), translated; n is a field too."""
    return _(singular if n == 1 else plural, n=n, **fields)


DECIMAL = {"it": ","}  # the decimal separator, where it is not a point


def num(x, digits=1):
    """A number written the language's way: 6.8 -> "6,8" in Italian."""
    return f"{round(x, digits):g}".replace(".", DECIMAL.get(language(), "."))
