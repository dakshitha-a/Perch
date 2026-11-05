# S50 design: round 2 build spec (2026-11-05)

This spec turns the four round 2 reviews into one front-end build. Round 3 follows it, then the release. It reuses the S49 conventions: the walk-flow loader, the package rules in S49_DESIGN.md section 3.1, and the shared-contract style ("A styles it; A and C emit it").

Item codes refer to these documents:

- **V1 to V51:** `S50_UIUX_REVIEW.md`.
- **Q1 to Q38:** `S50_PRODUCT_REVIEW.md`.
- **G1 to G34:** `S50_FUNCTION_REVIEW.md`. Only G7, G8 and G19 are front-end work.
- **C1 to C30:** `S50_BACKEND_REVIEW.md`. Only C3 reaches the screen.
- **LIVE:** the real-model capture in `build/s50_live/LIVE.md`.

The walk researcher is PI-4 (A5026494099). The example brief uses the aliased replay of PI-4. No other researcher is named here.

## 1. Decisions

The orchestrator settles these. Each one goes into `docs/DECISIONS.md` when the spec is recorded.

- **Keep and Dismiss move to a footer row (V2, V39, Q16):** the title row keeps only the Match pill. So the title gets about 650 px of an 840 px card, not 310 to 450 px.
- **The footer row also holds the Cover-letter points button, on its left:** a card then has one row of actions, not two. When points arrive, they open full width under the footer row.
- **The student verdict chip moves into the rule block (V4, Q1):** the chip sits on top of the lines that explain it. "To check:" and "Why not:" labels go away.
- **Rule lines come from `lead.checks` (P6, Q1, G6):** code writes each line, and the UI shows the text as it came. When the field is missing, the card falls back to `verdict_lines`.
- **A line that every card repeats is said once (V4, V5, decided):** when three or more cards on a list share one rule line, the line moves above the list as "Every option below: <line>". Each card then drops it.
- **The withheld-reason line is said once (V5):** when the list note about failed citation checks shows, the cards show no withheld line. A card with no reason section is the withheld one, and the list note says so.
- **The cover-letter hint is said once (V5):** a signed-in user sees one line above the list. Cards show only the button.
- **Facts sit in a fixed grid (V6):** two columns of 220 px, so Closes and Amount line up down the list.
- **One Match pill shape (V41):** the shape is the same in every band. Only the tint changes: filled green for strong, soft green for good, grey for partial and weak.
- **Sort becomes a small select (V3, V42):** the options are "Best match" and "Closing soonest". "Best match" sorts by `match_score`, highest first, with the server's rank as the tie-break. This fixes the out-of-order route T list.
- **The example brief is a static replay page (Q22, decided):** `web/example.html` loads `web/example/<side>.json` and plays it in the app's existing replay mode. The JSON is gitignored and placed on the deploy. It needs no server code and no model call, and it cannot stall.
- **The example is labelled plainly:** a banner says "Example", names the researcher by alias, gives the build date and says it plays back from a file. The landing link shows only when the file is on the server.
- **Guests get one "Or see an example" link under two walls (Q7 slice):** the links sit under "Sign in to ask Scout" and under "Sign in to draft a note to the office". Each one opens that tab of the example brief. The cover-points wall is already one line above the list, so it gets no link.
- **Phone filters fold (V9, V40, Q14, decided):** under 600 px, the search box stays and one "Filters" button opens the rest. School chips become one row that scrolls sideways.
- **Controls get a 3:1 border (V10, decided):** a new token `--line-strong` is `#7E8B85` in light mode and `#687B74` in dark mode. It is 3.1:1 or more against the page, cards and chips in both themes. Fields, secondary buttons, the ready chip and the sort select use it. Card edges keep `--line`.
- **Disabled buttons look disabled (V27):** a disabled button gets the chip fill, the faint border and muted text, with no opacity trick.
- **Focus on a heading moved by code shows no ring (V1, decided):** the rule covers `h1`, `h2` and `h3` with `tabindex="-1"`. Keyboard focus on every control keeps the ring.
- **Stop is for signed-in users only (Q6):** the cancel route refuses guests, so a guest never sees a Stop button.
- **Far-off dates on the funding list use the card's rule (G8):** a date more than ten years out with a note shows the note. The server's G8 fix replaces the rest.
- **Page words on the funding list are quoted (V29):** a record with no date and with its own words shows "The page says: “…”", as the awards list does.
- **"Not on the page" in the awards column (Q21):** the narrow column says this. The full sentence stays in the evidence panel.
- **Temple internal calls leave the Research Development note (Q3):** `handoff.js` counts only federal grants for that office. A line under the office choice says where Temple's own calls send people.
- **Student list heading (Q8):** it reads "N awards to look into". It no longer claims "you may apply for".
- **Canary tokens are hidden on screen only (Q17):** stored text, exports and the leak checks keep them, as rule 11 needs.
- **Lower-case Temple titles stay as written (Q20):** the round 1 decision stands, because a title is copied record text.
- **The researcher's name on My Perch rows waits (Q12):** `/me/briefs` has no display name. The row gets the time instead, and the name needs a back-end field later.

### For Dakshitha

