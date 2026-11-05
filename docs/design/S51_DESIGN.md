# S51 design: round 3 build spec (2026-11-05)

This spec turns the three round 3 reviews into one last build before the release. It reuses the S50 conventions: the walk-flow loader, the package rules in S50_DESIGN.md section 3.1, the S49 rules that section points to, and the shared-contract style ("A styles it; A and B emit it").

Item codes refer to these documents:

- **W1 to W39:** `S51_UIUX_REVIEW.md`.
- **D1 to D33:** `S51_PRODUCT_REVIEW.md`.
- **H1 to H20:** `S51_FUNCTION_REVIEW.md`.
- **LIVE:** the real-model capture in `build/s50_live/LIVE.md`.

The walk researcher is PI-4 (A5026494099). The live capture is PI-1 (A5063022331). No other researcher is named here.

## 1. Decisions

The orchestrator records each of these in `docs/DECISIONS.md` when the spec is accepted.

- **Centre and programme grants get their own group (H7, D3, decided 2026-11-05):**
  - **The field:** `Lead.group` widens to `Literal["temple_internal", "centre"]`.
  - **The route:** a centre lead stays on route A. `routeOf` in `web/app.js` already maps only `temple_internal` to the Temple tab, so it needs no change.
  - **Which codes:** exactly P30, P01, P50 and U54, read from `opportunity.activity_code`. The builder does not add codes from memory. Adding any other code needs NIH's public activity-codes page read first, with its URL recorded in `docs/SOURCES.md`. That is after release.
  - **What stays the same:** `rank` and `match_score` do not change, and neither does the Match pill. Inside the group, the cards keep the list's own order.
  - **The fold:** the front end draws these leads in a fold named "Centre and programme grants (N)". It sits below the single-lab cards and below the "Show N more" fold.
- **Accounts can be marked closed (D4, D5):**
  - **The setting:** a new setting, `PERCH_ACCOUNTS_OPEN`, defaults to `1`. The orchestrator sets it to `0` in `.env.deploy` when it updates the deploy, because self-registration is off there.
  - **The field:** `/auth/session` returns it as `accounts_open`.
  - **What changes on screen:** while accounts are closed, the landing's second button starts the guest sample. The Scout and hand-off walls also lead with the example.
  - **What stays:** the header's quiet "Sign in" link, so the presenter can still sign in.
- **The fit verdict goes on the researcher card's face (W13):**
  - **The face:** the model's inference sentence now sits right under the facts, labelled "Why it fits:" or "How it relates:", with the "Inference" tag.
  - **The disclosure:** the "what the call funds" sentence moves inside it.
  - **Which cards start open:** with a CV in the brief, only the first card starts open (W14). This revises the S27 rule that every card starts open.
  - **The reason:** the verdict is now on every card's face.
- **One paper per "you" sentence in cover points (H1):**
  - **The rule:** a `you` sentence that cites papers must cite exactly one.
  - **Where it is checked:** the cover skill's `validate`. A sentence that cites two or more fails, and the set is regenerated once, as rule 5 says.
- **A name-only student listing gets no model call (H4, D6):**
  - **Which listings:** an empty purpose, empty `eligibility.notes` and an empty `field_of_study`.
  - **What the card shows:** a code-written line in `lead.notes`, not in `explanation`. So the card never calls it model text.
- **Student entry labels (H9, W20, D14):**
  - **One entry:** the label is "Your entry".
  - **Several entries:** each is "One of your entries".
  - **The interests note:** "Your interests note".
  - **The sample student:** the labels read "the sample student's" in place of "your".
- **The precache key carries a rules version (H8):** the key gets `RULES_VERSION = "2026-11-05.1"` from `perch/eligibility.py`. Every later change to a rule bumps it.
- **The sample's canary tokens are hidden in the boxes (W3, D17; DECISIONS 2026-11-05, revised):** "Load sample" fills the boxes without the canary line. Save adds it back, so the stored text keeps it.
- **The guest budget line (D16):**
  - **When it shows:** when a brief's explanation stage was skipped by the model budget.
  - **Where:** one line above the list, on both sides.
  - **How the front end knows:** it reads the stage's own `detail`, which code writes as `BUDGET_DETAIL`. No new field is added. A back-end test pins the text.
- **Run again shows once (W5):**
  - **While building:** the header's "Run again" is hidden while the brief is queued or running.
  - **After a stop:** it is also hidden after the user stopped the brief, because the progress card shows its own.
  - **On My Perch:** the order is Open, Run again, Stop (W12).
- **One name for one order (W8):** the compare sort's first option reads "Best match".
- **W26 is dropped:** on the deploy every model role is Anthropic. `loop.py:687` therefore sets `where="cloud"`, and the tag already reads "Cloud: Anthropic". The review's wording, "Perch's own server", would be false.

### For Dakshitha

