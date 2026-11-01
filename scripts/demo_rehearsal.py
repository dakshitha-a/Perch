"""Rehearse the Demo Day Scout flow against a running server and check each answer by rule
(QA round 3, T29).

Researcher flow, each run in a fresh session: build the warm PI-4 brief (A5026494099), keep
the top two grant leads, then ask the three demo questions in order:
  1. "What are my top three leads and why?"  passes when the answer names the brief's first
     three grant leads in Match order, each in its own sentence or line with a reason, and
     does not refuse or apologise. Each reason ends as a whole sentence, never on a word
     such as "of." or "with." (F2), and speaks to the researcher, never of "the
     researcher" (F12).
  2. "Which of these close before March?"    passes when a search tool ran with closes_by
     after today and no later than the next 1 March, and the answer cites only leads that
     close before that March (a lead cited as accepting proposals anytime is allowed), or
     says none do when that is true of the brief's records. No apology. Every record it
     cites is one of the brief's grant leads: "these" are the brief's leads (QA round 4, F1).
  3. "Draft the hand-off for my top lead"    passes when draft_handoff ran and the draft is
     about the top lead alone.
Documents flow (QA round 4, F7), each run in a fresh session: add the SYNTHETIC persona-1
CV, aims and manuscript with no OpenAlex id, build, keep the top lead, and ask "Draft the
hand-off for my top lead". It passes when draft_handoff drafted the top lead alone, the
opening was written by code (the session holds documents and no public papers), and the
draft holds no empty or placeholder citation ("[]", "No papers provided") and no word of
substance that is in neither the documents, the lead's record nor Perch's own templates.
Every answer to questions 1 and 2 and the student question also passes a citation check
(QA round 5, G7): a line that cites one record shares a word with its title, and a line
that names a short name in parentheses, such as "(Parent F33)", cites that record.
Student flow, each run in a fresh session: build the SYNTHETIC persona-ug brief and ask
"Which of these can I apply to before March?". It passes when a search tool ran, the
answer was not withheld, and any sample scholarship sits under its own heading.

Each flow runs three times by default; the script prints pass counts per question and
writes the answers to build/rehearsal/. Researchers are named by alias in everything it
prints or writes. It never turns Cloud on: every session stays on local models.

  uv run python scripts/demo_rehearsal.py [--base http://127.0.0.1:8091] [--runs 3]
      [--only researcher student documents] [--kept top2|none|weak2]

--kept varies what is kept before the questions (the demo keeps the top two); the model
runs at temperature 0, so repeated runs of one conversation agree, and varying the kept
leads is the better test of a fix.

Exit code 1 unless every run of every question passes.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = "A5026494099"  # PI-4, the demo researcher
PERSONA = ROOT / "data/synthetic/persona-ug"
DOCS = ROOT / "data/synthetic/persona-1"
DOC_FILES = {"cv": "cv.md", "proposal": "specific_aims_draft.md",
             "manuscript": "unpublished_manuscript.md"}
DOCS_Q = "Draft the hand-off for my top lead"
QUESTIONS = ("What are my top three leads and why?", "Which of these close before March?",
             "Draft the hand-off for my top lead")
STUDENT_Q = "Which of these can I apply to before March?"
SEARCH_TOOLS = ("search_opportunities", "search_options")
CITE = re.compile(r"\[([^\[\]]+)\]")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
REFUSAL = re.compile(r"\b(apolog\w*|sorry|cannot|can't|can not|unable|not able|do not have "
                     r"access|don't have access)\b", re.I)
REASON = re.compile(r"\b(fit\w*|match\w*|align\w*|relat\w*|because|since|support\w*|focus\w*|"
                    r"your|you|research|papers?|work)\b", re.I)
NO_DEADLINE = re.compile(r"\b(anytime|any time|no fixed|no set|no deadline|no close date|"
                         r"not close before|do not close|does not close|don't close|placeholder|"
                         r"rolling)\b", re.I)
# F2: a reason that stops on a word that needs a noun after it ("...the aims of.").
DANGLING = {"of", "in", "with", "by", "for", "to", "the", "a", "an", "and", "or", "at", "on",
            "from", "as", "than", "that", "which", "into", "about", "under", "its", "their"}
THIRD = re.compile(r"\bthe researcher\b|\bthe researcher['’]s\b", re.I)  # F12
NONE_CLOSE = re.compile(r"\b(none|no lead|no leads|no grant|nothing|not any)\b", re.I)


def aliases() -> dict[str, str]:
    """Real display name -> alias, as scripts/tour/film.py and scripts/ux_walk.py use."""
    ids = {}
    with (ROOT / "data/overrides/pi_aliases.csv").open() as f:
        for r in csv.DictReader(f):
            ids[f"https://openalex.org/{r['openalex_id']}"] = r["alias"]
    out = {}
    for db in (ROOT / "build/devdemo/perch.db", ROOT / "data/demo/perch.db",
               ROOT / "data/perch.db"):
        if db.is_file():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for i, data in con.execute("SELECT id, data FROM records WHERE kind='researcher'"):
                if i in ids:
                    out[json.loads(data)["display_name"]] = ids[i]
            con.close()
    return out


NAMES = aliases()


def alias(text: str) -> str:
    for real, a in NAMES.items():
        text = text.replace(real, a)
    return text


def short(i: str) -> str:
    return i.strip().removeprefix("grants_gov:")


def cited(text: str) -> list[str]:
    out = []
    for g in CITE.findall(text):
        out += [short(x) for x in re.split(r"[,;]", g) if x.strip()]
    return list(dict.fromkeys(out))


def next_march(as_of: date) -> date:
    return date(as_of.year + (as_of.month >= 3), 3, 1)


class Client:
    def __init__(self, base: str) -> None:
        self.c = httpx.Client(base_url=base, timeout=180)
        self.h = {"X-Perch-Private": self.c.post("/private/session").json()["token"]}

    def get(self, path: str) -> dict:
        r = self.c.get(path, headers=self.h)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict | None = None) -> dict:
        r = self.c.post(path, headers=self.h, json=body or {})
        r.raise_for_status()
        return r.json() if r.content else {}

    def wait_brief(self, limit: float = 300) -> dict:
        t0 = time.time()
        while time.time() - t0 < limit:
            g = self.get("/private/brief")
            if g["brief"]["status"] in ("done", "failed"):
                return g
            time.sleep(2)
        raise TimeoutError("the brief did not finish")

    def ask(self, sid: str | None, question: str) -> tuple[str, dict, float]:
        t0 = time.time()
        v = (self.post("/private/scout", {"question": question}) if sid is None
             else self.post(f"/private/scout/{sid}/ask", {"question": question}))
        sid = v["id"]
        while v["busy"] or v["status"] == "running":
            time.sleep(1)
            v = self.get(f"/private/scout/{sid}")
            if time.time() - t0 > 300:
                raise TimeoutError("Scout did not finish")
        return sid, v["exchanges"][-1], time.time() - t0

    def end(self) -> None:
        try:
            self.post("/private/end")
        finally:
            self.c.close()


def check_top_three(ex: dict, top: list[str]) -> list[str]:
    a = ex.get("answer") or ""
    if not a:
        return [f"no answer ({ex.get('status')}; {'; '.join(ex.get('errors') or [])})"]
    errs = []
    if REFUSAL.search(a):
        errs.append("refuses or apologises")
    if THIRD.search(a):
        errs.append("speaks of the researcher in the third person: "
                    + repr(THIRD.search(a).group(0)))
    ids = [i for i in cited(a) if i in top or re.match(r"^[A-Z0-9-]+$", i)]
    grants = [i for i in ids if not i.startswith("W")]
    if grants[:3] != top:
        errs.append(f"names {grants[:3]}, not {top} in Match order")
    units = [u for u in SENTENCE.split(a) if u.strip()]
    for t in top:
        mine = [u for u in units if t in cited(u)]
        if not mine:
            continue
        own = [u for u in mine if not any(o in cited(u) for o in top if o != t)]
        if not own:
            errs.append(f"{t} shares its only sentence with another lead, so no reason of its own")
        elif not any(REASON.search(CITE.sub(" ", u)) and len(CITE.sub(" ", u).split()) >= 6
                     for u in own):
            errs.append(f"{t} has no reason")
        for u in mine:
            words = re.findall(r"[A-Za-z']+", CITE.sub(" ", u))
            if words and words[-1].lower() in DANGLING:
                errs.append(f"{t}'s reason does not end as a sentence: "
                            f"...{' '.join(words[-4:])}.")
    return errs


def check_before_march(ex: dict, as_of: date, closes: dict[str, date | None]) -> list[str]:
    """closes: each brief lead's real close date, None for none or a placeholder."""
    march = next_march(as_of)
    errs = []
    searched = [c for c in ex["cards"] if c["tool"] in SEARCH_TOOLS and c["status"] == "done"]
    good = False
    for c in searched:
        by = c["arguments"].get("closes_by")
        try:
            good |= bool(by) and as_of < date.fromisoformat(by) <= march
        except ValueError:
            pass
    if not good:
        errs.append("no search with closes_by after today and by the next March: "
                    + json.dumps([c["arguments"] for c in searched]))
    a = ex.get("answer") or ""
    if not a:
        return [*errs, f"no answer ({ex.get('status')}; {'; '.join(ex.get('errors') or [])})"]
    if REFUSAL.search(a):
        errs.append("refuses or apologises")
    before = {i for i, d in closes.items() if d and as_of < d < march}
    named_before = set()
    for u in (u for u in SENTENCE.split(a) if u.strip()):
        for i in cited(u):
            if i.startswith("W"):
                continue
            if i in before:
                named_before.add(i)
            elif i not in closes:  # F1: "these" are the brief's leads
                errs.append(f"cites {i}, which is not one of the brief's leads")
            elif not NO_DEADLINE.search(u):
                errs.append(f"cites {i}, which does not close before {march.isoformat()}, "
                            "as if it did")
    if before and not named_before:
        errs.append(f"names none of {sorted(before)}, which close before {march.isoformat()}")
    if not before and not NONE_CLOSE.search(a):
        errs.append("does not say that none close before March")
    return errs


