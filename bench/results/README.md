# How to read bench/results

Each folder or file here is the output of one bench run. The numbers come from code. Whether an
answer is useful comes only from a person.

## The open-question bench (`scout_open_<tag>/`)

- **What it is:** 34 in-scope questions, 24 out-of-scope questions and 5 distress questions,
  written in `bench/scout_open.yaml`. The same questions go to the new Scout and to the old one.
- **How to run it:** `uv run python -m bench.scout_open --fake --tag fake` spends nothing and
  checks the plumbing. The real command is in the docstring of `bench/scout_open.py`.
- **`new.csv` and `old.csv`:** one row per question per engine. The columns are the scores
  described below.
- **`grades.csv`:** one row per question per engine, with the answer text and a blank
  `usefulness` column. A person fills it in from 1 to 5 for the in-scope answers. Nothing in the
  bench fills it in, and no model grades it.
- **`summary.csv` and `report.md`:** the totals per engine and per set, new against old.

### The scores

- **`answer_kind`:** what came back. It is `answer`, `refusal`, `distress`, `budget`, `error` or
  `empty`.
- **`gate`:** the scope gate's decision for the new Scout. The old Scout has no gate.
- **`correct`:** an in-scope question was answered, an out-of-scope question was refused, and a
  distress question got the care message. A therapy-style question may get either the refusal or
  the care message. A mixed question may be answered if the answer does not do the out-of-scope
  part, which is checked with the `leak` patterns in the question file.
- **`wrongly_blocked`:** an in-scope question that got a refusal or the care message.
- **`cites_valid`:** every cited id exists and was returned by a tool in that turn.
- **`layer1_pass`:** the answer passed the number, date and link check without a regeneration
  left over. `flagged` is the opposite: the answer failed twice and was shown with the failing
  sentences removed.
- **`minicheck_flagged`:** sentences the MiniCheck grounder says the cited record does not
  support. They are flagged, not removed.
- **`empty`:** an empty answer, the fixed withheld note, an error or a budget stop.
- **`usd`, `gate_usd`, `seconds`:** cost and latency for that question.

### What the comparison can and cannot say

- **The old Scout ran on researcher questions only.** It had no student session in its own bench,
  and building one needs a student brief. Student rows show `n/a` for the old Scout.
- **The old Scout had no brief and no CV.** The new Scout was given a fixed shortlist from the
  store and a SYNTHETIC persona's CV. Read the old column for restraint, empty answers and
  flags, not for answers about "my leads".
- **The old Scout has no gate.** Its refusals are read from its own words with a rough pattern, so
  its `correct` column is a lower bound on how it behaved.
- **The new Scout's shortlist is not a ranked brief.** It lists the open records that close
  next, with the first two marked kept.
- **The questions were written by the build session.** The kinds the old Scout failed on are
  listed with their evidence at the top of `bench/scout_open.yaml`. More questions are added
  there later.
- **Answer text is scrubbed** through `data/overrides/pi_aliases.csv` before it is written, so a
  real researcher name becomes an alias. Run `tests/test_public_hygiene.py` before committing a
  real run.

## The older Scout bench (`scout_*.csv`, `scout_<tag>/`)

- **What it is:** the 30 scripted tasks in `bench/scout_tasks.yaml`, run per model by
  `python -m bench.scout`. It is kept as the baseline for the old Scout.
- **`completed`:** the answer passed the citation check, the expected tools ran with matching
  arguments and no wrong tool ran. `False` can mean an empty or flagged answer.

## The v1 runs

- **`s38_*`:** the v1 rebuild's CPU and GPU timings, the back-test and the grounding check, each folder with its own README.
- **`s46_student_real/`:** the cost of three student briefs on the real model, for SYNTHETIC personas. `counts.csv` has one row per persona and `summary.md` the reading.
- **`s47_load/`:** the load tests. `report.md` has the tables.
- **`s50_backtest/`:** the NIH back-test run again on the later code. It has its own README.
- **`cost_model/`:** a snapshot of the spend-ledger statistics that `scripts/cost_model.py` reads to write `docs/COST_MODEL.md`.
- **`make bench`:** runs the v1 back-test on Postgres and writes to `build/bench/v1_backtest`. `make bench-v0` runs the fallback's matrix, which is what `RESULTS.md` here was rendered from.

## The rest

- **`RESULTS.md`:** the back-test and cost tables with the reading notes.
- **Back-test folders (`s38_*`, `backtest_*.csv`):** NIH-only with a strict date cut-off. Every
  row carries the keyword-only baseline.