- **D9, whose name goes on the projector:**
  - **The risk:** a live researcher brief shows a real Temple researcher's name, and its hand-off is written in that person's first person. Nothing records that the person agreed to appear on stage.
  - **Recommendation:** for the researcher side on stage, present the aliased example (`example.html`). If Dakshitha has a researcher who has agreed, present that person's brief instead. Do not search a stranger's name live.
  - **Effect on this spec:** none. It changes the run sheet only.

## 2. Scope for round 3

The cap is about 3 hours of builder time, for three builders in parallel. **Tier A** is the must-fix work and ships. **Tier B** is ranked polish and ships only under budget, cut from the bottom.

- **Tier A is about 230 minutes of builder time, about 50 over the cap:**
  - **The packages:** BE about 110 minutes, FE-A about 65 and FE-B about 55.
  - **Wall-clock:** with three builders in parallel, this is about 2 hours, and BE is the binding package.
  - **The must-fix list alone:** the review estimates for H1, H4, H5, H7, H8 and H9 add up to about 5 hours. The scopes below are the smallest safe versions of each.
- **What the cuts remove:** cuts 1, 5 and 6 are polish. Cuts 2, 3 and 4 remove must-fix work. They are offered only because the must-fix set alone is over the cap.
- **The next polish cut:** if BE runs long, W19 (the unsupported fold) is the next one. It is Tier A in both front-end packages, but it is not a must-fix.
- **The cut line, to reach about 180 minutes.** Cut in this order:
  1. **FE-A, W13:** the card keeps "what it funds" on its face. This saves 15 minutes.
  2. **BE, W7's instrument row:** keep the "no written reason" wording, and leave the row in. This saves 5 minutes.
  3. **FE-B, W12:** My Perch rows keep their current order. This saves 8 minutes.
  4. **BE, H9:** the front end's W20 mapping still fixes the id form, but titles stay "Your achievement A" in the model text. This saves 10 minutes.
  5. **FE-A, the D16 line on the researcher side:** the student side keeps it, since that is the audience path. This saves 5 minutes.
  6. **FE-B, help:** help keeps only the centre-grant sentence and the budget sentence. This saves 6 minutes.

### Must-fix coverage

- **UI/UX review:**
  - W1 and W2 are A1.
  - W3 is B1.
  - W4, W5 and W6 are A2.
  - W7 is BE7.
  - W8 is B4.
  - W9 is B4.
  - W10 and W11 are A1.
  - W12 is B5.
- **Product review:**
  - D1 is the release session; see section 3.6.
  - D2 is H1.
  - D3 is BE2 and A3.
  - D4 is BE8 and A4.
  - D5 is B2.
  - D6 is BE3, with the ordering question in Limits.
  - D7 and D8 are run-sheet steps for the orchestrator.
  - D9 is for Dakshitha, above.
  - D10 is the release docs: the README "See it" line and tracking the student example.
- **Function review:**
  - H1 is BE1.
  - H4 is BE3.
  - H5 is BE4.
  - H7 is BE2.
  - H8 is BE5.
  - H9 is BE6.
  - H2, the re-capture, is the orchestrator's after the merge, with `again=true` and a new idempotency option.
  - H3 is done by the decision that raised the guest budget.
  - H6 is BE Tier B.

### Deferred, with reasons

- **W14's line clamp:** W13 moves the long sentence into the disclosure, so the clamp is not needed. Only the "first card open" half ships, in A3.
- **W15 to W19, W21 to W25 and W27 to W34:** these are Tier B in their packages, in rank order. What does not ship goes nowhere: none of them is a limit a user meets.
- **W26:** dropped (section 1).
- **W35 to W39 and D26 to D33:** both reviews date these after Demo Day.
- **D11 and D12, Scout's tails and mixed lists:** these touch the Scout prompt, and a prompt change needs a paid bench to check. They go in Limits.
- **D13, expiry shown as a deadline:** the researcher card already labels an expiry "Announcement" (`web/app.js`, the `expires` branch). QA checks the P01 card after H2's re-capture. It is not built.
- **D18, old Temple calls:** S50's G5 rule should already leave them out. QA checks after H2.
- **D19, industry ids:** QA checks the CSV, the JSON export and the compare table after H2.
- **D20, the same papers on most cards:** not measured since 3b landed (H14). It goes in Limits.
- **D21, awards list order:** it needs a server sort parameter. It goes in Limits.
- **D25, Run again next to Export:** the presenter avoids it. It goes in Limits.
- **H13, Scout headings, and H12, cover wording:** these are BE Tier B.
- **H15, the free Scout replay:** the orchestrator runs it on CPU after BE merges, through `scripts/run_limited.sh`.

## 3. Build packages

### 3.0 Step 0, done by the orchestrator before any builder starts (about 5 minutes, one commit)

- **Walk flow files:** create `scripts/walk_flows/s51_fe_a.py` and `s51_fe_b.py`. Each holds `def register(U): return {}, []`.
- **Who owns which flow file:**
  - **FE-A:** `s51_fe_a.py`, `s50_fe_a.py` and `s49_fe_a.py`.
  - **FE-B:** `s51_fe_b.py`, `s50_fe_b.py`, `s50_fe_c.py`, `s49_fe_b.py` and `s49_be_s.py`.
