# SCOUT_SPEC.md — Scout, specified from what Perch needs

**Status: approved 2026-10-30 (Q37). Phase 1 is S27; phase 2 waits until after Demo Day.** Dakshitha asked for Scout to be specified from the ground up, from this project's needs and not from patterns borrowed from other projects. This document replaces SPEC §8 once Dakshitha approves it (Q37). Until then the app runs as §8 describes.

Each item is marked:
- **Built:** the app does this today.
- **Proposed:** a change this spec asks for. It is not built.

## 1. What Scout is for

- **The situation:** a person has a finished brief open. They have a question the page does not answer directly, and they ask it in plain words.
- **The job:** Scout turns the question into calls on Perch's own tools, then writes a short answer that cites the records those tools returned.
- **The model's two jobs:** the model turns words into tool arguments, and it writes the cited answer. Everything else is code: the search, the filters, the eligibility rules, the comparison table and the checks on the answer.
- **What it adds to the brief page, part 1:** filters the page does not offer. Examples are an activity code, an award ceiling, a close-by date and words to include or leave out.
- **What it adds, part 2:** answers to "why" questions, such as why a lead fits or why an option is "may be eligible", built from records.
- **What it adds, part 3:** small chores across several steps, such as comparing the kept leads and then drafting a note to the right office.
- **Who uses it:** researchers on a researcher brief, students on a student brief, and MCP clients through the MCP server. The MCP server is a separate surface and is covered in section 9.

## 2. What Scout must never do

- **No outside reach (Built):** Scout cannot browse the web, run a shell or call anything outside its tool table.
- **Nothing is sent (Built):** Scout cannot send email or write to any outside system. Drafts are shown for the person to copy (standing rule 7).
- **No record changes (Built):** Scout cannot change a stored record. In a private session, store writes stay in the session's memory.
- **No invented numbers or dates (Built):** a number or date in an answer must come from a record the answer cites, or from the person's own question (standing rule 3).
- **No other person (Built, S28):** a Scout session works on the brief's own researcher or student only. Scout's own tools take no author id and it has no author search (section 4); only the MCP server keeps them.

## 3. The risks Scout actually has, and what controls each

Scout's tools only read records and write text on screen. So the risks are about wrong answers, money, privacy and wasted time, not about harmful actions.

- **Risk 1, invented facts (Built control):** the citation validator checks every answer against the records the tools returned. A failed answer is rewritten once. If it fails again, it is withheld and flagged.
- **Risk 2, money (Built control, with a gap):** Scout's own model must be local in a private session, and every web brief has been a private session since S23. Each session has a budget of 120,000 tokens and $0.25, and each question stops after 8 model calls. The Anthropic adapter also enforces the $100 cap to the demo.
- **The gap in risk 2:** in a session with Cloud on, `explain_fit` and `draft_handoff` use the session's Cloud model. Their cost is not counted in Scout's $0.25 session budget, and the daily Cloud cap counts briefs, not Scout steps. Only the 8-call cap, the hourly question limit and the $100 cap bound them. Section 5 closes this.
- **Risk 3, private text leaving the machine (Built control, amended S32 and S33):** Scout's model must be local in every private session. A session that holds documents can turn Cloud on only after a second warning that lists each document, and the consent is per document and per session (Q33). The model-backed steps, `explain_fit`, `draft_handoff` and `cover_points`, follow that choice. Every other student tool calls no model; `cover_points` is the one tool whose model reads the CV text, with contact details blanked, and only for the one record the student asks about.
- **Risk 4, wasted turns (Built control):** a call identical to an earlier one in the same question is answered from the earlier result and never run again. In S10's first bench run, Sonnet repeated one search up to nine times; the guard was added for that.
- **Risk 5, misreading the question (partly controlled):** the model may turn "small grants" into the wrong filter. The answer then looks right but quietly leaves leads out. The validator cannot catch this, because every cited fact is still true. Only the person can, by seeing how Scout read their question.

**What the per-step approval gate controls:** none of risks 1 to 4. For risk 5, it shows the filters before the step runs. But showing them after the step works just as well, because a step is a quick read with no effects, and a wrong one is fixed by asking again. So the gate costs a click per step and buys nothing the after-view does not.

## 4. How a question runs

- **One brief, one session (Built):** a Scout session belongs to one finished brief. It ends when the person ends their session.
- **The brief's leads are in context (Built):** the model sees the brief's ranked leads, so "the third one" means something.
- **Steps run at once (Built, S28):** every step runs as soon as the model asks for it. The "Ask before each step" mode and the Approve and Skip buttons are removed.
- **A Stop button (Built, S28):** while Scout works, a Stop button ends the question. The steps already done stay on screen. This is the one control a person needs during a run: to stop waiting.
- **Fixed subject (Built, S28):** in the web app, the researcher tools no longer take an `author_id`. They always use the brief's researcher.
- **No author search in the web app (Built, S28):** `resolve_author` leaves the web app's tool table. A brief already knows its researcher, so the tool has no use there. The MCP server keeps it, because an MCP client starts without a researcher.
- **Model policy (Built):** a model with good native tool calling uses it. A small model uses the structured policy, which asks for one JSON step per turn. On the S10 bench, qwen3:8b passed 17 of 20 tasks with native calls and 12 of 20 with the structured policy, so native stays the first choice.