# G7 (QA round 5): "...Senior Fellowship (Parent F33): ... [PA-25-422]", the F31's id. A
# sentence or list line that cites one record names that record: it shares a word with
# its title.
TITLE_STOP = {"with", "from", "that", "this", "your", "program", "programs", "research",
              "award", "awards", "grant", "grants", "fellowship", "fellowships", "national",
              "opportunity", "funding", "scholarship", "scholarships", "sample", "clinical",
              "trial", "required", "allowed", "optional", "individual", "service"}


def check_own_titles(ex: dict, titles: dict[str, str]) -> list[str]:
    errs = []
    owners: dict[str, set[str]] = {}  # a short name in parentheses, and the titles with it
    for i, t in titles.items():
        for n in re.findall(r"\(([^()]{2,40})\)", t):
            owners.setdefault(n.lower(), set()).add(i)
    for u in (x for x in SENTENCE.split(ex.get("answer") or "") if x.strip()):
        ids = [i for i in cited(u) if i in titles and not i.startswith("W")]
        for n in re.findall(r"\(([^()]{2,40})\)", CITE.sub(" ", u)):
            own = owners.get(n.lower(), set())
            if ids and len(own) == 1 and not own & set(ids):
                errs.append(f"a line names ({n}), which is [{next(iter(own))}], but cites "
                            f"{ids}: {u.strip()[:90]!r}")
        if len(ids) != 1:
            continue
        words = set(re.findall(r"[a-z]{4,}", CITE.sub(" ", u).lower()))
        if not words:
            continue
        own = set(re.findall(r"[a-z]{4,}", titles[ids[0]].lower())) - TITLE_STOP
        if own and not own & words:
            errs.append(f"a line cites [{ids[0]}] but names none of its title: {u.strip()[:90]!r}")
    return errs


