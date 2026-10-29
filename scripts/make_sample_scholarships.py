"""Generate the SYNTHETIC sample scholarship corpus (S17 task 2).

Every record is invented (standing rule 11). The corpus is shaped like a real
scholarship database, but no record is copied from any site. Run:

    uv run python scripts/make_sample_scholarships.py            # local model writes purposes
    uv run python scripts/make_sample_scholarships.py --no-model # template text only

How a record is made:
1. A hand-written template picks the award type, levels, fields, the amount and deadline
   ranges, and the requirement and eligibility profile.
2. A seeded random draw (SEED) picks a fictional sponsor and the concrete values.
3. The local chat model may write the purpose: one or two sentences, from the name,
   award type, level and field. Code rejects any model text with a digit, a dollar sign,
   a month, a number word or a capitalised word other than the first, and then uses the
   template's own sentence. So the model never adds a number, a date or a name.
4. A deterministic pass sets every structured field, checks consistency, appends the
   canary and assigns the `sample:sch-NNNN` id.
The first PLANTED records are written by hand for the three student personas
(data/synthetic/persona-*); their answer keys refer to them by id.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from perch.llm import Provider  # noqa: E402
from perch.schemas import Scholarship, ScholarshipEligibility, ScholarshipRequirements  # noqa: E402
from perch.scholarships import CANARY_PREFIX, SAMPLE_JSONL, dump_jsonl, name_hits, real_names  # noqa: E402

SEED = 1729
TOTAL = 500
GENERATED = date(2026, 10, 29)  # deadlines fall after this date, so the corpus stays valid
FIRST_DEADLINE = date(2026, 11, 20)
LAST_DEADLINE = date(2027, 9, 30)
FETCHED = datetime(2026, 10, 29, 12, tzinfo=UTC)
URL = "synthetic://perch/sample-scholarships"

# Coined words: none is a real organisation's name (checked against real_names()).
COINED = """Quillmere Brindlecove Vantorre Marrowfield Ostrevel Callowmere Dunmarrow Feldspire
Hesterwick Ivorvale Jessamyne Kestrelby Lorrimond Mistlecombe Norwhistle Orlanthe Pellowyn
Quenridge Rookhallow Saffrenby Thistlecombe Umberlane Vossmere Wrenholt Yarrowdene Zephrath
Ambergate Brackenly Cindervale Dovecrest Elmsworthy Fennimore Glimmerton Hollowmere Inkwater
Juniperby Larkmoor Moonvale Nettlecombe Oakhurrow Primrook Quaverly Rushmeadow Silverwend
Tamberlin Underhay Veldmoor Willowick Ashcombe Bellweather Copperwyn""".split()
SPONSOR_TYPES = ["Education Trust", "Scholarship Fund", "Foundation", "Learning Society",
                 "Memorial Fund", "Community Fund", "Guild", "Circle", "Student Aid Trust",
                 "Collective"]
FIELDS = ["biology", "chemistry", "computer science", "engineering", "nursing",
          "public health", "education", "business", "accounting", "journalism",
          "communication", "film and media arts", "music", "visual arts", "architecture",
          "environmental science", "mathematics", "physics", "psychology", "social work",
          "political science", "history", "English", "world languages", "kinesiology",
          "neuroscience", "bioengineering", "data science", "epidemiology", "economics"]
ARTS = {"film and media arts", "music", "visual arts", "architecture"}
STATES = ["PA", "NJ", "DE", "NY", "MD", "OH"]
TARGETED = [
    "first-generation college student",
    "has completed at least one season of community volunteering",
    "is a parent or guardian of a dependent child",
    "is returning to study after a break of at least two years",
    "is a current or former member of the armed forces",
    "grew up in a rural county",
    "has worked in a family business",
    "is the first in their family to pursue a graduate degree",
]

# Hand-written templates: (name pattern, award type, levels, amount range, purpose sentence,
# requirement profile, eligibility profile, field pool or None for any field).
TEMPLATES = [
    ("{s} Merit Scholarship in {F}", "scholarship", ["bachelor's"], (1000, 5000),
     "Rewards strong academic work by undergraduates studying {f}.", "merit", "merit", None),
    ("{s} Need-Based Award", "scholarship", ["bachelor's", "associate"], (500, 4000),
     "Helps students with financial need cover tuition and books.", "need", "need", None),
    ("{s} First-Year Scholarship", "scholarship", ["high school"], (500, 2500),
     "Supports graduating high school seniors as they begin college.", "essay", "hs", None),
    ("{s} Transfer Student Scholarship", "scholarship", ["associate", "bachelor's"],
     (1000, 3000), "Supports students moving from a two-year college to a bachelor's "
     "programme.", "essay", "transfer", None),
    ("{s} Graduate Fellowship in {F}", "fellowship", ["graduate"], (5000, 30000),
     "Funds graduate study and research in {f}.", "fellowship", "grad", None),
    ("{s} Dissertation Completion Fellowship", "fellowship", ["graduate"], (10000, 35000),
     "Gives doctoral candidates time to finish writing the dissertation.", "fellowship",
     "grad", None),
    ("{s} Research Travel Grant", "grant", ["bachelor's", "graduate"], (300, 2500),
     "Pays travel costs to present research at a meeting.", "travel", "any", None),
    ("{s} Summer Research Grant", "grant", ["bachelor's"], (1500, 5000),
     "Supports a summer research project in {f} with a faculty mentor.", "research",
     "upper", None),
    ("{s} Prize for Writing in {F}", "prize", ["bachelor's", "graduate"], (250, 2000),
     "Recognises an outstanding essay or paper in {f}.", "writing", "any", None),
    ("{s} Creative Portfolio Prize", "prize", ["high school", "bachelor's"], (250, 3000),
     "Recognises original creative work in {f}.", "portfolio", "any", ARTS),
    ("{s} Professional Degree Scholarship", "scholarship", ["professional"], (2000, 15000),
     "Supports students in professional degree programmes.", "merit", "prof", None),
    ("{s} Community Leadership Scholarship", "scholarship",
     ["high school", "bachelor's"], (500, 3000),
     "Rewards students who lead service projects in their communities.", "leader", "any",
     None),
    ("{s} Part-Time Learner Award", "scholarship", ["associate", "bachelor's", "graduate"],
     (500, 2000), "Supports students who study part-time while working.", "need",
     "part", None),
    ("{s} Women in {F} Scholarship", "scholarship", ["bachelor's", "graduate"], (1000, 6000),
     "Encourages women to study and work in {f}.", "essay", "targeted", None),
    ("{s} Associate Degree Completion Grant", "grant", ["associate"], (300, 2000),
     "Helps students finish an associate degree on time.", "need", "need", None),
    ("{s} Study Abroad Scholarship", "scholarship", ["bachelor's", "graduate"], (1000, 7500),
     "Helps students spend a term studying abroad.", "essay", "any", None),
    ("{s} Teaching Fellowship", "fellowship", ["graduate"], (8000, 25000),
     "Supports graduate students preparing to teach in {f}.", "fellowship", "grad",
     {"education", "mathematics", "English", "history", "world languages"}),
    ("{s} Health Professions Scholarship", "scholarship", ["bachelor's", "professional"],
     (2000, 10000), "Supports students preparing for careers in {f}.", "merit", "merit",
     {"nursing", "public health", "kinesiology", "epidemiology"}),
    ("{s} STEM Scholars Award", "scholarship", ["bachelor's"], (2000, 8000),
     "Supports undergraduates with strong promise in {f}.", "merit", "upper",
     {"biology", "chemistry", "computer science", "engineering", "mathematics", "physics",
      "data science", "bioengineering", "neuroscience", "environmental science"}),
    ("{s} Senior Capstone Award", "prize", ["bachelor's"], (250, 1500),
     "Recognises an outstanding senior project in {f}.", "writing", "senior", None),
]
AMOUNT_STEPS = [250, 300, 500, 750, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 7500,
                8000, 10000, 12000, 15000, 20000, 25000, 30000, 35000]
MONTH_WEIGHTS = {11: 1, 12: 3, 1: 4, 2: 5, 3: 5, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1}


def pick_amount(rng: random.Random, lo: int, hi: int) -> tuple[float, float]:
    steps = [a for a in AMOUNT_STEPS if lo <= a <= hi] or [lo]
    a = rng.choice(steps)
    if rng.random() < 0.7:
        return float(a), float(a)
    b = rng.choice([x for x in steps if x >= a])
    return float(a), float(b)


def pick_deadline(rng: random.Random) -> date:
    months = list(MONTH_WEIGHTS)
    m = rng.choices(months, weights=[MONTH_WEIGHTS[x] for x in months])[0]
    y = 2026 if m >= 11 else 2027
    d = date(y, m, rng.choice([1, 10, 15, 20, 28]))
    return min(max(d, FIRST_DEADLINE), LAST_DEADLINE)


def requirements(rng: random.Random, profile: str) -> ScholarshipRequirements:
    r = ScholarshipRequirements()
    r.transcript = profile in ("merit", "fellowship", "research") or rng.random() < 0.3
    r.essay = profile != "travel" and rng.random() < 0.8 or profile in ("essay", "writing")
    r.letters_count = {"fellowship": rng.choice([2, 3]), "research": 1,
                       "leader": rng.choice([1, 2])}.get(profile, rng.choice([0, 0, 1, 2]))
    r.portfolio = profile == "portfolio"
    r.interview = profile in ("fellowship", "leader") and rng.random() < 0.3
    r.fafsa = profile == "need"
    return r


def eligibility(rng: random.Random, profile: str, f: str) -> tuple[ScholarshipEligibility, str]:
    e = ScholarshipEligibility()
    if profile in ("merit", "upper"):
        e.gpa_min = rng.choice([3.0, 3.2, 3.5, 3.7])
    elif rng.random() < 0.35:
        e.gpa_min = rng.choice([2.5, 2.8, 3.0])
    if profile == "upper":
        e.class_year = rng.choice([[2, 3], [3], [3, 4], [2, 3, 4]])
    elif profile == "senior":
        e.class_year = [4]
    elif profile == "merit" and rng.random() < 0.4:
        e.class_year = rng.choice([[1], [2, 3, 4], [3, 4]])
    if profile == "part":
        e.enrolment_status = "part-time"
    else:
        e.enrolment_status = rng.choices(["full-time", "any", None], weights=[5, 4, 1])[0]
    if rng.random() < 0.2:
        e.residency_state = rng.choice(STATES)
    if rng.random() < 0.25:
        e.citizenship = "U.S. citizen or permanent resident"
    if profile == "targeted":
        e.targeted_criterion = "identifies as a woman"
    elif rng.random() < 0.25:
        e.targeted_criterion = rng.choice(TARGETED)
    if rng.random() < 0.3 and profile not in ("hs",):
        e.major = [f]
    if profile == "grad" and rng.random() < 0.2:
        e.graduation_after = date(2027, rng.choice([6, 12]), 1)
    kind = "need-based" if profile == "need" else "merit" if profile in ("merit",) else ""
    return e, kind


PURPOSE_RULES = re.compile(
    r"\d|\$|\b(january|february|march|april|may|june|july|august|september|october|november|"
    r"december|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|"
    r"percent|dollars?)\b", re.I)


def clean_purpose(text: str) -> str | None:
    """The model's purpose sentence, or None if it breaks a rule."""
    t = " ".join(text.strip().strip('"').split())
    if not t or len(t) > 320 or PURPOSE_RULES.search(t):
        return None
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", t)
    sentences_first = {m.group(1) for m in re.finditer(r"(?:^|[.!?]\s+)([A-Za-z][\w'-]*)", t)}
    if any(w[0].isupper() and w not in sentences_first and w not in ("STEM", "English")
           for w in words):
        return None  # a capitalised word may be a name; template text instead
    return t