- **The walk server:** start it with `PERCH_SCHEDULER=0`, as in S50.
- **No other shared file is touched in Step 0.** Each contract in 3.2 is read with a safe default, so each package works before the others merge.

### 3.1 Rules for every package

S50_DESIGN.md section 3.1 applies unchanged: isolation, fail first, one walk server on port 8191 through `scripts/run_limited.sh`, worktrees without the example files, and stubs for missing contracts. Three additions:

- **Walk checks are lean:** at most six new checks per front-end package. Each one is listed below. Each must fail on the branch before the change, and the builder notes the failing value in the hand-back.
- **Old checks this round breaks on purpose:** the builder lists them in the hand-back, and the orchestrator edits `scripts/ux_walk.py` after the merge. These are known now:
  - **The weak fold's summary text:** it now reads "Show N more" (A3).
  - **The compare sort's first option text:** it now reads "Best match" (B4).
  - **The My Perch link text:** "Change details and run again" now reads "Run again" (B5).
  - **Any check that expects "Canary:" in a Load sample box:** the line is hidden now (B1).
- **The back-end builder runs `make test`.** It does not run the walk. Each front-end builder runs `tests/test_web.py` and its own walk flows.

### 3.2 Shared contracts

#### Lead group for centre grants (BE builds it; FE-A reads it)

```json
{"id": "...", "route": "A", "group": "centre", "rank": 1, "match_score": 82,
 "notes": ["Centre or programme grant (activity code P30). An institution applies for these for a centre or a group of projects, so Perch lists them below the single-lab grants."],
 "opportunity": {"activity_code": "P30", "...": "..."}}
```

- **The note:** BE writes it, with the code filled in from the record. FE-A shows it through `leadNotes`, as it already does for every note.
- **The default:** a lead without `group` is a single-lab card.

#### Accounts open (BE builds it; FE-A reads it and passes it on; FE-B reads it from ctx)

- **`GET /auth/session`:** every response shape (signed out, guest and signed in) gains `"accounts_open": true|false`.
- **FE-A:** adds `accountsOpen: S.session.accounts_open !== false` to every ctx object it builds:
  - the Scout ctx at `web/app.js:1365`;
  - the hand-off ctx at `:1355`;
  - `coverCtx()` at `:2100`;
  - the student ctx passed to `studentRoutes` at `:1341`.
- **FE-B:** reads `ctx.accountsOpen !== false`. A missing field means open, so nothing changes before the merge.

#### The budget line (FE-A emits it on the researcher list; FE-B emits it on the student list; FE-A styles it)

- **When it shows:** the brief's `explanations` stage (researcher) or `student_explanations` stage (student) has `status: "skipped"`, and its `detail` starts with `"withheld: the daily model budget"`.
- **Markup:** `p.notice.info.list-note[data-budget]` with `icon("info")` and this text: "Written reasons are paused: this session’s model budget for today is used. The list, dates, amounts and rule results are not affected."
- **Where it goes:** in the list's notices slot, first in the slot. When it shows, the withheld-reason note does not.

#### The unsupported-sentence fold (FE-A styles it; FE-A and FE-B emit it) (W19, Tier A for both)

```
details.unsupported-fold
  summary[data-key=unsupported]   "1 sentence could not be matched to its source" / "N sentences could not …"
  ul > li (each sentence, as it came)
```

- **What it replaces:** the amber `div.notice.warn` on the researcher card (`web/app.js`, in `explanationBlock`) and on the student card (`web/student.js:487`).
- **CSS (FE-A, `styles.css`):** `.unsupported-fold summary { color: var(--ink-2); font-size: var(--fs-14, 14px); min-height: 44px; display: flex; align-items: center; } .unsupported-fold ul { margin: 4px 0 0; padding-left: 20px; color: var(--ink-2); }`.

### 3.3 Package BE: back end (Tier A about 110 minutes)

**Files BE may touch:**

- `perch/skills/cover.py`
- `perch/validate.py`
- `perch/eligibility.py`
- `perch/precache.py`
- `perch/service.py`
- `perch/student.py`
- `perch/skills/fit.py`
- `perch/schemas.py` (the `Lead.group` literal only)
- `perch/compare.py`
- `perch/auth/routes.py`
- `perch/config.py`
- `.env.example`
- the cover prompt file, if it is not in `cover.py`
- new `tests/test_s51_*.py`
- existing tests that pin a string this package changes

**BE must not edit:** `web/`, `scripts/`, the `docs/` files, `.env` or `.env.deploy`.

**Escalate instead of guessing:**

- a database or JSON-schema constraint on `group`;
- a back-test path that reads `group` or the brief's display order;
- a skill test that needs a paid call.