def record_titles(leads: list[dict]) -> dict[str, str]:
    out = {}
    for x in leads:
        rec = x.get("opportunity") or x.get("record") or {}
        if t := rec.get("title") or rec.get("name"):
            out[short(x["record_id"])] = t
    return out


def check_draft(ex: dict, top: str, others: list[str]) -> list[str]:
    drafts = [c for c in ex["cards"] if c["tool"] == "draft_handoff" and c["status"] == "done"]
    if not drafts:
        return ["no draft_handoff step: " + json.dumps(
            [(c["tool"], c["status"], c["arguments"]) for c in ex["cards"]])]
    d = drafts[-1]["draft"] or {}
    text = f"{d.get('subject', '')}\n{d.get('body', '')}"
    errs = []
    if top not in text:
        errs.append(f"the draft does not name the top lead {top}")
    if extra := [o for o in others if o in text]:
        errs.append(f"the draft also names {extra}")
    if "1 funding opportunity" not in d.get("subject", ""):
        errs.append(f"subject reads {d.get('subject')!r}")
    return errs


def check_student(ex: dict) -> list[str]:
    errs = []
    if not any(c["tool"] in SEARCH_TOOLS and c["status"] == "done" for c in ex["cards"]):
        errs.append("no search step")
    a = ex.get("answer") or ""
    if not a:
        return [*errs, f"no answer ({ex.get('status')}; {'; '.join(ex.get('errors') or [])})"]
    if REFUSAL.search(a) and not cited(a):
        errs.append("refuses")
    heading = False
    for line in a.splitlines():
        if re.match(r"^\W*sample scholarships", line, re.I):
            heading = True
        ids = [i for i in cited(line)]
        if any(i.startswith("sample:") for i in ids):
            if not heading:
                errs.append("a sample is cited before its own heading")
                break
            if any(not i.startswith("sample:") for i in ids):
                errs.append("a sample shares a line with a public record")
                break
    return errs


