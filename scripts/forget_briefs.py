"""Delete every stored brief, lead and monitoring digest from a store (S23).

Since S23 the app stores nothing about a visitor. Stores from before then still hold the
briefs visitors ran; this removes them and compacts the file, so the old rows are not
left in free pages. Public records (researchers, works, awards, opportunities,
organisations, scholarships) stay.

  uv run python scripts/forget_briefs.py data/demo/perch.db
"""

from __future__ import annotations

import sqlite3
import sys

USER_KINDS = ("brief", "lead", "digest")


def forget(path: str) -> dict[str, int]:
    con = sqlite3.connect(path)
    with con:
        counts = {k: con.execute("SELECT count(*) FROM records WHERE kind = ?", (k,)).fetchone()[0]
                  for k in USER_KINDS}
        con.execute(f"DELETE FROM records WHERE kind IN ({','.join('?' * len(USER_KINDS))})",
                    USER_KINDS)
    con.execute("VACUUM")
    con.close()
    return counts


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p, forget(p))
