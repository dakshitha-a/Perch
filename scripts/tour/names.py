"""The alias swap film.py applies to API responses, kept free of Playwright so it can be
tested. A name may arrive as typed, in NFC or NFD form, or HTML-escaped (GET /private/brief
writes "&#243;" for an accented letter), so every form of each name is swapped."""

from __future__ import annotations

import html
import re
import unicodedata


def forms(name: str) -> list[str]:
    """The name in NFC and NFD, each as typed, HTML-escaped, and with every non-ASCII
    letter as a decimal and as a hex character reference. Longest first."""
    out = set()
    for f in {unicodedata.normalize("NFC", name), unicodedata.normalize("NFD", name)}:
        out |= {f, html.escape(f), html.escape(f, quote=False)}
        out.add("".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in html.escape(f)))
        out.add("".join(c if ord(c) < 128 else f"&#x{ord(c):x};" for c in html.escape(f)))
    return sorted(out, key=len, reverse=True)


# Each base letter and every Latin letter that decomposes to it ("o" -> "oóòöô..."), so a name
# written plainly in pi_aliases.csv also matches the accented spelling a source uses (S52).
_VARIANTS: dict[str, str] = {}
for _cp in range(0xC0, 0x250):
    _ch = chr(_cp)
    _base = unicodedata.normalize("NFKD", _ch)[:1]
    if _base.isascii() and _base.isalpha():
        _VARIANTS[_base] = _VARIANTS.get(_base, _base) + _ch


def _loose(name: str) -> str:
    """A regex for `name` in which each letter also matches its accented forms, whether
    precomposed or followed by combining marks."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    parts = []
    for c in plain:
        if c.isalpha():
            parts.append("[" + re.escape(_VARIANTS.get(c, c)) + "]" + "[\u0300-\u036f]*")
        else:
            parts.append(re.escape(c))
    return "".join(parts)


def swap_names(body: str, names: dict[str, str]) -> str:
    """Real display name -> alias, in every form. Model text can name a researcher by
    surname alone ("Dr. ..."), so the surnames go too, as whole words."""
    for real, alias in names.items():
        for f in forms(real):
            body = body.replace(f, alias)
        body = re.sub(rf"(?<!\w){_loose(real)}(?!\w)", alias, body)
    for real, alias in names.items():
        last = real.split()[-1]
        if len(last) > 2:
            for f in forms(last):
                body = re.sub(rf"(?<!\w){re.escape(f)}(?!\w)", alias, body)
            body = re.sub(rf"(?<!\w){_loose(last)}(?!\w)", alias, body)
    return body
