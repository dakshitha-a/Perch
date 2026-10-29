"""Light and dark copies of the architecture figure for the README.

docs/architecture/overview.svg draws with `currentColor`, which suits the tracker and
docs pages that set a text colour, but an <img> on GitHub has none, so text would be
black on GitHub's dark theme. This writes overview-light.svg and overview-dark.svg with
fixed colours and a background, for a <picture> element.

  python scripts/tour/arch_variants.py
"""

from pathlib import Path

ARCH = Path(__file__).resolve().parents[2] / "docs/architecture"
THEMES = {
    "light": {"currentColor": "#1f2b2d", "bg": "#ffffff"},
    "dark": {"currentColor": "#e4eae6", "bg": "#0d1117", "#dcefe8": "#1e3a30",
             "#f6ead8": "#3a2e1c", "#1f6f5c": "#74c3a0", "#a15c07": "#e0a24a"},
}


def main() -> None:
    src = (ARCH / "overview.svg").read_text(encoding="utf-8")
    for name, colours in THEMES.items():
        s = src
        for old, new in colours.items():
            if old != "bg":
                s = s.replace(old, new)
        head_end = s.index(">") + 1
        s = s[:head_end] + f'\n  <rect width="100%" height="100%" fill="{colours["bg"]}"/>' \
            + s[head_end:]
        (ARCH / f"overview-{name}.svg").write_text(s, encoding="utf-8")
        print(f"wrote overview-{name}.svg")


if __name__ == "__main__":
    main()