#### BE1. H1: one paper per "you" sentence (30 minutes)

- **Validate:** in `validate` (`perch/skills/cover.py:348`), a `you` point whose citations hold two or more paper ids (`W…`) fails, with the reason "cites more than one paper; name one paper and one fact".
- **Prompt:** "Each ‘you’ point names one paper and one fact from it, as ‘Your paper reports …’. Do not add a judgment after it, such as ‘which shows …’."
- **`YOU_SUBJECT` (`:255`):** it also matches `your papers?`.
- **`as_record_claim`:** turns "You have" into "The paper has", and "Your paper(s) report(s)" into "The paper reports".
- **Tests:**
  - "Your paper reports X" becomes "The paper reports X".
  - "You have work on X" becomes "The paper has work on X".
  - A two-paper point fails `validate` with the reason above.
  - A one-paper point passes.
- **Not in this round:** the optional `link` field.

#### BE2. H7: centre and programme grants (25 minutes)

- **`perch/eligibility.py`:** add `CENTRE_CODES = frozenset({"P30", "P01", "P50", "U54"})`, with a comment that points to this spec.
- **Where the group is set:** where route A leads are built in `perch/service.py`, set `lead.group = "centre"` for each lead whose `opportunity.activity_code` is in the set. Append the note from 3.2. Do it on the fresh path and on the precache path; the Temple internal group is computed live at `service.py:456`, so follow that pattern.
- **What it must not change:** `rank`, `match_score` and `explanation`.
- **The back-test:** confirm that `bench/` reads `rank`, not the group or the shown order, and say so in the hand-back. The orchestrator re-runs the back-test in the release session.
- **Tests:**
  - A P30 lead gets `group: "centre"` and the note, and its rank is unchanged.
  - An R01 lead gets no group.
  - A Temple internal lead keeps `temple_internal`.

#### BE3. H4: name-only student listings (15 minutes)

- **In `_run_student_explanations` (`perch/service.py:706`):** leave out of `explain_leads` every lead whose scholarship has all three of these:
  - an empty purpose, after the canary tail is removed;
  - empty `eligibility.notes`;
  - an empty `field_of_study`.
- **For each such lead:** append "This listing gives only the award’s name. Read its page for what it funds." to `lead.notes`. Leave `explanation` and `inference` as `None`.
- **The stage detail:** it gains ", K name only" when K > 0.
- **Test:** a name-only listing makes no model call and gets the note.

#### BE4. H5: nested record fields in `evidence()` (10 minutes)

- **In `perch/validate.py:101–118`:** walk dict values recursively, and add the ints and floats inside lists to the allowed numbers.
- **Test:** "It asks for a GPA of 3.50" passes against a record with `eligibility.gpa_min = 3.5`. "The record lists class years 1, 2 and 3" passes against `class_year = [1, 2, 3]`.

#### BE5. H8: a rules version in the precache key (5 minutes)

- **The change:** `RULES_VERSION = "2026-11-05.1"` in `perch/eligibility.py`, added as one more part of `precache_key` (`perch/precache.py:64`).
- **Test:** the key changes when the version changes.

#### BE6. H9: student entry labels (10 minutes)

- **The titles at `perch/student.py:551` and wherever signed-in entries become records:**
  - one achievement: "Your entry";
  - several: "One of your entries";
  - the interests note: "Your interests note".
- **`SAMPLE_WORDS` (`perch/student.py:701`):** add "One of your entries" → "One of the sample student's entries", "Your entry" → "The sample student's entry" and "Your interests note" → "The sample student's interests note".
- **H11 and D22 in the same commit:**
  - "rules you out" now becomes "rules the sample student out".
  - The staff rule's line now reads "Students: not a staff or faculty award."
- **Test:** the rendered finding for `user:achievement-a` contains no "achievement A". The sample wording reads "the sample student".

#### BE7. W7: compare wording (10 minutes)

- **`perch/compare.py:113`:** on a brief whose explanation stage is done or skipped, "no explanation yet" becomes "no written reason".
- **The instrument row:** leave the "Instrument or relationship" row (`:30`) out when every column is a grant (route A).
- **Test:** both cases.

#### BE8. D4: accounts open (5 minutes)

- **The setting:** `settings.accounts_open()` reads `PERCH_ACCOUNTS_OPEN`, default `1`.
- **`.env.example`:** add `PERCH_ACCOUNTS_OPEN=1  # 0 when self-registration is off; the landing and the walls then lead guests to the sample and the example`.
- **`perch/auth/routes.py`:** the three `/auth/session` shapes include `"accounts_open"`.
- **Pin `BUDGET_DETAIL`:** add a test that `perch/service.py`'s `BUDGET_DETAIL` starts with `"withheld: the daily model budget"`, because the front end matches it.
- **Test:** the signed-out session shows `accounts_open: false` with the setting at `0`.

#### BE9. Tier B, in order

