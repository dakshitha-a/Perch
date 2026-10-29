# HANDOFF.md — state for the next context window

Perch-dev rewrites this at the end of every session. Keep it under 60 lines; it is the first thing the next session reads after CLAUDE.md.

## Last session: S16 — Monitoring (done)
- All five tasks are done. 219 tests pass. No API spend; the ledger is still $2.05 of $100.
- The demo was rebuilt with `make demo`, so the public URL serves the new screen.

## What S16 built
- **The job:** `perch/monitor.py`, run as `perch monitor --author A…` or with `PERCH_WATCH` set.
  - **Refresh:** a Grants.gov delta. A full record is fetched only for a new listing, or one whose status or close date changed.
  - **Fresh brief:** each watched researcher gets a new brief through `service.create` and `run`. It never goes through `reuse`, which would compare a brief with itself.
  - **Baseline:** the last digest's brief. Without one, the newest finished brief with the same options.
- **Triggers:**
  - An award trigger: a linked award ends within 12 months. It fires once per award.
  - An opportunity trigger: one new to the top 10 (Q24).
  - Listed but not triggers: close-date changes, dropped leads and new industry leads.
- **Records:** `Change` and `Digest` in `perch/schemas.py`. A digest holds a snapshot of the leads' close dates, so the next run can see a date move.
- **Draft:** written by code only, addressed to the researcher. It reuses the hand-off drafter's `lead_lines`. It is never sent.
- **Screen:** `web/watch.js` at `#/changes`, linked from Find as "What changed this week". It reads `GET /watch`. Help has a new step.
- **Timer:** `perch-demo-monitor.timer`, Mondays at 06:00. It runs `perch monitor` inside the app container. `make demo-monitor` runs it at once.
- **Bench:** `make bench --render-only` keeps everything below a marker line in RESULTS.md, so the Scout sections are safe.

## Live result
- **Refresh:** 660 open NIH listings, 3 new.
- **Demo researchers:** PI-5, PI-4 and PI-2 had 0 changes, so there was no draft.
- **Why nothing fired:** their awards end 2028-07-31, 2016-06-30 and 2028-05-31, and none of the new listings entered a top 10.
- **A real draft elsewhere:** on a deleted copy of the store, A5052363442 (outside the alias table) got a real draft. Their NSF award 2303111 ends 2027-03-31.
- **Q25:** asks whether to add a researcher with a real trigger to the demo watch.

## Known gaps
- **Awards are not refreshed weekly.** The awards stage fetches only when no award is linked, so a new or extended award is missed until the store is refreshed.
- **Shared brief state:** the What changed screen links to the monitor's own brief, so visitors share its keep and dismiss state. A reused copy would avoid that.
- **Index writes:** the monitor runs as a second process on the demo store. A new opportunity is indexed by whichever process runs a brief first. Two processes writing LanceDB at once is untested.
- **From earlier sessions:**
  - The MCP server was not tested with a local Ollama agent.
  - A private brief does not index new opportunities.
  - The hand-off opening has no layer-2 check.
  - Replay mode has no compare, hand-off or watch.
  - Scout on Gemma sometimes states a count that the validator withholds.

## Next session: S17 — QA, freeze, package
1. Read S17 in `docs/PLAN.md`. Code freeze is Thu 5 Nov 12:00.
2. Rerun the Scout bench on the frozen build. `make bench --render-only` is now safe for RESULTS.md.
3. After the last test run:
   - Run `make decide-down`.
   - Tell the uracil session that GPUs 1 and 2 are free (see the local notes).
4. The privacy audit should include the monitor. It never runs on private sessions, and it writes only public digests.

## Open questions (mirror of bridge/QUESTIONS.md)
- Q21: private document shares. Default: proposal 0.5, direction 0.3, unpublished 0.2; the CV gets none.
- Q24: the new-opportunity trigger is the top-10 position rule. Default: as built.
- Q25: the demo watch has no draft yet. Default: leave it; the first scheduled run is Mon 2 Nov.
