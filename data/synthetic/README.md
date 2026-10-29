# data/synthetic — SYNTHETIC test data

Everything in this folder is invented. No person, sponsor, award, school or result here
exists. Standing rules 11 and 12 (CLAUDE.md) govern it.

## Sample scholarship corpus (`scholarships.jsonl`)

- **What it is:** 500 SYNTHETIC scholarship records for student mode. They are shaped
  like a real scholarship database, but no record is copied from any site.
- **How it was made:** `scripts/make_sample_scholarships.py` with seed 1729 on
  2026-10-29. Hand-written templates set the award type, level, field and the ranges.
  The local chat model (gemma4:26b-a4b on Ollama) wrote only the purpose sentences.
  Code rejected any model sentence with a digit, a dollar sign, a month, a number word
  or a capitalised name, and used the template sentence instead.
- **What marks a record:** `source: synthetic`, an id `sample:sch-NNNN`, and a canary
  `PERCH-CANARY-SCH-NNNN` at the end of its purpose text.
- **Sponsors:** each sponsor is a coined word plus a generic type ("Quillmere Education
  Trust"). A test checks every sponsor against well-known sponsors, the awards on
  Temple's public fellowship pages and OpenAlex institution names.
- **Dates:** every deadline falls between 2026-11-20 and 2027-09-30, after the
  generation date. No record has a passed deadline on Demo Day.
- **Where it lives:** the app loads it into a separate store (`data/sample.db`), never
  into the public store. Only student mode opens it, and every card shows a sample badge.
- **Planted cases:** records `sample:sch-0001` to `sample:sch-0024` are written by hand
  for the three student personas below. Each one tests one rule.

## Student personas

| Folder | Stands in for | Planted records |
|---|---|---|
| `persona-ug` | a third-year undergraduate in environmental science | 0001 to 0008 |
| `persona-masters` | a part-time MPH student in epidemiology | 0009 to 0016 |
| `persona-phd` | a full-time neuroscience PhD candidate | 0017 to 0024 |

Each folder has a CV, an interests note, three achievements and an answer key. Every
file holds its own canary token (`PERCH-CANARY-UG-…`, `-MS-…`, `-PHD-…`).
`persona-1` is the S13 faculty persona for private mode.

## Answer key rules

The answer keys were written by hand from these rules, before the S18 rule code
existed. The S19 bench compares the app's verdicts and gap lists with them.

- **Verdicts:** "eligible", "may be eligible" or "not eligible".
- **Not eligible:** the first rule a record breaks, checked in this order:
  1. `deadline`: the deadline is before the as-of date.
  2. `level`: the record lists levels and the student's level is not among them.
  3. `class_year`: the record lists undergraduate years and the student's year is not
     among them.
  4. `graduation`: the student's expected graduation is after `graduation_by` or
     before `graduation_after`.
  5. `major`: the record lists majors and the student's major is not among them.
  6. `gpa`: the record has a minimum GPA and the student's stated GPA is below it.
  7. `enrolment`: the record asks for full-time or part-time and the student's stated
     status is the other one.
- **May be eligible:** no rule is broken, but the record asks for something the CV
  cannot show. The reasons are `gpa_unstated` (a minimum GPA and no GPA on the CV),
  `residency`, `citizenship` and `targeted` (a criterion the student judges). The app
  never asks for these.
- **Eligible:** no rule is broken and nothing is unknown.
- **Gap list:** for an eligible or may-be-eligible record, the requirements the CV does
  not show, in this order:
  - `transcript`, `essay`, `interview` and `fafsa`: always gaps, because a CV cannot
    show them.
  - `letters`: a gap when the record asks for more letters than the CV's References
    section lists.
  - `portfolio`: a gap unless the CV has a portfolio.
  - `gpa`: a gap when the record has a minimum GPA and the CV states none.
- **As-of date:** 2026-11-06.