1. **H10 (5 minutes):** `CHOSEN_PAPERS["student"] = 1` (`perch/skills/fit.py:96`), and update its tests.
2. **H6 (20 minutes):** the merged-award amount carry-over in `student_pool` (`perch/student.py:631`), as the function review specifies. Test with one group whose kept copy has no amount.
3. **H12 (10 minutes):** `COVER_NOTE` says "your CV, entries or papers", and the missing items say "nothing in your records shows it". This is in `perch/scout/web.py`, which BE may touch for this item only.
4. **H13 (10 minutes):** add the comparison, side-by-side and soonest heading forms to `STRUCTURAL_HEADINGS` (`perch/scout/answer.py:117`). BE may touch it for this item only.

#### BE correctness items: added by the orchestrator

From `docs/design/S51_BACKEND_REVIEW.md`. E1 (guest session budget) and E3 (realm lockout and password) are already done by the orchestrator; E6 too.

- **E2 (must-fix, 30 minutes):** reserve worker capacity for the presenter. Of the worker's threads, keep at least two that take only `scout`, `cover_points` and `handoff` jobs (and purges), so a queue of audience briefs never delays them. Make the split a setting with that default (`PERCH_WORKER_FAST_THREADS=2`), document it in `.env.example` and docs/deploy.md, and test that a fast job is claimed while every brief thread is busy. Files: `perch/jobs.py`, `perch/cli.py`, `.env.example`, `docs/deploy.md`.
- **E4 (should-fix, 20 minutes):** a guest brief with explanations off must still count against the guest's limits, and the `guest_job` limit must be per address as the Demo Day decision assumed (or a second per-address scope added); test both. Files: `perch/api.py` (the brief submit path only), `perch/redisx.py`.
- **E5 (should-fix, 10 minutes):** Scout's `get_record` must never show "None (the record's own words)": with a placeholder date and no note, say the record states no closing date. Test on a record with a far-future date and no note. File: `perch/scout/read_tools.py` (this item only).
- **Other E-items:** do the remaining should-fix items in the review's order only if time is left after the H-items; list the rest for the Limits section.

### 3.4 Package FE-A: researcher brief, card, landing, example page, base styles (Tier A about 65 minutes)

**Files FE-A may touch:**

- `web/app.js`
- `web/styles.css`
- `web/example.js`
- `web/example.html`
- `web/format.js`
- `web/dom.js`
- `tests/test_web.py`
- `scripts/walk_flows/s51_fe_a.py`, `s50_fe_a.py` and `s49_fe_a.py`

**FE-A merges first:** it owns the CSS that FE-B's markup uses.

#### A1. Phone and landing CSS (W1, W2, W10, W11) (10 minutes)

- **W1, the example banner:**

  ```css
  @media (max-width: 599px) {
    .example-banner .banner-line { flex-wrap: wrap; }
    .example-banner .banner-line > span { flex-basis: 100%; order: 3; }
  }
  ```

- **W2, the compact progress card:** under 600 px, `.progress.compact .replay, .progress.compact details { grid-column: 1 / -1; }`. Use the real selectors from the replay link and the Steps disclosure.
- **W10:** `.landing .hint-row { align-items: center; }`.
- **W11, the brief's chip row:** under 600 px, `.filter-box .filter-chips { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; margin: 0 -16px; padding: 0 16px; }`. This overrides line 1552 inside the phone media block.
- **Fail-first walk checks:**
  - **`s51a_example_banner_w360`:** stub the example file as in S50 3.1. At 360 px, the banner's text `span` is at least 300 px wide.
  - **`s51a_brief_chips_one_row_w360`:** on the stubbed PI-4 brief, every chip in `.filter-box .filter-chips` has the same `offsetTop`.

#### A2. The brief while building and after a stop (W4, W5, W6) (10 minutes)

- **W4:** in `renderRoutes` (`web/app.js:1702`), draw `skeleton(3), skeleton(3)` only when the brief is not failed.
- **W6:** the waiting hint reads "What Perch read fills in first."
- **W5:** the header's "Run again" is not drawn in either of these cases:
  - `S.brief.brief.status` is `queued` or `running`;
  - the brief failed and `S.stoppedId === S.briefId`.
- **Fail-first walk check `s51a_stopped_once`:** reuse the `s50a_building` stub, and stop the brief. Count only visible `button` and `a` elements whose trimmed text is exactly "Run again". The hint "Run again builds a new one." must not count. Two things must hold:
  - **On the stopped screen:** no `.skeleton` is in the routes panel, and the count is exactly 1.
  - **While building:** the count is 0.

#### A3. Cards and the list (H7 front end, W13, W14, W19, W21) (25 minutes)

- **The centre fold:**
  - In `renderRoutes`, take `l.group === "centre"` out of `active` before the `OPEN_FIRST` slice.
  - Draw them in a new `div.centre-box` after `.weak-box`. It holds a `details.weak-fold.centre-fold` with the summary "Centre and programme grants (N)", `data-key=centre-fold`, closed by default and remembered in `S.centreOpen`.
  - Under the summary goes one `p.hint`: "Centres and programmes of several projects apply through the institution. Each card says why it is here." Then the `ol.leads`.
  - The tab count and the list heading still count these leads.
  - The agency and code chips still filter them, through the same `passes` rule as every other card.