- **None.** Q20 is the only real fork. It was settled in round 1 (keep the record's text), and this spec keeps that. If Dakshitha wants it reopened, it is one CSS rule in round 3.

## 2. Scope for round 2

The budget is about 4 to 5 hours of builder time, run by 3 builders in parallel. Each package lists its items in build order with minute estimates. **Tier A** must ship. **Tier B** ships only if the package is under budget, cut from the bottom first.

- **Tier A adds up to about 325 minutes:** FE-A is about 115, FE-B about 120 and FE-C about 90. That is about 5.4 hours, a little over the target. The decided items and the review must-fixes alone need about 4.5 hours.
- **Tier B adds about 150 minutes more.** It is polish that round 3 can take if this round runs short.
- **The cut line, if the orchestrator holds to 4.5 hours:** move these to round 3, in this order.
  1. **FE-B B1's V7 search button:** keep the doubled border for one more round. This saves 10 minutes.
  2. **FE-C C4's merged facts line for fellowships-list records (G7):** the cards keep "Not stated". This saves 10 minutes.
  3. **FE-A A6's "Hidden" disclosure (V44):** keep the run-on line. This saves 8 minutes.
  4. **FE-B B3's hand-off error placement (V24):** keep the wording fix only. This saves 5 minutes.

### Must-fix coverage

Every must-fix item that is front-end work is in Tier A:

- **UI/UX review:** V1 is A1. V2 is A2 and C1. V3 is A3. V4 is C2. V5 is B4, A2 and C2. V6 is A2. V7 is B1. V8 is A1. V9 is B1. V10 is A1.
- **Product review:**
  - Q1 is C2 and C5.
  - Q3 is B3.
  - Q4 is C3.
  - Q6 is A4 and B2.
  - Q7, as the two example links, is B3 and B5.
  - Q22 is A5.
  - Q2 is back-end data work. Q5 is done: the live capture is `build/s50_live/LIVE.md`.
- **Function review:** G7 is C4. G8 is B1. G19 is C4. G1 to G6 are back-end work.
- **Back-end review:** C3 is shown by B2. The status field comes from the back-end package.

### Deferred to round 3 or later, with reasons

- **V11 (two Compare screens):** this round gives both the same heading and note order (C5). One shared table component is a larger refactor across two owners.
- **V15 (steps text):** the text is written in `perch/service.py`, which the back-end package owns. It is passed to the back-end builder as a one-line note.
- **V23 (cover actions in one row):** the change is small, but it touches `scout.js` and `cover.js` together. It goes in round 3 with V49.
- **V25 and Q18 (hand-off wait shows the draft frame):** the product review dates this after Demo Day, and it needs a server split of the draft.
- **V46, V49, V50 (link styles, Scout column, separator dots):** polish only, so round 3.
- **Q9 (request for information on funding):** the back-end G3 rule hides these from briefs. A browse tag is FE-B Tier B.
- **Q12 researcher name:** it needs a back-end field, as noted above.
- **Q23 (has-a-deadline filters):** the lists are paged on the server, so this needs new query parameters.
- **Q24 to Q29 and Q34 to Q38:** the product review dates them after Demo Day. Q38 is a run-sheet step, not code.
- **Q37:** a fork for Dakshitha after Demo Day. The account rule stands for the demo.
- **LIVE, industry titles:** the capture showed OpenAlex institution URLs where the organisation name was missing in the payload. `orgCard` already falls back to `record_id`. QA checks the screen in round 3. A fix belongs in the payload, not the UI.
- **LIVE, raw ids in student prose:** `fitReason` already strips a leading `user:achievement-x`. QA checks one real student card in round 3.

## 3. Build packages

### 3.0 Step 0, done by the orchestrator before any builder starts (about 15 minutes, one commit)

These changes let three worktrees build without touching each other's files.

- **`web/api.js`, two methods on the live API:**
  - **`cancelBrief(id)`:** `post(`${bid(id)}/cancel`)`. It returns `{"id": "<id>", "cancelled": true|false}` and a 404 for a guest.
  - **`exampleAvailable(side)`:** a `HEAD` fetch of `example/${side}.json`, kept in a module-level map so it runs once per side. It resolves to `true` or `false` and never throws.
- **`web/api.js`, the replay API:** `cancelBrief` rejects with `new ApiError("Stopping needs the live app.", 0)`. `exampleAvailable` resolves to `false`.
- **`web/dom.js`:** add `info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01"` to the icon paths.
- **`.gitignore`:** add `web/example/`.
- **Walk flow files:** create `scripts/walk_flows/s50_fe_a.py`, `s50_fe_b.py` and `s50_fe_c.py`. Each holds `def register(U): return {}, []`.
- **Example files on the deploy checkout:**
  - Copy `build/replay/MCp4CdcfZLK8.json` (PI-4, saved 3 Nov 2026, with compare, hand-offs and Scout) to `web/example/researcher.json`.
  - Copy `build/replay/student.json` (the SYNTHETIC student preview) to `web/example/student.json`.
  - Before copying, open each file and check five things. The researcher shows as "PI-4" only. The created date is right. `compare`, `handoffs` and `scout` are there. The recorded hand-off lead ids are the leads marked kept in the file. No `explanation` or `inference` field in the researcher file contains "SYNTHETIC": the walk's fake model writes that word, so a hit means the file came from a walk, not from real models, and it must not be used.
  - If a fresh researcher replay can be exported from the v1 deploy store, prefer it.
  - These files are gitignored, so they never enter the repo or the ZIP. The v1 test deploy runs from this checkout, so it serves them at once.
- **Walk server:** start it with `PERCH_SCHEDULER=0`, so the nightly precache never runs during a walk (C2, C19).
- **Who owns which flow file:**
  - FE-A owns `s50_fe_a.py` and the old `s49_fe_a.py`.
  - FE-B owns `s50_fe_b.py` and the old `s49_fe_b.py`.
  - FE-C owns `s50_fe_c.py` and the old `s49_be_s.py`.

### 3.1 Rules for every package

The S49 rules apply unchanged (S49_DESIGN.md section 3.1). They cover isolation, fail first, one walk server on port 8191 started through `scripts/run_limited.sh`, existing checks, tests, final copy, commits and escalation. Four additions:

- **Worktrees lack the example files:** `web/example/` is gitignored, so a worktree does not have it. A walk check stubs `**/example/*.json` with Playwright's `page.route`. It serves the cached PI-4 payload that `s49_fe_a.py` already keeps under `build/s49_fe_a/cache`, wrapped as a replay file: `{"version": 2, "brief": <payload>, "candidates": [{"display_name": "PI-4"}], "records": {}}`.
- **Old checks in `ux_walk.py` that this round breaks on purpose:** the builder lists them in the hand-back, and the orchestrator edits `ux_walk.py` after the merge. These are known now:
  - **`cover_student_hint` and `cover_researcher_hint`** (lines 906 and 1023): the hint moves above the list.
  - **`cover_hint_hidden_with_result`** (line 941).
  - **The `[data-key=sort-closing]` click** (line 989): Sort is now a select.
- **Old checks in `scripts/walk_flows/s49_*.py`:** each owner updates its own. Examples are `CARDS` (titleTop and actTop) and `CENTRES` (the sort group) in `s49_fe_a.py`, and the withheld-line count in `s49_be_s.py`.
- **Contracts that may be missing:** the back-end fields this round reads (`lead.checks`, the C3 status, the G8 words) may not be merged yet. Every screen must work without them, and the walk stubs them with SYNTHETIC values.

### 3.2 Shared contracts

#### Lead card markup (FE-A styles it; FE-A and FE-C emit it)

```
li.card.lead[.kept][.gone][.is-sample][data-id]
  div.lead-top
    div.lead-name
      h3.lead-title > button.title-btn[data-key=title] > span(title) + evMark()
      p.lead-sub                       muted line, unchanged from S49
    div.lead-pill                      the Match pill, or the "Reading" pill; left out when neither
  dl.facts.facts-2                     two div.fact, unchanged content
  div.rules                            FE-C only, student cards (see below)
  div.reason                           "Still needed: …", unchanged
  ...notes, explanation...
  p.hint.withheld-line                 only when the list shows no withheld note (see the list contract)
  div.lead-foot
    div.cover                          coverBlock(...) when it returns a node; left out otherwise
    div.actions                        Keep and Dismiss, or Restore; data-keys unchanged
```

- **`.lead-end` is removed.** Nothing else may style or query it.
- **Industry cards (`orgCard`, FE-A):** the tags row stays at the top. Keep and Dismiss move into `div.lead-foot > div.actions`.
- **The student `data-key`s stay as they are:** `keep-<id>`, `dismiss-<id>` and `restore-<id>`.

#### Rule block (FE-C emits it; FE-A styles it)

```
div.rules[data-verdict="eligible"|"may"|"not"]
  verdictChip(l.verdict)                       the existing span.verdict
  ul.checks
    li.check[data-outcome="fail"|"unknown"|"pass"]
      span.check-mk[aria-hidden=true]          "✕" | "?" | "✓"
      span.sr-only                             "Not met: " | "Not known: " | "Met: "
      span                                     the line's text, verbatim
  details.checks-more                          only when there are more than 4 lines
    summary                                    "N more checks"
    ul.checks > li.check ...
```

- **The source, when `l.checks` is an array:** one `li` per item. The order is fail, then unknown, then pass, keeping the server's order inside each group. The `text` is rendered exactly as it came. The UI never reformats a number or a date in it.
- **The source, when `l.checks` is missing:** one `li` per `verdict_lines` item. Its outcome is `fail` when the verdict is "not eligible" and `unknown` otherwise. The one exception is the eligible line "Meets every rule Perch checks.", which is `pass`.
- **Lines already said above the list** (see below) are left out of the card.
- **An empty block:** when no line is left, the block holds the chip alone.

#### List head and notices (FE-A and FE-C emit them; FE-B's cover line goes in)

```
div.list-head
  h2.section-title#routes-title
  div.sort-group
    label.sort-label[for=sort-pick]            "Sort"
    select#sort-pick.sort-pick[data-key=sort]
      option[value=order]                      "Best match"
      option[value=closing]                    "Closing soonest"
div#list-notices
  p.notice.info.list-note[data-withheld]       only when two or more visible cards are flagged
  p.notice.info.list-note[data-shared-rule]    FE-C only: one per shared rule line
  <coverListLine(ctx) result>                  from cover.js; null when there is nothing to say
```

- **The withheld note's text, on both sides:** "Some written reasons failed Perch’s citation check, so those cards show no reason. Every date, amount and rule result on the cards is still copied from the record." It uses icon("info").
- **The shared-rule note's text:** "Every option below: <line>". It uses icon("info").
- **When a line counts as shared:** the visible, not-dismissed cards on the current route number 3 or more, and every one of them has exactly that rule line text.
- **A changed sort select:** it redraws the list and keeps focus on the select.

#### Example page (FE-A builds it; FE-B links to it)

- **URL:** `example.html`, with two optional query parameters:
  - **`side`:** `researcher` (the default) or `student`.
  - **`tab`:** `routes` (the default), `profile`, `compare` or `scout`.
- **FE-B's links:** `example.html?tab=scout` and `example.html?tab=compare`. They show only after `api.exampleAvailable("researcher")` resolves to `true`.

#### My Perch brief status (the back-end package builds it; FE-B reads it)

- **`GET /me/briefs`, each item's `status`:** one of `queued`, `running`, `done`, `failed` or `cancelled`. After the C3 fix, a dead or timed-out job reads `failed`.
- **The UI also accepts `dead`:** it is treated as `failed`.

#### Student lead checks (the back-end package builds it; FE-C reads it)

```json
"checks": [
  {"rule": "level", "outcome": "pass", "text": "Level: open to undergraduates; your CV says bachelor's."},
  {"rule": "deadline", "outcome": "unknown", "text": "Deadline: the listing does not state one."}
]
```

The field may be missing or empty. The builder at merge states the final rule names. The UI does not read `rule` except as a `data-rule` attribute on the `li`, for tests.

### 3.3 Package FE-A: researcher brief, lead card, base styles, example page

**Files FE-A may touch:**

- `web/app.js`
- `web/styles.css`
- `web/dom.js` (after Step 0)
- `web/format.js`
- `web/example.html` (new)
- `web/example.js` (new)
- `tests/test_web.py`
- `scripts/walk_flows/s50_fe_a.py`
- `scripts/walk_flows/s49_fe_a.py`

**Budget:** Tier A is about 115 minutes. FE-A merges first, because FE-C's cards depend on its CSS.

#### A1. Base styles (25 minutes, its own commit)

- **Heading focus (V1):** add `:is(h1, h2, h3)[tabindex="-1"]:focus { outline: none; }` right after the `:focus-visible` rule at line 94.
  - **Fail-first check `s50a_heading_ring`:** go to `#/awards`, then `#/welcome` with a stub. Read `getComputedStyle(document.activeElement).outlineStyle` while the heading has focus. Pass when it is `none` and `document.activeElement.tagName` is `H1`.
- **Control border (V10):**
  - **The token:** add `--line-strong: #7E8B85;` to `:root`, and `--line-strong: #687B74;` to both dark blocks.
  - **Where it applies:** use it for the border of `.btn` (not `.primary`, not `.quiet`), `input`, `select`, `textarea`, `.searchbox`, `.ready-chip > summary`, `.sort-pick` and `.export-menu > summary`.
  - **Where it does not apply:** `.card`, `.box` and `.award-row` keep `--line`.
  - **Fail-first check `s50a_control_border`:** on the landing and on `#/awards` in both themes, take every visible `.btn:not(.primary):not(.quiet)`, `input` and `select`. Compute the contrast of `border-top-color` against the effective background of its parent. Pass when every one is 3.0 or more.
- **Disabled buttons (V27):** replace the rule at line 120 with this.

  ```css
  .btn[disabled], .btn[aria-disabled="true"] { opacity: 1; cursor: not-allowed; background: var(--chip); border-color: var(--line); color: var(--ink-3); }
  .btn.primary[disabled], .btn.primary[aria-disabled="true"] { background: var(--chip); border-color: var(--line); color: var(--ink-3); filter: none; }
  ```

  - **The ratios:** `--ink-3` on `--chip` is 4.98:1 in light mode and 5.22:1 in dark mode.
  - **Fail-first check `s50a_disabled`:** on the student start with no CV, the computed `background-color` of `[data-key=st-build]` equals the computed `--chip`.
- **Form column (V8):** remove the 680 px caps at about lines 1425 and 1428. Every card and button in `body[data-screen="form"] main > .screen` is then `width: 100%` of the 760 px column.
  - **Fail-first check `s50a_form_edges`:** on welcome, account and the student start, every `.box` and `.welcome-go .btn.primary` has the same right edge as the `.screen`, within 1 px.
- **Dialogs (V37):**

  ```css
  dialog { background: var(--surface); }
  dialog::backdrop { background: rgba(10, 16, 14, .55); }
  ```

  In both dark blocks, set `dialog { background: #1F2D29; border: 1px solid var(--line-strong); }`.
- **Evidence mark (V43):** `.lead-title .ev-mark, .ar-title .ev-mark { vertical-align: baseline; white-space: nowrap; }`.
- **Equal landing buttons (V47):** `.landing .hero-actions .btn { min-width: 264px; }`. Use the selector that holds the two buttons at about line 952.
- **The kept bar on phones (V36):** `@media (max-width: 699px) { #panel { padding-bottom: 72px; } }`.
- **Student compare labels on phones (V12):** in `.compare.stack td`, align the label pseudo-element and the value to the top: `align-items: start;`.
  - **Check `s50a_stack_labels`:** at 360 px, on the student compare, each cell's `::before` top and the value's top differ by 2 px or less.

#### A2. The lead card (35 minutes)

- **Markup:** build `leadCard` and `orgCard` to the contract in 3.2. The match pill or the Reading pill goes in `div.lead-pill`. Keep, Dismiss and Restore go in `div.lead-foot > div.actions`. The `coverBlock(...)` node goes first in `div.lead-foot`.
- **The withheld line:** a flagged card shows `p.hint.withheld-line` only when fewer than two visible cards are flagged. Otherwise the list note says it.
- **CSS:** replace the S49 A4 block from `.lead-top` to `.lead-end .actions` with this.

  ```css
  .lead-top { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 16px; align-items: start; }
  .lead-pill { padding-top: 2px; }
  .lead-foot { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin-top: 2px; padding-top: 12px; border-top: 1px solid var(--line); }
  .lead-foot > .cover { flex: 1 1 auto; min-width: 0; display: grid; gap: 8px; }
  .lead-foot > .cover:empty { display: none; }
  .lead-foot > .cover:has(.scout-points) { order: 2; flex-basis: 100%; }
  .lead-foot > .actions { margin-left: auto; display: flex; gap: 8px; }
  .facts-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 220px)); gap: 4px 32px; margin: 0; }
  .facts-2 .fact-wide { grid-column: 1 / -1; }
  @media (max-width: 599px) {
    .lead-top { grid-template-columns: 1fr; }
    .lead-pill { padding-top: 0; }
    .facts-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 16px; }
  }
  ```

- **The rule block styles (for FE-C's markup):**

  ```css
  .rules { display: grid; gap: 6px; justify-items: start; }
  .rules ul.checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; font-size: var(--fs-14); }
  .rules li.check { display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 6px; color: var(--ink-2); }
  .check-mk { font-weight: 700; text-align: center; }
  li.check[data-outcome="pass"] .check-mk { color: var(--ok-ink); }
  li.check[data-outcome="fail"] .check-mk { color: var(--no-ink); }
  li.check[data-outcome="unknown"] .check-mk { color: var(--may-ink); }
  details.checks-more > summary { font-size: var(--fs-14); color: var(--ink-2); min-height: 32px; }
  ```

- **One Match pill (V41):** replace lines 325 to 332 with this.

  ```css
  .fit { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 12px; border-radius: 999px; font-size: 13px; font-weight: 600; white-space: nowrap; }
  .fit b { font-weight: 700; min-width: 0; height: auto; padding: 0; background: none; box-shadow: none; border-radius: 0; }
  .fit.strong { background: var(--moss); color: var(--moss-ink); }
  .fit.strong .fit-k { color: var(--moss-ink); opacity: .85; }
  .fit.good { background: var(--accent-soft); color: var(--ok-ink); }
  .fit.partial, .fit.weak { background: var(--chip); color: var(--ink-2); }
  ```

- **Fail-first checks:**
  - **`s50a_title_width`:** on the researcher brief at 1280 px, every card's `.lead-title` width is 600 px or more. Before the change it is about 450 px.
  - **`s50a_actions_footer`:** every card's `[data-key=keep]` top is below its `.facts-2` bottom.
  - **`s50a_facts_column`:** the left edge of the second `.fact` is the same on every visible card, within 1 px. Before the change it varies by up to 133 px.
  - **`s50a_title_opens_evidence`, the open evidence rail:** the brief opens a record in two places. On a screen 901 px or wider, `openEvidence` fills the rail box `#rail-ev` beside the list. On a phone it opens the `#evidence` sheet.
    - **At 1280 px:** click the first card's `.lead-title .title-btn`. Pass when `#rail-ev` holds the record's title in `#evidence-title`, its placeholder text "Pick a card’s title" is gone, and the card has the class `selected`. Save the screenshot as `evidence-rail-open`.
    - **At 360 px:** the same click. Pass when `#evidence` is not hidden and `#evidence-body` holds the title.
    - **Why it matters:** the round 1 bug on the list title slipped through because no check clicked a title. This is the new walk coverage for an open evidence rail.

#### A3. List head and brief header (15 minutes)

- **Sort (V3, V42):** `sortedLeads()` for `"order"` sorts by `match_score` descending, with nulls last and `rank` as the tie-break. Industry stays by rank.
  - **The control:** replace `sortSwitch()` with the select in 3.2. `S.sort` keeps the values `order` and `closing`.
  - **Fail-first check `s50a_sort_order`:** on route T with the stub that moves two leads to T, the visible Match numbers never rise from top to bottom.
- **Ready chip (V14):** in `format.js`, the duration under 1 second returns no number, and the chip reads "Ready". At 1 second or more it reads "Ready · 4 s", as now.
  - **Check `s50a_ready_zero`:** a cached brief's chip text is exactly "Ready".
- **Change details and run again (V16):** the wide link becomes `a.btn.quiet.rerun-wide`, with icon("restore") and the visible text "Run again". Its `aria-label` is "Change details and run again". The Export menu item stays as it is.
- **Student Export (Q33):** `exportMenu(true)` leaves out "Records as JSON".
- **Citation chip labels (V17):** `recordLabel(id)` at about line 1295 returns the record's title cut to 32 characters plus "…" when a title is known. It never returns the word "Evidence" alone. When no title is known, it returns the record's source name and number, such as "Grants.gov PAR-25-442".
- **Banner icons (V26):** "Your data was deleted." uses icon("check"). The guest banner uses icon("info"). The withheld note uses icon("info"), from 3.2.

#### A4. Stop a brief while it builds (Q6) (10 minutes)

- **Where:** in `renderProgress()`, while `S.brief.brief.status` is `queued` or `running`, for a signed-in user (`S.session.signed_in` and not replay), add `button.btn.quiet[data-key=stop-brief]` with icon("stop") and the text "Stop".
- **What it does:** it calls `api.cancelBrief(S.briefId)`, then announces "Stopping the brief." The next poll draws the failed state.
- **The failed state when the stop came from the user:** the brief payload has no "cancelled" field. `job_overlay` in `perch/user/briefs.py` turns a cancelled job into `status: "failed"` with a code-written `error` sentence. So the page remembers the press: `S.stoppedId = S.briefId`.
  - **When the next poll says `failed` and `S.stoppedId` matches:** the progress card's heading reads "Stopped". Its hint reads "You stopped this brief. Run again builds a new one." The Run again link is shown.
  - **Otherwise:** the failed state stays as it is, with the server's `error` sentence.
- **Fail-first check `s50a_building`:** stub `GET /briefs/<RB>` with the cached payload. Set the status to `running`, the `route_a` stage to `running` and the later stages to `pending`.
  - **Pass condition:** the progress card shows, the Leads panel shows its skeleton text "Leads appear here when the search finishes.", and `[data-key=stop-brief]` shows for a stubbed signed-in session.
  - **Second step:** click Stop. A stubbed `POST /briefs/<RB>/cancel` must be hit once, and the next stubbed poll with `status: "failed"` shows "Stopped".
  - **This is new walk coverage:** "a brief while it builds".

#### A5. The example brief (Q22) (30 minutes)

- **`web/example.html`:** a copy of `index.html` with three differences.
  - **The title:** `<title>Example brief — Perch</title>`.
  - **The wordmark:** `href="./"`.
  - **The script:** `<script type="module" src="example.js"></script>` in place of `app.js`.
- **`web/example.js`:**

  ```js
  // The example brief (S50 Q22): a saved brief played back in the app's replay mode, from a file the
  // deploy places at web/example/<side>.json. Nothing is called and nothing is saved.
  const q = new URLSearchParams(location.search);
  const side = q.get("side") === "student" ? "student" : "researcher";
  const tab = ["routes", "profile", "compare", "scout"].includes(q.get("tab")) ? q.get("tab") : "routes";
  try {
    const r = await fetch(`example/${side}.json`, { cache: "no-cache" });
    if (!r.ok) throw new Error(String(r.status));
    const data = await r.json();
    window.PERCH_REPLAY = data;
    window.PERCH_EXAMPLE = { side };
    if (!location.hash || location.hash === "#/") {
      history.replaceState(null, "", `#/brief/${encodeURIComponent(data.brief.brief.id)}/${tab}`);
    }
    await import("./app.js");
  } catch {
    // draw into <main>: h1 "The example is not on this server.", then a link "Back to Perch" to "./"
  }
  ```

  - **The CSP stays as it is:** `script-src 'self'` allows both files, and the JSON is fetched under `connect-src 'self'`. The inline-script page that `build_ui_preview.py` makes would be blocked here, so it is not used.
- **`app.js`, the banner in `init()`:** when `window.PERCH_EXAMPLE` is set, the replay banner reads as follows.
  - **The badge:** a `span.tag.ember` with the text "Example".
  - **The researcher text:** "A saved brief for a Temple researcher, shown as <candidates[0].display_name>, built <formatDate(brief.brief.created_at)> from public records. It plays back from a file: nothing here calls a model or saves anything."
  - **The student text:** "A saved brief for an invented SYNTHETIC student, built <date>: real Temple listings and invented sample scholarships. It plays back from a file: nothing is saved."
  - **The link:** `a[href="./"]` with the text "Back to Perch".
  - **The tab title:** `document.title` is "Example brief — Perch".
- **`app.js`, the landing (`renderFind`, live mode only):** under the researcher Find button, and under the student "Check my fit" button, add `a.quiet-link[data-key=example-brief]`.
  - **Researcher link:** text "See an example brief", `href="example.html"`.
  - **Student link:** text "See an example", `href="example.html?side=student"`.
  - **When it shows:** only after `api.exampleAvailable(side)` resolves to `true`. Draw the slot empty first and fill it, so the landing never jumps by more than one line.
  - **The fit:** the landing must still fit 1280 × 720 (the S49 A2 checks).
- **Fail-first checks:**
  - **`s50a_example`:** stub `**/example/researcher.json` as in 3.1. Open `example.html`. Pass when `#banner` contains "Example" and "PI-4", the lead list shows cards, and no request goes to `/briefs`, `/session` or `/me`.
  - **`s50a_example_link`:** on the live landing with the stub, `[data-key=example-brief]` is visible. With the stub returning 404, it is not in the DOM.
  - **`s50a_example_missing`:** with the stub returning 404, `example.html` shows "The example is not on this server."

