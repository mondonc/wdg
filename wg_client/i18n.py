"""
Internationalization for the WDG client.

Uses the standard `gettext` module. Translation files live under
``<this_package>/locales/<lang>/LC_MESSAGES/wdg.mo`` and are compiled from
``.po`` sources (see ``locales/README.md`` for the maintainer workflow).

Language selection, in order of precedence:
    1. ``WDG_LANG`` environment variable (e.g. ``fr``, ``en``)
    2. standard gettext env vars (``LC_ALL``, ``LC_MESSAGES``, ``LANG``)
    3. fallback: untranslated source strings (English)
"""

import gettext
import os
from pathlib import Path

DOMAIN = "wdg"
LOCALE_DIR = Path(__file__).parent / "locales"


def _build_translation() -> gettext.NullTranslations:
    override = os.environ.get("WDG_LANG")
    languages = [override] if override else None
    try:
        return gettext.translation(DOMAIN, LOCALE_DIR, languages=languages)
    except FileNotFoundError:
        # No .mo matches the requested/detected language: fall back to source.
        return gettext.NullTranslations()


_translation = _build_translation()
_ = _translation.gettext