def researcher_run(base: str, n: int, kept: str = "top2") -> dict:
    """kept: top2 (the demo, and the gate), none, or weak2 (the two weakest grants and the
    top two companies, as QA round 3 varied it)."""
    cl = Client(base)
    out: dict = {"run": n, "kept": kept, "questions": []}
    try:
        cl.post("/private/brief", {"author_id": AUTHOR})
        g = cl.wait_brief()
        as_of = date.fromisoformat(g["brief"]["options"]["as_of"])
        grants = sorted((x for x in g["leads"] if x["route"] == "A"
                         and x["status"] != "dismissed"), key=lambda x: x["rank"] or 0)
        orgs = sorted((x for x in g["leads"] if x["route"] == "B"), key=lambda x: x["rank"] or 0)
        keep = {"top2": grants[:2], "none": [], "weak2": grants[-2:] + orgs[:2]}[kept]
        for x in keep:
            cl.post(f"/private/leads/{x['id']}/keep")
        top = [short(x["record_id"]) for x in grants[:3]]
        closes: dict[str, date | None] = {}
        for x in grants:
            o = x.get("opportunity") or {}
            d = date.fromisoformat(o["close_date"]) if o.get("close_date") else None
            far = d and o.get("close_date_note") and (d - as_of).days > 3 * 365
            closes[short(x["record_id"])] = None if far else d
        sid = None
        titles = record_titles(g["leads"])
        checks = (lambda ex: check_top_three(ex, top) + check_own_titles(ex, titles),
                  lambda ex: check_before_march(ex, as_of, closes) + check_own_titles(ex, titles),
                  lambda ex: check_draft(ex, top[0], [short(x["record_id"]) for x in grants[1:]]))
        for q, check in zip(QUESTIONS, checks, strict=True):
            sid, ex, secs = cl.ask(sid, q)
            errs = check(ex)
            out["questions"].append(_record(q, ex, secs, errs))
    finally:
        cl.end()
    return out


def student_run(base: str, n: int) -> dict:
    cl = Client(base)
    out: dict = {"run": n, "questions": []}
    try:
        for kind in ("cv", "interests", "achievements"):
            cl.post("/private/documents", {"kind": kind,
                                           "text": (PERSONA / f"{kind}.md").read_text()})
        cl.post("/private/student/brief", {})
        g = cl.wait_brief(limit=600)
        if g["brief"]["status"] != "done":
            raise RuntimeError("the student brief failed")
        _, ex, secs = cl.ask(None, STUDENT_Q)
        out["questions"].append(_record(STUDENT_Q, ex, secs, check_student(ex)
                                        + check_own_titles(ex, record_titles(g["leads"]))))
    finally:
        cl.end()
    return out


def check_documents_draft(ex: dict, top: str, others: list[str], vocab: set[str]) -> list[str]:
    errs = check_draft(ex, top, others)
    drafts = [c for c in ex["cards"] if c["tool"] == "draft_handoff" and c["status"] == "done"]
    if not drafts:
        return errs
    d = drafts[-1]["draft"] or {}
    body = d.get("body", "")
    if "[]" in body or re.search(r"no papers provided", body, re.I):
        errs.append("the draft holds an empty or placeholder citation")
    opening = body.split("\n\n")[1] if body.count("\n\n") >= 2 else body
    if "[" in opening:
        errs.append(f"the opening holds a bracket: {opening[:160]!r}")
    if d.get("opening_by") != "code":
        errs.append(f"the opening was written by {d.get('opening_by') or 'an unlabelled hand'}"
                    ", not by code, in a documents session with no public papers")
    new = sorted({w for w in re.findall(r"[a-z]{6,}", opening.lower()) if w not in vocab})
    if new:
        errs.append(f"the opening uses words in no document, record or template: {new[:8]}")
    return errs