#### A6. Tier B, in order

- **"Hidden" as a disclosure (V44) (8 minutes):** `hiddenLine()` becomes `details.hidden-fold > summary` with "<total> hidden by the rules". It opens to a `ul` of "<label>: <count>". The labels and counts stay the server's.
- **Pick screen (Q19, Q31, V32, Q13) (15 minutes):**
  - **Q19:** a stored CV is ticked by default for a signed-in user.
  - **Q31:** "Explain each lead" moves inside "Tell Perch more". It stays checked by default.
  - **V32 and Q13:** a second `button.btn.primary[data-key=build-foot]` with the text "Build brief" sits at the foot of the form. It calls the same handler.
- **Thread chips (V48) (20 minutes):** the profile thread heading becomes "Thread <n> · <share> %", with the label words as `span.chip` under it. The share is the server's number. The explanation paragraph is cut to its first sentence, with the rest in `details > summary "How threads work"`.

### 3.4 Package FE-B: lists, My Perch, hand-off, cover points, Scout, help

**Files FE-B may touch:**

- `web/browse.js`
- `web/account.js`
- `web/compare.js`
- `web/handoff.js`
- `web/cover.js`
- `web/scout.js`
- `web/help.js`
- `web/api.js` (after Step 0)
- `web/index.html`
- `web/pages.css`
- `tests/test_web_pages.py`
- `scripts/walk_flows/s50_fe_b.py`
- `scripts/walk_flows/s49_fe_b.py`