## 5. Budgets

- **Per question (Built):** 8 model calls, after which Scout stops and says so.
- **Per session (Built):** 120,000 tokens and $0.25, counted for Scout's own model.
- **Cloud steps counted (Built, S28; `cover_points` added S33):** the session budget also counts the tokens and dollars of `explain_fit`, `draft_handoff` and `cover_points`. Their model calls already go through the audited provider, so the numbers exist; they are just not added in.
- **Per visitor (Built):** 30 Scout questions an hour, counted by IP address. Q35 asks whether per-IP counting suits Demo Day; the same answer applies here.

## 6. What the person sees

- **How Scout read the question (Built, S28):** above the answer, one line lists the steps and their filters as chips, for example "Searched opportunities: activity code R21, closes by 2027-03-01". This is risk 5's control, and it is the first thing the person reads after the question.
- **Step cards (Built, changed):** each step stays a card with its tool, filters, result line and records. The cards are collapsed under the "how Scout read it" line by default, because nobody needs to act on them.
- **Where a step ran (Built, S28; `cover_points` S33):** a card for `explain_fit`, `draft_handoff` or `cover_points` says "Local" or names the Cloud provider, matching the header chip.
- **Points on the card (Built, S33):** after `cover_points` runs, code writes the answer line and the full points sit on the card with a Copy button, as a hand-off draft does. The points are for the person to put in their own words; they never enter an export or a hand-off draft.
- **The answer (Built):** two to five short sentences. Each citation is a button that opens the record in the evidence rail.
- **A withheld answer (Built):** if the answer fails the check twice, the page says so plainly, and the step cards still show what Scout found.
- **Steps used (Removed, S27):** the side panel that counted steps went with the single-column chat. The eight-call limit is stated in Scout's welcome, under "What I will not do".
- **Lead results you can keep (Proposed, after Demo Day):** a search step's leads appear as short rows with a Keep button, so a filtered result can go straight to the shortlist.
- **Change a filter without the model (Proposed, after Demo Day):** removing a chip reruns that one search by code, with no model call, and updates the answer's step card.

## 7. Student Scout

- **Own tools (Built, S24; eighth tool S33):** students get eight tools: search_options, check_option, explain_verdict, read_cv, compare_options, draft_note, cover_points and get_record. The researcher tools are not on the student list, and the student tools are not on the MCP server.
- **Rules first (Built):** search_options, check_option, explain_verdict, read_cv, compare_options, draft_note and get_record return rule results, record fields and the fields code read from the CV. They call no model. The eligibility verdicts and the Still needed lists are rule results, and a note to an office is written by code.
- **Application points (Built, S33):** `cover_points` is model skill 4 on the student side. For one public fellowship or one sample scholarship, it returns 3 to 6 points for the application: each pairs what the record asks for or rewards, cited to the record, with what the student has that answers it, cited to the CV, the interests note or an achievement. It may list up to three things the record asks for that nothing the student added shows. It is the one student tool whose model reads the CV text, with contact details blanked, and only for the one record the student asks about. The old promise that no model reads the CV is withdrawn (Dakshitha, 2026-11-01, Q43); code still reads the CV by rule for eligibility.
- **Checked like a draft (Built, S33):** every point passes the citation validator (ids known; numbers and dates only from the cited record). A failed set is regenerated once, then withheld. The grounding model flags an unsupported sentence. Code writes the answer line, and the points sit on the card with Copy. They never enter an export or the note.
- **Private by construction, Cloud by choice (Built):** student Scout runs only in a private session. Scout's own model is local. `cover_points` runs on the session's models: local by default, and the cloud provider only after the student has turned Cloud on and confirmed the documents warning that names the CV (Q33).
- **Samples stay marked (Built):** sample scholarships are marked as samples in every tool result and in the answer's records. Points for a sample scholarship say they are for an invented sample, on the card and in the answer.
- **Same changes (Built, S28):** steps run at once, the Stop button, and the "how Scout read it" line apply to students too.

## 8. Records and logs

- **Public sessions (Built):** the Scout log keeps each tool call with its arguments and hashes of arguments and results. Questions and answers are kept as hashes only.
- **Private sessions (Built):** no Scout log is written, and the audit log stays in memory.
- **Replay (Built):** a public session can be replayed from its log, except steps that call a model or a live OpenAlex search.

## 9. The MCP server