def documents_run(base: str, n: int) -> dict:
    cl = Client(base)
    out: dict = {"run": n, "questions": []}
    try:
        texts = []
        for kind, name in DOC_FILES.items():
            texts.append((DOCS / name).read_text())
            cl.post("/private/documents", {"kind": kind, "text": texts[-1]})
        cl.post("/private/brief", {})
        g = cl.wait_brief(limit=600)
        if g["brief"]["status"] != "done":
            raise RuntimeError("the documents brief failed")
        grants = sorted((x for x in g["leads"] if x["route"] == "A"
                         and x["status"] != "dismissed"), key=lambda x: x["rank"] or 0)
        cl.post(f"/private/leads/{grants[0]['id']}/keep")
        vocab = set(re.findall(r"[a-z]{6,}", " ".join(
            [*texts, json.dumps(grants[0]), (ROOT / "perch/skills/handoff.py").read_text(),
             (ROOT / "perch/export.py").read_text(), (ROOT / "perch/offices.py").read_text()]
        ).lower()))
        top = short(grants[0]["record_id"])
        _, ex, secs = cl.ask(None, DOCS_Q)
        out["questions"].append(_record(DOCS_Q, ex, secs, check_documents_draft(
            ex, top, [short(x["record_id"]) for x in grants[1:]], vocab)))
    finally:
        cl.end()
    return out


def _record(q: str, ex: dict, secs: float, errs: list[str]) -> dict:
    return {"question": q, "pass": not errs, "errors": [alias(e) for e in errs],
            "seconds": round(secs, 1), "status": ex.get("status"),
            "answer": alias(ex.get("answer") or ""), "flagged": ex.get("flagged"),
            "steps": [{"tool": c["tool"], "status": c["status"], "arguments": c["arguments"],
                       **({"subject": alias(c["draft"]["subject"]),
                           "body": alias(c["draft"]["body"]),
                           "opening_by": c["draft"].get("opening_by")}
                          if c.get("draft") else {})}
                      for c in ex["cards"]]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8091")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", nargs="+", default=["researcher", "student", "documents"])
    ap.add_argument("--label", default="")
    ap.add_argument("--kept", default="top2", choices=["top2", "none", "weak2"],
                    help="what the researcher runs keep before asking; top2 is the demo")
    a = ap.parse_args()
    report: dict = {"base": a.base, "runs": a.runs, "kept": a.kept, "researcher": [],
                    "student": [], "documents": []}
    for flow, fn in (("researcher", researcher_run), ("student", student_run),
                     ("documents", documents_run)):
        if flow not in a.only:
            continue
        for n in range(1, a.runs + 1):
            try:
                r = fn(a.base, n, a.kept) if flow == "researcher" else fn(a.base, n)
            except Exception as e:  # noqa: BLE001 - a failed run counts as failed questions
                r = {"run": n, "error": f"{type(e).__name__}: {alias(str(e))[:200]}",
                     "questions": []}
            report[flow].append(r)
            for q in r["questions"]:
                mark = "pass" if q["pass"] else "FAIL"
                print(f"{flow} run {n} | {mark} | {q['seconds']:>5}s | {q['question']}")
                for e in q["errors"]:
                    print(f"    - {e}")
                print("    steps: " + "; ".join(f"{s['tool']}({json.dumps(s['arguments'])})"
                                                for s in q["steps"]))
                print("    answer: " + q["answer"].replace("\n", " / ")[:600])
            if r.get("error"):
                print(f"{flow} run {n} | ERROR | {r['error']}")
            sys.stdout.flush()
    print("\nPass counts")
    total = ok = 0
    for flow, qs in (("researcher", QUESTIONS), ("student", (STUDENT_Q,)),
                     ("documents", (DOCS_Q,))):
        if flow not in a.only:
            continue
        for i, q in enumerate(qs):
            got = [r["questions"][i]["pass"] if len(r["questions"]) > i else False
                   for r in report[flow]]
            print(f"  {flow:10} Q{i + 1} {sum(got)} of {len(got)}  {q}")
            total += len(got)
            ok += sum(got)
    print(f"  all {ok} of {total}")
    out = ROOT / "build/rehearsal"
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + (f"-{a.label}" if a.label else "")
    path = out / f"rehearsal-{stamp}.json"
    path.write_text(json.dumps(report, indent=1))
    print(f"  report: {path.relative_to(ROOT)}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