FE-B never edits `styles.css`. Its rules go in `pages.css`, which loads after it.

**Budget:** Tier A is about 120 minutes.

#### B1. Browse lists (50 minutes)

- **Phone filters (V9, V40, Q14, decided):** in the list's filter area at `browse.js:304-328`, build this.

  ```
  div.filter-bar
    div.search-row                       the search field and its button; always shown
    button.btn.filter-toggle[data-key=filters][aria-expanded][aria-controls=filter-body]
      icon("filter") + span "Filters" + span.filter-n " · <n>"   (n only when it is above 0)
    div#filter-body.filter-body[.is-folded]
      the level select (awards only), the sort select, the switches, the hint, div.tag-row of school chips
  ```

  - **What n counts:** the filters not at their default. A school is picked, a level is set, the sort is not the side's default, "Show closed calls" is on, or "All Temple" is on.
  - **The starting state:** `.is-folded` is set each time a list screen is drawn. The toggle flips it and `aria-expanded`.
  - **CSS in `pages.css`:**

    ```css
    .filter-toggle { display: none; }
    @media (max-width: 599px) {
      .filter-toggle { display: inline-flex; }
      .filter-body.is-folded { display: none; }
      .filter-body .tag-row { flex-wrap: nowrap; overflow-x: auto; scroll-snap-type: x proximity; padding-bottom: 6px; }
      .filter-body .tag-row > * { flex: none; scroll-snap-align: start; }
    }
    ```

  - **Fail-first check `s50b_phone_first_row`:** at 360 × 740, on `#/awards` and `#/funding`, the first `.award-row` top is under 640 px. Before the change it is 700 to 1100 px.
  - **Second check:** after a click on `[data-key=filters]`, the school chips' tops are all equal, so they sit on one row.