- **W21:** the weak fold's summary becomes `Show ${n} more`.
- **W13, the verdict on the face:** in `explanationBlock`, when `l.inference` is present, the card's face shows:

  ```
  p.fit-why
    b  "Why it fits: "  (or "How it relates: " in the weak band, the rule the summary already uses)
    renderSegs(...)  the inference, as inferenceBox renders it now
    span.tag.model  "Inference"
  ```

  - **Inside the disclosure:** the `p.what` sentence, now the first child, then the findings, the unsupported fold and the eligibility rows. `inferenceBox` is no longer drawn inside it.
  - **The summary text:** it stays as it is.
  - **When there is no inference:** the face keeps `p.what`, as it does today.
- **W14:** with a CV in the brief, only the first card in the shown order starts open. The rest follow `S.open`.
- **W19:** emit the unsupported fold from 3.2 in place of the warn notice, and add its CSS.
- **Fail-first walk checks:**
  - **`s51a_centre_fold`:** stub one lead with `group: "centre"` and the note. The card is inside `.centre-fold`, not in the top list. The summary reads "Centre and programme grants (1)". Opened, the card shows the note.
  - **`s51a_fit_on_face`:** on a stubbed card with `inference`, `.fit-why` is visible while the card's `details.why` is closed.

#### A4. Landing and ctx (D4, D16, W25) (10 minutes)

- **D4:**
  - **The new case:** in `renderFind` (`web/app.js:397-406`), when not signed in, not a guest and `S.session.accounts_open === false`, use the `S.signinDown` branch's button: "Try a sample student", which calls `startGuest`.
  - **The guest line:** it is not drawn in that case, as with `signinDown`.
  - **The header:** its "Sign in" stays.
- **ctx:** add `accountsOpen` to the four ctx objects listed in 3.2.
- **D16:** in `drawNotices`, put the budget line from 3.2 first when the `explanations` stage matches. In that case leave out the withheld note.
- **W25:** `exampleSlot` reads "See an example brief" on both sides.
- **Fail-first walk check `s51a_accounts_closed`:** stub `/auth/session` as `{"signed_in": false, "accounts_open": false}`. `[data-key=fit]` reads "Try a sample student" and is a `button`. `#sign-in` is still visible.

#### A5. Tier B, in order

1. **W22 (5 minutes):** one `p.hint.match-hint` under the list head: "Match: how closely the call’s text matches the papers, out of 100. It is not the odds of funding."
2. **W15 (5 minutes):** the Dismiss button becomes `btn quiet`. Add `.lead-foot:not(:has(.cover)) { border-top: 0; padding-top: 4px; }`. Both buttons keep 44 px.
3. **W31 (3 minutes):** `orgCard` draws the "Inference" line only when `l.inference` is set.
4. **W23 (5 minutes):** at 600 px and wider, the Compare tab's long label reads "Compare and draft (N)". The phone keeps "Compare".
5. **W33 and W34 (8 minutes):**
   - The award horizon reads "Last federal award ended <date>" at section-title size.
   - The thread subtitle reads "<n> % of the papers’ weight. Newer papers count more."

#### A6. What the example page needs from a fresh export (D1; release session, no builder work)

- **What the page reads:** `example.js` reads `web/example/<side>.json`, a replay file with `version`, `brief`, `candidates`, `records`, `kept`, `compare`, `handoffs` and `scout`. The page code needs no change for a fresh file.
- **What a fresh researcher file must hold to show this round's work:**
  - `group: "temple_internal"` and `group: "centre"` on the leads that have them, with their `notes`;
  - `inference` on the top cards, so W13's line shows;
  - two kept single-lab leads, and a hand-off draft for them in `handoffs`;
  - two Scout answers in `scout`, made by the deploy's model, not a local one;
  - the researcher shown by alias in `candidates` and in every text field.
- **What a fresh student file must hold:**
  - `checks` on every lead;
  - `notes` on name-only listings;
  - `options.persona`, so the sample wording applies.
- **What the example does not show:** cover points. The replay API has no `coverStart`, so `coverBlock` draws nothing (see Limits).
- **The risk:** `scripts/export_replay.py` runs the old API through `TestClient` against a `--db` SQLite store, and it was never verified against the Postgres deploy. The release session needs a path that reads a finished brief from the deploy as the SYNTHETIC presenter account. One option is `scripts/live_capture.py`'s signed-in client, plus the alias step and the real-name check from `export_replay.py`. Plan time for this in the release session.

### 3.5 Package FE-B: student screens, walls, cover, Scout, hand-off, My Perch, compare, help (Tier A about 55 minutes)

**Files FE-B may touch:**