def model_purpose(provider: Provider, name: str, award_type: str, levels: list[str], f: str,
                  seed_text: str) -> str | None:
    from perch.llm import Message

    prompt = (f"Write the purpose statement for a scholarship database entry.\nAward: {name}\n"
              f"Type: {award_type}\nLevel: {', '.join(levels)}\nField: {f}\n"
              f"Starting idea: {seed_text}\n\nRules: one or two short sentences, plain "
              "words, present tense. Do not use any number, amount, date, month, place or "
              "the name of any organisation, person, school or company. Do not repeat the "
              "award name. Reply with the sentences only.")
    try:
        r = provider.chat([Message("user", prompt)], max_tokens=120)
    except Exception:  # noqa: BLE001 - a failed call falls back to the template
        return None
    return clean_purpose(r.text)


def sponsors(rng: random.Random, real: set[str], skip: set[str]) -> list[str]:
    """Three sponsors per coined word not in skip and not close to a real name."""
    return [f"{w} {t}" for w in COINED if w not in skip and not name_hits(w, real)
            for t in rng.sample(SPONSOR_TYPES, 3)]


def canary(n: int) -> str:
    return f"{CANARY_PREFIX}{n:04d}"


def finish(n: int, purpose: str, **kw: object) -> Scholarship:
    c = canary(n)
    return Scholarship(id=f"sample:sch-{n:04d}", source="synthetic", source_url=URL,
                       fetched_at=FETCHED, canary=c,
                       purpose=f"{purpose} SYNTHETIC sample record, canary {c}.", **kw)