- **Search box (V7):** the Search button moves out of the bordered box.
  - **The input:** `.searchbox` keeps a 1 px `--line-strong` border on the input only.
  - **The native clear:** hide the browser's own clear button with `input[type=search]::-webkit-search-cancel-button { -webkit-appearance: none; display: none; }`.
  - **Its replacement:** add `button.btn.quiet.icon-only.search-clear[aria-label="Clear the search"]` with icon("close") at the input's right end. It shows only when the input has text.
  - **The focus ring:** `styles.css:963` sets `.searchbox input:focus-visible { outline: none; }`, because the box used to carry the border. In `pages.css`, give it back: `.searchbox input:focus-visible { outline: 3px solid var(--focus); outline-offset: 1px; }`.
  - **Check `s50b_search_button`:** the Search button's box does not overlap `.searchbox`'s box. `.searchbox` has a computed `border-top-width` of `0px`, or the button lies outside it.
- **Right column (V28, Q21):** `.award-row { grid-template-columns: minmax(0, 1fr) 260px auto; }`. Amount text gets `white-space: nowrap`. "No amount or deadline on the page" becomes "Not on the page".
  - **Check `s50b_amount_one_line`:** every visible amount `dd` is one line high: its height is less than 1.6 times its line-height.
- **Level on funding (V30, Q30):** the "Level of study" select is not drawn on `#/funding`.
- **Far-off dates (G8):** in `deadlineText`, for an opportunity whose `close_date` is more than 3650 days after today, and which has a `close_date_note`, return the note. This is the card's `farClose` rule. When the back-end G8 change has replaced the date, the row shows what the server sent.
  - **Fail-first check `s50b_far_date`:** stub `/opportunities` with one SYNTHETIC record, `close_date: "2076-10-05"` and `close_date_note: "SYNTHETIC proposals accepted anytime"`. The row shows the note, not "5 Oct 2076".