- `web/student.js`
- `web/sample_student.js`
- `web/cover.js`
- `web/scout.js`
- `web/handoff.js`
- `web/account.js`
- `web/compare.js`
- `web/help.js`
- `web/pages.css`
- `scripts/walk_flows/s51_fe_b.py`, `s50_fe_b.py`, `s50_fe_c.py`, `s49_fe_b.py` and `s49_be_s.py`

FE-B uses FE-A's classes from 3.2. Any new CSS it needs goes in `pages.css`.

#### B1. W3 and D17: canary hidden in the Load sample boxes (15 minutes)

- **`fillSample` (`web/student.js:256`):** fills each box with `noCanary(text)`. The tag "SYNTHETIC example" still shows.
- **Before each save of a box's text:** if the text starts with `SYNTHETIC example student (invented).` and holds no `Canary:`, put the box's token back on the first line. The result reads `SYNTHETIC example student (invented). Canary: <token>`, exactly as in `sample_student.js`.
  - **The tokens:** take them from `SAMPLE_STUDENT` with a regex, not a copy.
  - **What else it touches:** nothing.
- **Fail-first walk check `s51b_sample_no_canary`:** after Load sample, no box's `value` contains `PERCH-CANARY`. Then press Save against a stubbed save route. The captured request body contains `PERCH-CANARY-UG-CV-3R8D`.

#### B2. D5: the walls lead to the example (15 minutes)

When `ctx.accountsOpen === false`:

- **Scout wall (`web/scout.js:83-95`):**
  - **Lede:** "Ask Scout needs an account."
  - **Hint:** "Accounts are not open yet. See what a signed-in user gets in the example."
  - **The main action:** `a.btn.primary[data-key=example-scout]` "See an example answer", linked to `example.html?tab=scout`. It shows only when `exampleAvailable` resolves true; otherwise there is no button.
  - **Under it:** a `quiet-link` "Sign in", for the presenter.
- **Hand-off wall (`web/handoff.js:139`):** the same pattern, with "See an example draft" linked to `example.html?tab=compare` and the same hint line.
- **Cover list line (`web/cover.js:165`):** for a guest, "Cover-letter points need an account, and accounts are not open yet." It has no link, because the example shows no cover points.
- **When accounts are open:** today's walls are unchanged.
- **W27, in the same edit:** the Scout wall sits in the chat's centred column. In `pages.css`: `.scout-wall { max-width: 870px; margin-inline: auto; }`, or the chat column's real width.
- **Fail-first walk check `s51b_walls_closed`:** stub `accountsOpen` false through a stubbed `/auth/session` on a guest session, and stub the example file. Three things must hold:
  - the Scout tab's first `.btn.primary` is `[data-key=example-scout]`;
  - the Compare tab's guest draft area has `[data-key=example-draft]` as `.btn.primary`;
  - neither wall has `.btn.primary` pointing at sign-in.

#### B3. Student cards (W19, W20, D16) (10 minutes)

- **W19:** emit the unsupported fold from 3.2 at `web/student.js:487`.
- **W20:** `plainExplanation` maps `achievement-x` to "one of your entries", or "one of the sample student's entries" on a sample brief. It maps `interests` to "your interests note", as now.
- **D16:** in `studentRoutes`, the budget line from 3.2 goes first in the notices when the `student_explanations` stage matches. In that case leave out the flagged note.
- **Fail-first walk check `s51b_student_budget`:** stub the student brief's `student_explanations` as `{"status": "skipped", "detail": "withheld: the daily model budget is used"}`. `[data-budget]` shows, and `[data-withheld]` does not.

#### B4. Small wording (W8, W9) (4 minutes)

- **W8:** `web/compare.js:64`: "Perch’s order" becomes "Best match".
- **W9:** `coverListLine` (`web/cover.js:159`), for `audience: "student"` on a sample brief, says "A model writes these from the sample student's CV and entries. You put them in your own words."
  - **How cover.js knows:** read `ctx.sample`, which `student.js` sets from `SAMPLE_STUDENT` when it builds the ctx it passes.

#### B5. W12: My Perch rows (8 minutes)

- **The order (`web/account.js:351-359`):** Open, then Run again, then Stop last, only while busy.
- **The link:**
  - **Visible text:** "Run again".
  - **`aria-label`:** "Change details and run again".
  - **The class:** it keeps `quiet-link`.
- **The announcement after Stop:** "Stopped. Run again builds a new one."
- **Fail-first walk check `s51b_myperch_order`:** on the stubbed busy row and on a done row, "Run again" has the same x position.

#### B6. Help (`web/help.js`) (10 minutes)

The sentences are in section 4. FE-B checks each one against the merged code before it closes B6. Where a sentence depends on FE-A or BE work, it checks after the merge, or it leaves that sentence out and says so in the hand-back.

#### B7. Tier B, in order