def planted() -> list[Scholarship]:
    """Hand-written cases for the personas; see data/synthetic/persona-*/answer_key.json."""
    E, R = ScholarshipEligibility, ScholarshipRequirements
    rows = [
        # Undergraduate persona (3rd year, environmental science, GPA 3.40, full-time,
        # graduates May 2028, two referees listed).
        dict(name="Quillmere Watershed Stewardship Scholarship",
             sponsor="Quillmere Education Trust",
             p="Supports undergraduates who study rivers, streams and watershed restoration.",
             level_of_study=["bachelor's"], field_of_study=["environmental science"],
             award_type="scholarship", amount_min=3000, amount_max=3000,
             deadline=date(2027, 2, 15),
             eligibility=E(gpa_min=3.0, class_year=[3, 4], enrolment_status="full-time"),
             application_requirements=R(transcript=True, essay=True, letters_count=2)),
        dict(name="Brindlecove Clean Water Honors Award", sponsor="Brindlecove Foundation",
             p="Rewards top students working on urban water quality.",
             level_of_study=["bachelor's"], field_of_study=["environmental science"],
             award_type="scholarship", amount_min=5000, amount_max=5000,
             deadline=date(2027, 1, 31),
             eligibility=E(gpa_min=3.5, enrolment_status="any"),
             application_requirements=R(transcript=True, essay=True, letters_count=1)),
        dict(name="Vantorre Early Field Science Scholarship", sponsor="Vantorre Learning Society",
             p="Helps students in their first two years start field work in ecology and "
               "water science.",
             level_of_study=["bachelor's"], field_of_study=["environmental science"],
             award_type="scholarship", amount_min=1500, amount_max=1500,
             deadline=date(2027, 3, 1),
             eligibility=E(class_year=[1, 2], enrolment_status="any"),
             application_requirements=R(essay=True)),
        dict(name="Marrowfield Graduate Fellowship in Water Resources",
             sponsor="Marrowfield Scholarship Fund",
             p="Funds graduate research on watershed management and stream restoration.",
             level_of_study=["graduate"], field_of_study=["environmental science"],
             award_type="fellowship", amount_min=15000, amount_max=15000,
             deadline=date(2027, 1, 15), eligibility=E(enrolment_status="full-time"),
             application_requirements=R(transcript=True, essay=True, letters_count=3)),
        dict(name="Ostrevel Regional Streams Scholarship", sponsor="Ostrevel Community Fund",
             p="Supports students who monitor and restore local streams.",
             level_of_study=["bachelor's"], field_of_study=["environmental science"],
             award_type="scholarship", amount_min=2000, amount_max=2000,
             deadline=date(2027, 3, 15),
             eligibility=E(residency_state="PA", enrolment_status="any"),
             application_requirements=R(essay=True, letters_count=3)),
        dict(name="Callowmere Pathway Scholarship for Environmental Studies",
             sponsor="Callowmere Student Aid Trust",
             p="Helps students who are new to college study the environment.",
             level_of_study=["bachelor's"], field_of_study=["environmental science"],
             award_type="scholarship", amount_min=2500, amount_max=2500,
             deadline=date(2027, 2, 1),
             eligibility=E(targeted_criterion="first-generation college student",
                           enrolment_status="any"),
             application_requirements=R(transcript=True, fafsa=True)),
        dict(name="Dunmarrow Graduating Senior Award in Ecology", sponsor="Dunmarrow Guild",
             p="Recognises students finishing a degree in ecology or environmental science "
               "this year.",
             level_of_study=["bachelor's"], field_of_study=["environmental science"],
             award_type="prize", amount_min=1000, amount_max=1000,
             deadline=date(2027, 4, 1),
             eligibility=E(graduation_by=date(2027, 6, 30), enrolment_status="any"),
             application_requirements=R(essay=True)),
        dict(name="Feldspire Field Notes Prize", sponsor="Feldspire Circle",
             p="Recognises field journals, maps and photographs about local waterways.",
             level_of_study=["bachelor's"], field_of_study=["environmental science"],
             award_type="prize", amount_min=500, amount_max=1000,
             deadline=date(2027, 3, 20), eligibility=E(enrolment_status="any"),
             application_requirements=R(essay=True, portfolio=True)),
        # Master's persona (MPH, epidemiology, GPA 3.80, part-time, graduates May 2027,
        # three referees listed).
        dict(name="Hesterwick Public Health Graduate Scholarship",
             sponsor="Hesterwick Education Trust",
             p="Supports graduate students in public health who study disease in "
               "communities.",
             level_of_study=["graduate"], field_of_study=["public health", "epidemiology"],
             award_type="scholarship", amount_min=4000, amount_max=4000,
             deadline=date(2027, 2, 20),
             eligibility=E(gpa_min=3.5, enrolment_status="any"),
             application_requirements=R(essay=True, letters_count=2)),
        dict(name="Ivorvale Full-Time Epidemiology Fellowship", sponsor="Ivorvale Foundation",
             p="Funds full-time graduate study in epidemiology and disease surveillance.",
             level_of_study=["graduate"], field_of_study=["epidemiology"],
             award_type="fellowship", amount_min=12000, amount_max=12000,
             deadline=date(2027, 1, 10), eligibility=E(enrolment_status="full-time"),
             application_requirements=R(transcript=True, essay=True, letters_count=2)),
        dict(name="Jessamyne Undergraduate Public Health Award",
             sponsor="Jessamyne Memorial Fund",
             p="Supports undergraduates who are starting to study public health.",
             level_of_study=["bachelor's"], field_of_study=["public health"],
             award_type="scholarship", amount_min=1500, amount_max=1500,
             deadline=date(2027, 3, 1), eligibility=E(enrolment_status="any"),
             application_requirements=R(essay=True)),
        dict(name="Kestrelby Population Health Scholarship", sponsor="Kestrelby Scholarship Fund",
             p="Supports graduate students who study the health of whole populations.",
             level_of_study=["graduate"], field_of_study=["public health", "epidemiology"],
             award_type="scholarship", amount_min=3000, amount_max=5000,
             deadline=date(2027, 2, 28),
             eligibility=E(citizenship="U.S. citizen", enrolment_status="any"),
             application_requirements=R(transcript=True, letters_count=3)),
        dict(name="Lorrimond Working Professional Scholarship",
             sponsor="Lorrimond Learning Society",
             p="Supports graduate students who study part-time while working in health "
               "services.",
             level_of_study=["graduate"], field_of_study=["public health"],
             award_type="scholarship", amount_min=2500, amount_max=2500,
             deadline=date(2027, 1, 25), eligibility=E(enrolment_status="part-time"),
             application_requirements=R(essay=True, interview=True)),
        dict(name="Mistlecombe Second-Year Epidemiology Award",
             sponsor="Mistlecombe Community Fund",
             p="Supports epidemiology students with at least a full year of study still "
               "ahead.",
             level_of_study=["graduate"], field_of_study=["epidemiology"],
             award_type="scholarship", amount_min=2000, amount_max=2000,
             deadline=date(2027, 3, 10),
             eligibility=E(graduation_after=date(2027, 12, 1), enrolment_status="any"),
             application_requirements=R(essay=True)),
        dict(name="Norwhistle Distinguished Scholar Award in Public Health",
             sponsor="Norwhistle Guild",
             p="Rewards public health graduate students with the very highest grades.",
             level_of_study=["graduate"], field_of_study=["public health"],
             award_type="scholarship", amount_min=6000, amount_max=6000,
             deadline=date(2027, 2, 5),
             eligibility=E(gpa_min=3.9, enrolment_status="any"),
             application_requirements=R(transcript=True, essay=True)),
        dict(name="Orlanthe Applied Epidemiology Scholarship", sponsor="Orlanthe Circle",
             p="Supports graduate and professional students who apply epidemiology in "
               "practice.",
             level_of_study=["graduate", "professional"], field_of_study=["epidemiology"],
             award_type="scholarship", amount_min=1500, amount_max=1500,
             deadline=date(2027, 4, 15), eligibility=E(enrolment_status="any"),
             application_requirements=R(transcript=True)),
        # PhD persona (neuroscience candidate, GPA not stated, full-time, graduates August
        # 2028, three referees listed).
        dict(name="Pellowyn Neuroscience Doctoral Scholarship", sponsor="Pellowyn Foundation",
             p="Supports doctoral students who study how neural circuits shape behaviour.",
             level_of_study=["graduate"], field_of_study=["neuroscience"],
             award_type="scholarship", amount_min=5000, amount_max=5000,
             deadline=date(2027, 1, 20),
             eligibility=E(gpa_min=3.3, enrolment_status="full-time"),
             application_requirements=R(essay=True)),
        dict(name="Quenridge Graduate Fellowship in Systems Neuroscience",
             sponsor="Quenridge Education Trust",
             p="Funds graduate research on memory, sleep and neural circuits.",
             level_of_study=["graduate"], field_of_study=["neuroscience"],
             award_type="fellowship", amount_min=20000, amount_max=20000,
             deadline=date(2027, 1, 5), eligibility=E(enrolment_status="full-time"),
             application_requirements=R(transcript=True, letters_count=3)),
        dict(name="Rookhallow Young Neuroscientist Award", sponsor="Rookhallow Collective",
             p="Encourages high school and college students to explore brain science.",
             level_of_study=["high school", "bachelor's"], field_of_study=["neuroscience"],
             award_type="prize", amount_min=500, amount_max=500,
             deadline=date(2027, 3, 31), eligibility=E(enrolment_status="any"),
             application_requirements=R(essay=True)),
        dict(name="Saffrenby Dissertation Completion Fellowship in Neuroscience",
             sponsor="Saffrenby Scholarship Fund",
             p="Gives neuroscience doctoral candidates in their final year time to write.",
             level_of_study=["graduate"], field_of_study=["neuroscience"],
             award_type="fellowship", amount_min=25000, amount_max=25000,
             deadline=date(2027, 2, 1),
             eligibility=E(graduation_by=date(2027, 8, 31), enrolment_status="any"),
             application_requirements=R(transcript=True, essay=True, letters_count=2)),
        dict(name="Thistlecombe Sleep and Memory Research Fellowship",
             sponsor="Thistlecombe Foundation",
             p="Funds doctoral research on how sleep supports memory.",
             level_of_study=["graduate"], field_of_study=["neuroscience"],
             award_type="fellowship", amount_min=18000, amount_max=18000,
             deadline=date(2027, 2, 10), eligibility=E(enrolment_status="any"),
             application_requirements=R(essay=True, letters_count=2, interview=True)),
        dict(name="Umberlane First-in-Family Doctoral Award", sponsor="Umberlane Memorial Fund",
             p="Supports doctoral students in the brain sciences who are the first in "
               "their family at this level.",
             level_of_study=["graduate"], field_of_study=["neuroscience"],
             award_type="scholarship", amount_min=3000, amount_max=3000,
             deadline=date(2027, 3, 5),
             eligibility=E(targeted_criterion="is the first in their family to pursue a "
                                              "doctorate", enrolment_status="any"),
             application_requirements=R(essay=True, letters_count=2)),
        dict(name="Vossmere Part-Time Doctoral Scholarship", sponsor="Vossmere Guild",
             p="Supports doctoral students in neuroscience who study part-time.",
             level_of_study=["graduate"], field_of_study=["neuroscience"],
             award_type="scholarship", amount_min=2000, amount_max=2000,
             deadline=date(2027, 2, 25), eligibility=E(enrolment_status="part-time"),
             application_requirements=R(essay=True)),
        dict(name="Wrenholt Computational Neuroscience Fellowship",
             sponsor="Wrenholt Student Aid Trust",
             p="Funds graduate students who build computer models of the brain.",
             level_of_study=["graduate"], field_of_study=["neuroscience", "computer science"],
             award_type="fellowship", amount_min=10000, amount_max=10000,
             deadline=date(2027, 1, 30),
             eligibility=E(major=["computer science"], enrolment_status="any"),
             application_requirements=R(transcript=True, letters_count=2)),
    ]
    return [finish(i, r.pop("p"), **r) for i, r in enumerate(rows, 1)]