- **Page words on funding (V29):** an opportunity with no `close_date` and with a `close_date_note` shows `span.quote-date` with the text "The page says: “<note>”". This is the same element the awards list uses.
- **Title opens evidence (new walk coverage):**
  - **Fail-first check `s50b_title_opens_evidence`:** on `#/awards` and `#/funding`, click the first `.ar-title .title-btn`. Pass when `#evidence` is visible and `#evidence-body` holds the same title.
  - **Proving it fails:** revert 5abe151's one-line fix locally to see this fail, then restore it.

#### B2. My Perch (15 minutes)

- **Status words (C3):** `queued` and `running` read "Still building". `failed`, `cancelled` and `dead` read "Stopped".
- **Stop on a busy row (Q6):** a busy row gets `button.btn.quiet[data-key=stop-<id>]` with icon("stop") and the text "Stop". It calls `api.cancelBrief(id)`, then reloads the brief list and announces "Stopped. Change details and run again builds a new one."
- **Fail-first check `s50b_stop_row`:** stub `/me/briefs` with one `running` row. The Stop button shows. A click hits the stubbed cancel route once. The reload, stubbed with `failed`, shows "Stopped" and no Stop button.

#### B3. Hand-off (15 minutes)

- **Temple internal leads (Q3):** in `renderHandoff`, `count(route)` and `inNote` leave out leads with `l.group === "temple_internal"`.
  - **The line:** when any kept lead has that group, add `p.hint[data-key=temple-line]` under the office fieldset. Its text is "Temple’s own calls name their contact on each call’s page."
  - **Fail-first check `s50b_temple_handoff`:** in the stubbed brief, keep one route-T lead and no federal grant. The Research Development radio is disabled, and `[data-key=temple-line]` is visible.
