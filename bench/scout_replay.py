"""Offline replay of stored Scout drafts (S49 Q0): re-grade every draft with today's rules.

No model call, no grounder, no spend. Each draft in a bench run's drafts.jsonl is graded again
by perch/scout/answer.py, and the removals are counted by reason. A draft's `seen` (the records
its tools returned) is rebuilt with no model: the brief the bench gave the question is read with
read_brief, and every id the question's drafts cite is resolved the way a tool would return it
(store records by id; the SYNTHETIC persona's CV parts and entries; the empty saved list).
Runs written before S49 store no tool log, so their replay is approximate: an id that a tool
returned but no draft cites is not in `seen`. From S49 the bench writes each turn's `read` ids
and tool `steps`, and the replay uses them when they are there.

Run: python -m bench.scout_replay bench/results/scout_open_s45g --records DIR
DIR holds opportunity.jsonl and scholarship.jsonl (one record per line, as the store keeps them);
without --records the records come from the local store.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from bench.scout_open import QUESTIONS, persona, shortlist
from perch.schemas import Opportunity, Record, Scholarship
from perch.scout import answer as ans
from perch.scout.read_tools import ReadTools, ScoutData, ToolError

KINDS: dict[str, type[Record]] = {"opportunity": Opportunity, "scholarship": Scholarship}


class MemRepo:
    """Read-only records by id, enough for read_brief and record lookups."""

    def __init__(self, records: list[Record]) -> None:
        self.by_id = {r.id: r for r in records}

    def get_any(self, id: str) -> Record | None:  # noqa: A002 - the Repository signature
        return self.by_id.get(id)

    def get(self, cls: type[Record], id: str) -> Record | None:  # noqa: A002
        r = self.by_id.get(id)
        return r if isinstance(r, cls) else None

    def list(self, cls: type[Record], **_: object) -> list[Record]:
        return [r for r in self.by_id.values() if isinstance(r, cls)]


class _Service:  # the one method bench.scout_open.shortlist calls
    def __init__(self, repo: MemRepo) -> None:
        self._repo = repo

    def repo(self) -> nullcontext[MemRepo]:
        return nullcontext(self._repo)


def load_records(folder: Path) -> list[Record]:
    out: list[Record] = []
    for kind, cls in KINDS.items():
        p = folder / f"{kind}.jsonl"
        if p.is_file():
            out += [cls.model_validate(json.loads(x)) for x in p.read_text().splitlines() if x]
    return out


def store_records() -> list[Record]:
    from perch.service import BriefService, Clients, default_models

    svc = BriefService("data/perch.db", default_models(True, Path("data")), Clients())
    with svc.repo() as r:
        return [*r.list(Opportunity), *r.list(Scholarship)]


def cited(text: str) -> list[str]:
    return list(dict.fromkeys(x.strip() for c in ans.CITE_RE.findall(text) for x in c.split(",")
                              if x.strip()))


def rebuild(tools: ReadTools, ids: list[str]) -> None:
    """Call the tools that would have returned each id."""
    for i in ids:
        try:
            if i.startswith("user:cv"):
                part = i.removeprefix("user:cv").lstrip(":") or None
                tools.read_cv_part(part)
            elif i.startswith("user:entr"):
                tools.read_entries()
            elif i == "user:saved":
                tools.read_saved()
            elif not i.startswith(("user:", "search:")):
                if (rec := tools._get(i)) is not None:
                    tools._see(rec)
        except ToolError:
            continue


@dataclass
class Tally:
    drafts: int = 0
    removed_rows: int = 0
    removed_sentences: int = 0
    drafts_with_removals: int = 0
    reasons: Counter = field(default_factory=Counter)
    questions: dict[str, dict[str, Any]] = field(default_factory=dict)
    stored_rows: int = 0
    mismatched_drafts: int = 0
    detail: list[dict[str, Any]] = field(default_factory=list)  # each removed sentence


def replay(run_dir: Path, records: list[Record], as_of: date | None = None) -> Tally:
    qs = {q["id"]: q for q in yaml.safe_load(QUESTIONS.read_text())["questions"]}
    rows = [json.loads(x) for x in (run_dir / "drafts.jsonl").read_text().splitlines() if x]
    repo = MemRepo(records)
    svc = _Service(repo)
    names = ans.name_index(records)
    as_of = as_of or date(2026, 11, 4)  # the s45g run date
    by_q: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_q.setdefault(r["id"], []).append(r)
    t = Tally()
    for qid, drafts in by_q.items():
        q = qs[qid]
        cv, entries = persona(q.get("persona"))
        b, leads = shortlist(svc, q["audience"], as_of)  # type: ignore[arg-type]
        data = ScoutData(repo=svc.repo, audience=q["audience"], as_of=as_of, signed_in=True,
                         brief=lambda b=b, leads=leads: (b, leads), cv_text=lambda cv=cv: cv,
                         entries=lambda e=entries: e, saved=list)
        tools = ReadTools(data)
        tools.read_brief()
        ids = [i for d in drafts for i in (d.get("read") or cited(d["draft"]))]
        rebuild(tools, list(dict.fromkeys(ids)))
        res = {"set": q["set"], "audience": q["audience"], "attempts": []}
        for d in sorted(drafts, key=lambda d: d["attempt"]):
            g = ans.grade(d["draft"], tools.seen, names, as_of, None, tools)
            rem = g.removed()
            t.drafts += 1
            t.removed_rows += len(rem)
            t.stored_rows += len(d["removed"])
            t.mismatched_drafts += len(rem) != len(d["removed"])
            t.removed_sentences += g.n_removed
            t.drafts_with_removals += bool(rem)
            t.reasons.update(r["reason"] for r in rem)
            t.detail += [{"id": qid, "attempt": d["attempt"], "kind": s.kind,
                          "reasons": [c for c, _ in s.reasons], "text": s.text}
                         for s in g.sentences + g.general_sentences if s.errors]
            res["attempts"].append({"attempt": d["attempt"], "removed": g.n_removed,
                                    "ok": g.ok, "stored": len(d["removed"])})
        t.questions[qid] = res
    return t


def summary(t: Tally) -> dict[str, Any]:
    inq = {k: v for k, v in t.questions.items() if v["set"] == "in" and v["attempts"]}
    first_ok = sum(v["attempts"][0]["ok"] for v in inq.values())
    any_ok = sum(any(a["ok"] for a in v["attempts"]) for v in inq.values())
    from bench.scout_guard import leaks

    return {"drafts": t.drafts, "removed_rows": t.removed_rows,
            "removed_sentences": t.removed_sentences,
            "drafts_with_removals": t.drafts_with_removals,
            "stored_rows": t.stored_rows, "drafts_differing_from_stored": t.mismatched_drafts,
            "in_scope_answers": len(inq), "in_scope_first_draft_clean": first_ok,
            "in_scope_clean_by_second_draft": any_ok,
            "guard_leaks": len(leaks()), "reasons": dict(t.reasons.most_common())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", help="a bench/results/scout_open_<tag> folder")
    ap.add_argument("--records", default=None, help="folder with opportunity.jsonl and "
                    "scholarship.jsonl; default the local store")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD; default 2026-11-04")
    ap.add_argument("--out", default=None, help="write the summary JSON here")
    ap.add_argument("--detail", default=None, help="write each removed sentence here (JSONL); "
                    "it holds draft text, so keep it out of the repo")
    a = ap.parse_args()
    recs = load_records(Path(a.records)) if a.records else store_records()
    t = replay(Path(a.run_dir), recs, date.fromisoformat(a.as_of) if a.as_of else None)
    s = summary(t)
    text = json.dumps(s, indent=2)
    print(text)
    if a.out:
        Path(a.out).write_text(text + "\n")
    if a.detail:
        Path(a.detail).write_text("".join(json.dumps(x) + "\n" for x in t.detail))


if __name__ == "__main__":
    main()