- **Same researcher tools (Built; tenth tool S33):** the MCP server serves the ten researcher tools over stdio, with the same schemas. Through MCP, `cover_points` works from papers and public awards, because documents cannot be added through MCP.
- **The client writes the answer (Built):** the client's own model writes the answer, so every result carries a provenance map of the records to cite.
- **Its own budgets (Built):** 60 tool calls and 20 model-backed calls per connection.
- **Unchanged by this spec:** `resolve_author` and the `author_id` arguments stay on MCP, where the client starts without a researcher.

## 10. Draft review

- **Status (Proposed, not built):** checking a draft against what a record asks for was evaluated in S24 and not built. Q34 decides whether to build it. If built, it becomes a Scout tool under the same rules: code quotes the record, the grounding model only marks each point, and nothing is stored.
- **The advice-writing version is built (S33):** `cover_points` (sections 6 and 7) is the advice-writing version that Q32 asked about. It was built on 2026-11-01 under standing rule 5 as amended, which names application points as the fourth model job. The decision-only draft check above, where the grounding model marks a finished draft and writes no prose, stays unbuilt.

## 11. How Scout is evaluated

- **The bench (Built):** `bench/scout_tasks.yaml` holds scripted questions. A task passes when Scout used an allowed tool with the right arguments and its answer passed the validator.
- **Latest numbers (Built):** Sonnet passed 20 of 20 tasks with 0 wrong-tool calls in 27. Gemma passed 18 of 20. The sets are small: they show the follow-ups work, not a failure rate.
- **Misreading (Proposed):** the "right arguments" check already measures risk 5. The bench report gains one line per model: tasks where the filters were wrong but the answer still passed the validator. Those are the quiet misses section 3 describes.
- **After the change (Proposed):** S27 runs the Scout bench on the changed loop, and S28's final rerun uses it too.
- **Offline replay (Built, S49 Q0):** `python -m bench.scout_replay <run dir> --records <dir>` re-grades every stored draft with today's answer check. It calls no model and spends nothing. It rebuilds what the tools returned from the brief, the persona and the cited ids. With the s45g rules it reproduces all 206 stored removals. From S49 the open bench also stores each turn's tool log, so later replays are exact. `bench/scout_open.py --replay DIR` runs the same thing.
- **Guard set (Built, S49 Q1):** `bench/scout_guard.py` holds 24 sentences that must always be removed. Examples are an invented amount, a wrong rank, a sample cited with a public record and a fit word after a cited sentence. `tests/test_scout_guard.py` fails if any one passes. Every change to the answer check is measured against it.
- **What the answer check allows since S49:** a fixed section name with no colon (Q4). A bold numbered record title kept whole, at any length when it is the title of a record cited under it (Q5). The disclaimer followed by "so check with ..." (Q6). A few more section names (Q9). An offer that names a record returned this turn (Q10). An empty-state line with a "to add ..." tail (Q11). A rank number that matches the brief (Q7). An uncited sentence right after a cited one in the same prose, checked against that record; a fit word, an eligibility word or a sample's citation is never inherited (Q3). The brief itself is a record, `[user:brief]`, and each search is one, `[search:N]` (Q2).
- **The next real run (Prepared, S49 Q13 and Q15):** the prompt now asks for one fact per sentence with no "so ..." tail, an id on every bullet, `[user:brief]` and `[search:N]` for whole-brief and search facts, a colon after every heading and no narration of steps. Run once, under the $1.30 cap: `python -m bench.scout_open --tag s49 --max-usd 1.30 --no-old --spread --brief <researcher brief JSON>`. The brief JSON is a stored demo researcher brief from `GET /briefs/{id}`, with a pinned as-of date; `--spread` keeps one record per close date where no brief is given, such as the student side. Then compare first-draft removals by reason with s45g, and report dollars per in-scope answer.

## 12. What changes from today

**Phase 1, built in S28, before the freeze:**
- **Remove the gate:** drop the ask mode, the Approve and Skip buttons and the mode switch, in the loop, the hub, both APIs and `web/scout.js`.
- **Add Stop:** end the current question between steps and keep what is done.
- **Fix the subject:** drop `author_id` from the web app's researcher tool schemas and drop `resolve_author` from its tool table, keeping both on MCP.
- **Count Cloud steps:** add `explain_fit` and `draft_handoff` spend to the session budget.
- **Show where a step ran:** label the two model-backed cards Local or Cloud.
- **Add the "how Scout read it" line:** and collapse the cards under it.
- **Update the words:** Help, the Scout hint line, the canvas copy in `docs/design/redesign/`, SPEC §8, including its Stack line that names the borrowed approve-every-action pattern.
- **Mock-up:** the redesign canvas has a working mock-up of this spec, `docs/design/redesign/ScoutProposed.dc.html`.
- **Retest:** tests, the UX walk and the Scout bench rerun.

**Phase 2, after Demo Day:**
- **Keep from a search step:** lead rows with Keep buttons.
- **Edit a filter by code:** remove a chip to rerun one search with no model call.
- **Draft review:** only if Q34 says build it.