- **Error wording and place (V24):**
  - **The text:** "The draft could not be made. <message>", with a full stop, not a colon.
  - **The place:** when a draft already exists, the error goes above the draft box. It adds `p.hint` with the text "The draft below is the previous one."
- **The example link for guests (Q7):** under the guest's "Sign in to draft a note to the office", add `a.quiet-link[data-key=example-draft][href="example.html?tab=compare"]` with the text "Or see an example draft". It shows only when `api.exampleAvailable("researcher")` is true.

#### B4. Cover-letter points (`cover.js`) (10 minutes)

- **Hint once (V5):** remove the per-card `COVER_HINT` line.
  - **The list line:** `coverListLine(ctx)` returns, for a signed-in live user with no quota note, `p.list-note[data-cover-line]` with icon("pen") and `COVER_HINT[audience]`.
  - **Other cases:** guests and the quota note work as now.
  - **Fail-first check `s50b_cover_hint_once`:** on the stubbed signed-in student list, the text "A model writes these" appears exactly once on the page.
- **Consent as a step, not an error (V20):** replace the red alert with `p.notice.info` holding icon("info").
  - **Its text:** "Cover-letter points use your CV, so they need your consent first. "
  - **Its link:** `a.btn` to `#/welcome` with the text "Read and agree", inside the same notice.
- **Reset time with the year (V38):** `backAt` adds the year when it differs from this year.

#### B5. Scout (`scout.js`) (10 minutes)

- **Warnings in one place (V19):** the "could not confirm" warning moves above the answer, next to the "did not pass the citation check twice" warning.
- **Chip labels (V17):** at about line 389, the record chips use the record's title, cut to 32 characters plus "…". They never show the word "Evidence" alone.
  - **Check `s50b_scout_chips`:** in the stubbed `withheld_all` answer, no two chips in one sentence share a label.
- **The example link for guests (Q7):** under "Sign in to ask Scout", add `a.quiet-link[data-key=example-scout][href="example.html?tab=scout"]` with the text "Or see an example answer". It shows only when the example is available.
- **One phrase for gaps (V21):** "Still missing" in `pointsBlock` becomes "Still needed", the student card's phrase.
- **Flagged points said once (LIVE):** when every flagged sentence is already marked `.flagged` inline, the notice reads "Marked lines could not be matched to their source." It does not repeat the sentences.

#### B6. Help (15 minutes)

Write section 4 into `web/help.js`.

- **Fail-first check `s50b_help`:** open `#/help`. Pass when the page heading is visible, the anatomy figure renders, and each new sentence in section 4 is present. Run it at 360 px and at 1280 px, and add axe with no serious issues. This is new walk coverage for the Help page.

#### B7. Tier B, in order

- **Q10 (5 minutes):** the funding row shows `span.rel` with `f.closesIn(days)` after a future date. The `dd` gets the class `f.urgency(days)`. Add `.ar-facts dd.soon > span:first-child { color: var(--ember); }` and `.ar-facts .rel { display: block; font-weight: 500; font-size: 13px; color: var(--ink-3); }`.
- **V31 (10 minutes):** a list error keeps the search and filter bar. The error is centred under them as `p.notice.error` with one Retry button, and the text says "The list could not be loaded." with no "Try again."
- **Q11 (8 minutes):** a My Perch saved row adds the external link (`a.btn.icon-only`, icon("external"), `href=f.safeUrl(record.source_url)`). "Kept in your brief of <date>" becomes a link to `#/brief/<brief_id>/routes`.
- **V35 and Q12 (5 minutes):** brief titles use the sans style (`font: 600 16px/1.3 var(--sans)`). Student rows read "Options checked <date>, <time>", where the time comes from `created_at` as `toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})`. Researcher rows keep topics, or "Researcher brief, <date>, <time>".
- **V51 (5 minutes):** an empty My Perch card holds one button, and the top start row leaves out a button that the empty card already shows.
- **Q9 (5 minutes):** a funding row whose title starts with "Request for Information" gets `span.tag` with the text "Request for information: not a funding call". Code reads the record's own title.

### 3.5 Package FE-C: student screens

**Files FE-C may touch:**

- `web/student.js`
- `web/sample_student.js`
- `scripts/walk_flows/s50_fe_c.py`
- `scripts/walk_flows/s49_be_s.py`
- `scripts/walk_flows/s49_student_brief.json` (the SYNTHETIC fixture; add `checks` to a copy, not to the original)

FE-C writes no CSS. It emits the classes in 3.2, and FE-A styles them. A class FE-C needs that 3.2 does not list is escalated, not invented.

**Budget:** Tier A is about 90 minutes.

#### C1. Student card markup (20 minutes)

- **The contract:** build `card(l, ctx)` to the lead card contract in 3.2.
  - **The title row:** the match pill goes in `div.lead-pill`.
  - **The verdict chip:** it moves into `div.rules` (C2).
  - **The footer:** the `coverBlock(...)` node, then `div.actions` with Keep and Dismiss, go in `div.lead-foot`.
- **The withheld line (V5):** when two or more visible cards are flagged, the card shows no withheld line. The list note text and icon follow 3.2.
- **Route switch with one route (V13):** when only route F exists, no `.route-switch` is drawn. The count heading is the label.
- **Heading (Q8):** route F reads `${f.plural(n, "award")} to look into`. The sample route keeps its text.
- **Sort:** use the select from 3.2. "Best match" is the existing `match_score` order.
- **Fail-first checks:**
  - **`s50c_title_width`:** on the student list at 1280 px, every `.lead-title` is 600 px wide or more.
  - **`s50c_single_route`:** no `.route-switch` shows on a brief with route F only.
  - **`s50c_title_opens_evidence`:** a click on the first card's title shows that title in `#rail-ev` at 1280 px, and in `#evidence` at 360 px, as in A2's check.

#### C2. Rule lines (P6, Q1, V4, V22) (25 minutes)