1. **W17 (5 minutes):** extend `neither` (`web/student.js:463`) to `temple_pages` records, with the text "The page gives neither. Check the award’s own page." Also give `.fact-wide dd` a regular weight in `pages.css`.
2. **W18 (5 minutes):** the "Every option below" note shows only `unknown` and `fail` lines.
3. **W16 (5 minutes):** leave out the `unknown` deadline check on a card whose facts already say there is no deadline. Check the rule id in `perch/student.py` first.
4. **W30 (1 minute):** `padding-top: 24px` on the My Perch head, in `pages.css`.

### 3.6 Merge order and the run-through

1. **Step 0** (the orchestrator).
2. **Merge BE first.** Its tests do not depend on the front end.
3. **Merge FE-A next.** It owns the CSS.
4. **Merge FE-B last.**
5. **After the merge:**
   - The orchestrator edits the `ux_walk.py` checks listed in 3.1.
   - It sets `PERCH_ACCOUNTS_OPEN=0` in `.env.deploy`.
   - It runs H2's re-capture with a new idempotency option and `again=true` for cover points.
   - It runs H15's free replay.
   - QA runs the full walk at 1280 and 360, in light and dark, and opens every changed screenshot.
   - QA checks D13, D18 and D19 on the re-capture.
6. **The release session (S52):**
   - re-export both example files (A6);
   - re-run the back-test;
   - D7's morning run sheet;
   - D8's port test;
   - D10's README line;
   - copy section 5 into the README's Known limits.

## 4. Help changes (`web/help.js`, FE-B)

Every sentence must be true of the merged code.

- **Centre and programme grants:** "Centre and programme grants, such as a P30 or a P01, sit in their own fold under the single-lab grants. An institution applies for these. Their Match number does not change."
- **The card's face:** "Each grant card shows the model’s reading of the fit under the dates: Why it fits, or How it relates for a weaker match. It is marked Inference. Open the card for what the call funds and the papers it cites."
- **Match:** "The Match number ranks the leads. The text says why. It is not the odds of funding."
- **Sentences not matched to a source:** "When a sentence could not be matched to its source, the card says so in a small fold that lists it."
- **A paused budget:** "When this session’s model budget for the day is used, written reasons pause. One line above the list says so. The list, dates, amounts and rule results are not affected."
- **Name-only listings:** "When a Temple listing gives only an award’s name, the card says so and points to its page. No model writes a reason for it."
- **The example:** "While accounts are not open, Ask Scout and the note to the office point to the example brief. It shows what a signed-in user gets."
- **Keep the rest:** keep the S50 sentences that are still true. Change "Change details and run again" to "Run again" wherever My Perch is described.

## 5. Limits

These are written for the README's Known limits. Each sentence is true of the code after this round's Tier A. The bullets under "Depends on Tier B" are dropped by the release session when that item shipped.

- Accounts are not open on the test deploy, so visitors use guest mode, and the example brief shows what a signed-in user gets.
- The example brief plays back a saved file, and it does not show cover-letter points.
- Guests cannot paste a CV; the guest student path uses an invented sample student.
- Each guest session has a small daily model budget, and when it is used the written reasons pause while the list, dates, amounts and rule results still show.
- Perch folds only NIH activity codes P30, P01, P50 and U54 as centre and programme grants; other institution-level grants are listed with the single-lab grants.
- Scout and the note to the office do not use the centre-grant label, so Scout may still call a centre grant a strong match.
- The Match number measures how closely a call's text matches the papers; it is not the odds of funding, and a card's written reason can be weaker than its Match band.
- Several cards on one brief can cite the same papers when the researcher has few recent papers.
- Perch writes no reason for a Temple listing that gives only the award's name; the card points to the award's page instead.
- A student brief can open on listings that say little, because the order does not consider how much a listing states.
- The citation check can flag a correct sentence that joins two facts from one listing, and a flagged sentence is shown in a fold with a note.
- Some cover-letter points can still be marked as not matched to their source.
- Scout removes a sentence it cannot check, such as a claim that a record lacks a field, and marks the answer when it does.
- Scout may mention that an account has added no CV or entries even when the question did not ask.
- Asking for the same brief or the same cover-letter points again on the same day returns what was already built that day.
- The Temple awards list sorts A to Z by default, so rows with no stated deadline or amount can come first.
- The funding list still shows requests for information, which fund nothing; briefs leave them out.
- Saves on the browse lists and keeps in a brief are two separate lists.
- The note to an office waits for the model before any of it shows, which can take up to two minutes.
- Run again sits in the brief's header and starts a new brief without asking first.
- Only Grants.gov listings are refreshed on the deploy; other sources are as of their last fetch.

### Depends on Tier B

- **Drop this bullet if H6 shipped:** "When two copies of one Temple award are merged, an amount stated only on the dropped copy is not shown."
- **Drop this bullet if H13 shipped:** "Scout removes some headings, such as a comparison heading, and marks the answer when it does." If H13 did not ship, keep it and leave the Scout bullet above unchanged.
