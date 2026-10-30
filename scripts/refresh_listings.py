"""Copy opportunity records from one store into another, then index them (S27).

The demo store is never overwritten whole: sessions write public records through to it
(S23), so only `opportunity` rows are copied (insert or replace by id). Private briefs do
not index (S13), so the target's LanceIndex is brought up to date here.

  uv run --extra ml python scripts/refresh_listings.py --from data/perch.db \\
      --to data/demo/perch.db --device cuda
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from perch.embed import get_embedder
from perch.profiles import current
from perch.retrieve import index_opportunities
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository


def copy_opportunities(src: Path, dst: Path) -> int:
    with sqlite3.connect(dst) as con:
        con.execute("ATTACH DATABASE ? AS src", (str(src),))
        n = con.execute("SELECT count(*) FROM src.records WHERE kind = 'opportunity'").fetchone()[0]
        con.execute("INSERT OR REPLACE INTO records SELECT * FROM src.records "
                    "WHERE kind = 'opportunity'")
        con.commit()
        con.execute("DETACH DATABASE src")
    return n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="src", type=Path, required=True)
    ap.add_argument("--to", dest="dst", type=Path, required=True)
    ap.add_argument("--device")
    a = ap.parse_args(argv)
    print(f"copied {copy_opportunities(a.src, a.dst)} opportunity records into {a.dst}")
    root = a.dst.parent
    embedder = get_embedder(current().embedder, cache=root / "cache" / "embeddings.db",
                            device=a.device)
    with SQLiteRepository(a.dst) as repo:
        n = index_opportunities(repo, LanceIndex(root / "lance"), embedder)
    print(f"indexed {n} into {root / 'lance'}")


if __name__ == "__main__":
    main()
