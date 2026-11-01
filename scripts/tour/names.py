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


def swap_names(body: str, names: dict[str, str]) -> str:
    """Real display name -> alias, in every form. Model text can name a researcher by
    surname alone ("Dr. ..."), so the surnames go too, as whole words."""
    for real, alias in names.items():
        for f in forms(real):
            body = body.replace(f, alias)
    for real, alias in names.items():
        last = real.split()[-1]
        if len(last) > 2:
            for f in forms(last):
                body = re.sub(rf"(?<!\w){re.escape(f)}(?!\w)", alias, body)
    return body
