"""scripts/tour/film.py aliases researchers in every form a name reaches the browser in.
The name here is SYNTHETIC and invented."""

import importlib.util
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tour_names", ROOT / "scripts/tour/names.py")
names = importlib.util.module_from_spec(spec)
spec.loader.exec_module(names)

REAL = "Ysolde Quórum"  # SYNTHETIC: an invented name with an accented letter
ALIAS = {REAL: "PI-9"}


def test_the_alias_swap_matches_escaped_and_normalised_forms_of_a_name():
    nfd = unicodedata.normalize("NFD", REAL)
    body = ('{"name": "Ysolde Quórum", "nfd": "' + nfd + '", "brief": "<h1>Ysolde '
            'Qu&#243;rum</h1>", "hex": "Ysolde Qu&#xf3;rum", "model": "Dr. Qu&#243;rum and '
            'Dr. Quórum agree"}')
    assert "Qu&#243;rum" in body.replace(REAL, "PI-9")  # the plain swap missed it
    out = names.swap_names(body, ALIAS)
    assert "Qu" not in out and "Ysolde" not in out, out
    assert out.count("PI-9") == 6


def test_an_accented_spelling_is_swapped_when_the_csv_is_plain():
    """S52: pi_aliases.csv may spell a name plainly while a source uses an accent."""
    real = "Ysolde Kowarth"  # SYNTHETIC: an invented name
    accented = "Kow\u00e1rth"
    decomposed = unicodedata.normalize("NFD", accented)
    body = f"Ysolde {accented} and Dr. {decomposed} and Kowarth"
    assert names.swap_names(body, {real: "PI-9"}) == "PI-9 and Dr. PI-9 and PI-9"