- **The block:** build `div.rules` to the contract in 3.2, from `l.checks` when it is an array. Otherwise use `verdict_lines`.
- **Shared lines:** after the cards are built, find the lines shared by every visible card (3 or more cards). Draw one `p.notice.info.list-note[data-shared-rule]` per line in `#list-notices`, with the text "Every option below: <line>". Leave those lines out of the cards.
- **"Still needed" (V21):** the gaps line keeps its label "Still needed:".
- **Fail-first checks:**
  - **`s50c_no_repeat`:** the S49 fixture has no line on every card, so nothing there can be hoisted. In FE-C's copy of the fixture, plant the fixed sentence "The listing says who may apply; the award's own page sets the full rules. Read it before applying." in `verdict_lines` on every visible card, and leave the GPA line on the two cards that have it.
    - **Pass condition:** the fixed sentence appears 0 times inside `.lead` cards and once in `#list-notices`.
    - **The guard against hoisting too much:** the GPA line still shows on both cards that have it.
    - **Fail first:** on the old code the fixed sentence appears on every card.
  - **`s50c_checks`:** with a stubbed `checks` array of one pass and one unknown on one card, that card shows two `li.check` items. The unknown one comes first. Each has the right `data-outcome`, and its text matches the stub exactly.

#### C3. Find saves the boxes (Q4, V33) (20 minutes)

- **Unsaved boxes:** these are the CV textarea, when no CV is stored, the interests box and the achievement box, each when it holds text.
- **The button's state:** "Find awards that fit" is enabled when a CV is stored or the CV textarea has text. When there are unsaved boxes, its label is "Save and find awards".
- **What the press does:**
  1. It calls `api.addDoc(...)` for each unsaved box, one after another, with the same bodies the separate buttons send.
  2. It does not redraw between saves.
  3. Then it builds.
  4. On an error, it stops, shows the error in `D.error`, and keeps what the user typed.
- **The hint when there is no CV:** "Paste or upload your CV first."
- **The separate Save buttons stay for editing.**
- **The Load sample hint and announcement:** "Nothing is saved until you press Save." becomes "Nothing is saved until you press Save, or Save and find awards."

- **Fail-first check `s50c_load_sample_find`:** on the stubbed signed-in student start, press Load sample, then `[data-key=st-build]`. Pass when the stubbed `POST /me/docs` is hit three times, then the brief create route once, with no other press.

#### C4. What the card says (15 minutes)

- **Unsupported model sentences (G19):** when `l.unsupported` is not empty, add the researcher card's block under the fit reason. It is `div.notice.warn` with icon("warn"), the text "This statement could not be matched to its source:" and a `ul` of the sentences.
  - **Check `s50c_unsupported`:** a stubbed card with one unsupported sentence shows the block.
- **Canary hidden on screen (Q17):** in the profile's "Your interests" and in the achievement texts, the on-screen text drops `/\s*Canary:\s*PERCH-CANARY-\S+/g` and app.js's `CANARY_TAIL` pattern. Stored text and exports are unchanged.
  - **Check `s50c_no_canary`:** the profile tab's visible text has no "PERCH-CANARY".
- **Fellowships-list records (G7):** a `temple_sdfa` record with no deadline, no deadline quote and no amount shows one `div.fact.fact-wide` in place of the two facts. Its `dt` is "Deadline and amount". Its `dd` is "The fellowships list gives neither. Check the award’s own page."
  - **Check `s50c_sdfa_facts`:** a stubbed `temple_sdfa` card shows one fact and no "Not stated".
  - **FE-A styles it:** add `.facts-2 .fact-wide { grid-column: 1 / -1; }` to A2.

#### C5. Student compare (10 minutes)

- **Rule check column (Q1):** the cell shows the verdict chip, then up to three check texts. Fail and unknown lines come before pass lines.
- **Same order as the researcher (V11):** the section heading is "Hand off". The line "Each cell is copied from its record…" moves above the hand-off section.

#### C6. Tier B

- **V34 (10 minutes):** the profile drops the inner "Your interests" title. Each achievement is titled by its first five words plus "…".

### 3.6 Merge order and the run-through

1. **Step 0** (orchestrator).
2. **Merge FE-A first.** It owns the card CSS and the sort select styles.
3. **Merge FE-C next.** It emits FE-A's markup.
4. **Merge FE-B last.** Its cover line goes into both lists.
5. **After the merge:**
   - The orchestrator updates the `ux_walk.py` checks listed in 3.1.
   - QA runs the full walk at 1280 and 360, in light and dark.
   - QA opens every changed screenshot, plus `example.html` on the deploy.
   - Round 3 gets one real student card and one real industry card on screen, to close the two LIVE items in the deferred list.

## 4. Help page (`web/help.js`, FE-B)

Every sentence below must be true of the merged code. FE-B checks each one against the code before it closes B6.

- **The lead card** (update the anatomy figure and its callouts): "The title comes first, with the Match pill beside it. Closes and Amount sit in two columns. Keep, Dismiss and Cover-letter points sit in the card's bottom row."
- **Rule lines:** "On a student card, the chip says what the rules found: eligible, may be eligible or not eligible. Under it, each line says what one rule checked. A check mark means the rule was met, a cross means it was not, and a question mark means the listing or your CV does not say. When every card shares a line, it is said once above the list."
- **Sort:** "Best match puts the highest Match first. Closing soonest puts the nearest date first; records with no date come last."
- **Example brief:** "See an example brief opens a saved brief for a Temple researcher, shown by alias. It plays back from a file, so it opens at once and nothing is called or saved. The banner says when it was built."
- **Stop:** "While a brief builds, a signed-in user can press Stop. The brief shows as Stopped on My Perch, and Change details and run again builds a new one."
- **Phone filters:** "On a phone, Filters opens the level, sort and school choices. The number on the button counts the filters that are on."
- **Temple internal calls in a hand-off:** "A note to Research Development lists kept federal grants only. Temple’s own calls name their contact on each call’s page."
- **Cover-letter points:** replace the per-card hint sentence with this: "One line above the list says how points are written. The points use your CV, so they need your consent first."
- **Withheld reasons:** "When several written reasons fail the citation check, one note above the list says so, and those cards show no reason. Their dates, amounts and rule results are still copied from the record."
- **Keep the rest:** keep the sample-data paragraph and the S49 sentences that are still true. Remove "Ready · 0 s" from any figure.