def generate(provider: Provider | None = None, total: int = TOTAL,
             seed: int = SEED) -> list[Scholarship]:
    rng = random.Random(seed)
    real = real_names()
    out = planted()
    pool = sponsors(rng, real, {(s.sponsor or "").split()[0] for s in out})
    names: set[str] = {s.name for s in out}
    n = len(out)
    while n < total:
        tpl = rng.choice(TEMPLATES)
        pat, atype, levels, (lo, hi), seed_text, req, elig, fpool = tpl
        f = rng.choice(sorted(fpool) if fpool else FIELDS)
        sponsor = rng.choice(pool)
        short = sponsor.split()[0]
        name = pat.format(s=short, F=f.title() if f != "English" else f, f=f)
        if name in names:
            continue
        names.add(name)
        n += 1
        a, b = pick_amount(rng, lo, hi)
        e, _ = eligibility(rng, elig, f)
        if "high school" in levels:
            e.class_year, e.major = [], []
        if "bachelor's" not in levels:
            e.class_year = []
        text = seed_text.format(f=f)
        purpose = (model_purpose(provider, name, atype, levels, f, text) if provider
                   else None) or text
        out.append(finish(n, purpose, name=name, sponsor=sponsor, level_of_study=levels,
                          field_of_study=[f], award_type=atype, amount_min=a, amount_max=b,
                          deadline=pick_deadline(rng), eligibility=e,
                          application_requirements=requirements(rng, req)))
    check(out, real)
    return out


def check(records: list[Scholarship], real: set[str]) -> None:
    """The deterministic consistency pass; raises on the first broken record."""
    ids = set()
    for s in records:
        assert s.synthetic and s.id.startswith("sample:sch-") and s.id not in ids, s.id
        ids.add(s.id)
        assert s.canary and s.canary in (s.purpose or ""), s.id
        assert s.deadline and GENERATED < s.deadline <= LAST_DEADLINE, s.id
        assert s.amount_min is not None and s.amount_max is not None
        assert s.amount_min <= s.amount_max, s.id
        e = s.eligibility
        assert not e.class_year or "bachelor's" in s.level_of_study, s.id
        assert not name_hits(s.sponsor or "", real), (s.id, s.sponsor)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-model", action="store_true", help="template purpose text only")
    ap.add_argument("--llm", default="ollama:gemma4:26b-a4b")
    ap.add_argument("--out", type=Path, default=SAMPLE_JSONL)
    a = ap.parse_args()
    provider = None
    if not a.no_model:
        from perch.llm import get_provider

        provider = get_provider(a.llm)
    recs = generate(provider)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    dump_jsonl(recs, a.out)
    print(f"wrote {len(recs)} records to {a.out}")


if __name__ == "__main__":
    main()
