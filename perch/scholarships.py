"""Scholarship records for student mode (S17): the sample store, the real-name check,
and the public fellowship listings.

Standing rule 11: synthetic records never share a list with public ones. They live in
their own SQLite file (PERCH_SAMPLE_DB, default data/sample.db), loaded from the
committed data/synthetic/scholarships.jsonl. The public store never holds one, so no
public screen, back-test or bench can list one by accident; student mode opens the
sample store on purpose and labels every card.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from perch.config import env
from perch.schemas import Opportunity, Organisation, Researcher, Scholarship
from perch.store.base import Repository
from perch.store.sqlite import SQLiteRepository

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_JSONL = ROOT / "data/synthetic/scholarships.jsonl"
CANARY_PREFIX = "PERCH-CANARY-SCH-"


def sample_db() -> Path:
    return Path(env("PERCH_SAMPLE_DB", str(ROOT / "data/sample.db")))


def read_samples(path: Path = SAMPLE_JSONL) -> list[Scholarship]:
    out = [Scholarship.model_validate_json(line) for line in path.read_text("utf-8").splitlines()
           if line.strip()]
    bad = [s.id for s in out if not s.synthetic]
    if bad:
        raise ValueError(f"not synthetic: {bad[:3]}")
    return out


def load_samples(repo: Repository, path: Path = SAMPLE_JSONL) -> int:
    """Write the sample corpus into repo, which must be the sample store."""
    return repo.upsert(read_samples(path))


def open_samples() -> SQLiteRepository:
    """The sample store, loaded from the committed file on first use."""
    p = sample_db()
    fresh = not p.exists()
    repo = SQLiteRepository(p)
    if fresh or not repo.list(Scholarship):
        load_samples(repo)
    return repo


# --- real-name check (rule 11: a sample sponsor must not be confusable with a real one) ---

# Well-known scholarship and fellowship sponsors, foundations, agencies and companies,
# written from general knowledge as a guard list. Not a source for anything shown.
WELL_KNOWN = """Gates Foundation; Bill & Melinda Gates Foundation; Gates Millennium Scholars;
Ford Foundation; Fulbright; Rhodes Trust; Marshall Scholarship; Truman Scholarship;
Goldwater Scholarship; Udall Foundation; Boren Awards; Gilman Scholarship; Beinecke;
Jack Kent Cooke Foundation; Coca-Cola Scholars Foundation; Hertz Foundation;
Paul & Daisy Soros; Knight-Hennessy; Schwarzman; Mitchell Scholarship; Churchill
Scholarship; Luce Foundation; Rockefeller Foundation; Carnegie Corporation; Mellon
Foundation; Andrew W. Mellon; Alfred P. Sloan Foundation; Simons Foundation; Pew
Charitable Trusts; Robert Wood Johnson Foundation; Howard Hughes Medical Institute;
Burroughs Wellcome Fund; Wellcome Trust; MacArthur Foundation; Kellogg Foundation;
Kresge Foundation; Lilly Endowment; Dell Scholars; Elks National Foundation; Rotary
International; Kiwanis; Lions Clubs; Horatio Alger Association; Ronald McDonald House
Charities; QuestBridge; Posse Foundation; United Negro College Fund; UNCF; Hispanic
Scholarship Fund; American Association of University Women; AAUW; American Indian College
Fund; Thurgood Marshall College Fund; Point Foundation; Davidson Institute; Regeneron
Science Talent Search; Siemens Foundation; Intel Foundation; Google; Microsoft; Amazon;
Apple; Meta; IBM; Pfizer; Merck; Johnson & Johnson; Walmart Foundation; PepsiCo; Boeing;
Lockheed Martin; Northrop Grumman; Raytheon; General Electric; Genentech; Gilead;
Amgen; National Science Foundation; NSF; National Institutes of Health; NIH; NASA;
Department of Energy; Department of Defense; NOAA; Smithsonian; Peace Corps;
AmeriCorps; National Merit Scholarship Corporation; College Board; Sallie Mae;
Fastweb; Scholarships.com; ScholarshipUniverse; Temple University; Pennsylvania
Higher Education Assistance Agency; PHEAA""".replace("\n", " ")

# Words that say what kind of body or award something is, not which one.
GENERIC = set("""the of for and in on at a an to & foundation fund funds trust trusts
scholarship scholarships scholars scholar fellowship fellowships fellows fellow award awards
grant grants prize prizes program programme programs society council association
institute institutes institution university universities college school center centers centre
network alliance foundations associations societies companies trusts
endowment corporation company inc llc group charities charitable club clubs national
international american united states us u.s. federal department office league guild
circle collective cooperative initiative project consortium partners partnership
academy research science sciences education educational student students memorial
community studies study learning aid financial summer junior senior graduate
undergraduate new early young
future women men public service services medical health arts art""".split())


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[.'&-][a-z0-9]+)*", text.lower())


def distinctive(name: str) -> set[str]:
    """The words that pick out one organisation: a name minus GENERIC words."""
    return {w for w in tokens(name) if w not in GENERIC and not w.isdigit() and len(w) > 1}


def real_names(repo: Repository | None = None, fixtures: Path | None = None) -> set[str]:
    """Names of real organisations to keep sample sponsors away from: WELL_KNOWN, the
    awards and sponsors on the saved Temple pages, and OpenAlex institution and company
    names from the fixtures and from repo (Researcher.institutions, Organisation)."""
    from perch.sources import temple

    names = {n.strip() for n in WELL_KNOWN.split(";") if n.strip()}
    fx = fixtures or ROOT / "tests/fixtures"
    page = fx / "temple/sdfa_find_fellowship.html"
    if page.exists():
        names |= {s.name for s in temple.parse_listing(page.read_text("utf-8"))}
    grad = fx / "temple/grad_external_funding.html"
    if grad.exists():
        # Sponsors only: links that leave temple.edu (the rest is site navigation).
        names |= {temple._text(a) for h, a in re.findall(r'<a [^>]*href="(https?://[^"]+)"'
                                                         r"[^>]*>(.*?)</a>",
                                                         grad.read_text("utf-8"), re.S)
                  if "temple.edu" not in h}
    for f in sorted((fx / "openalex").glob("*.json")):
        names |= institutions_in(json.loads(f.read_text("utf-8")))
    if repo is not None:
        for r in repo.list(Researcher):
            names |= set(r.institutions)
        names |= {o.name for o in repo.list(Organisation)}
        names |= {o.agency for o in repo.list(Opportunity)}
    return {n for n in names if len(n) > 2}


def institutions_in(data: object) -> set[str]:
    """display_name of every institution object in an OpenAlex response."""
    out: set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("institutions", "last_known_institutions") and isinstance(v, list):
                out |= {x["display_name"] for x in v
                        if isinstance(x, dict) and x.get("display_name")}
            out |= institutions_in(v)
    elif isinstance(data, list):
        for v in data:
            out |= institutions_in(v)
    return out


def name_hits(name: str, real: Iterable[str]) -> list[str]:
    """Real names that name collides with: a shared distinctive word, or the real name's
    full wording inside name."""
    mine = distinctive(name)
    low = " ".join(tokens(name))
    out = []
    for r in real:
        rt = " ".join(tokens(r))
        if (mine & distinctive(r)) or (len(rt) > 3 and re.search(rf"\b{re.escape(rt)}\b", low)):
            out.append(r)
    return sorted(out)


# --- public fellowship listings already in the store (NIH, via Grants.gov) ---

# NIH individual fellowships a student applies for, by activity code, and the level each
# is for. F30 and F31 are predoctoral, F99 is the dissertation phase of F99/K00; F32 and
# F33 are postdoctoral and senior fellowships, kept so a student sees why they do not
# fit. K (career development) and T (institutional training) awards are not listed: a
# K applicant holds a doctorate, and a T award goes to an institution, not a student.
NIH_FELLOWSHIP_LEVEL = {"F30": "graduate", "F31": "graduate", "F99": "graduate",
                        "F32": "postdoctoral", "F33": "senior"}


def nih_fellowships(repo: Repository) -> list[Opportunity]:
    return [o for o in repo.list(Opportunity)
            if (o.activity_code or "") in NIH_FELLOWSHIP_LEVEL]


def dump_jsonl(records: Iterable[Scholarship], path: Path) -> None:
    path.write_text("".join(json.dumps(json.loads(s.model_dump_json()), sort_keys=True) + "\n"
                            for s in records), "utf-8")
