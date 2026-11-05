# S49 design: round 1 build spec (2026-11-04)

This spec turns five front-end documents into one build for round 1. The five are `S48_UI_NOTES.md`, `S48_UI_DESIGN.md`, `S48_UI_REVIEW.md`, `S49_UIUX_REVIEW.md` and `S49_PRODUCT_REVIEW.md`. It also builds the four S49 decisions in `docs/DECISIONS.md`. Item codes refer to those documents:

- **D1 to D5:** sections of `S48_UI_DESIGN.md`.
- **M1 to M6:** the must-fix items of `S48_UI_REVIEW.md`.
- **U1 to U55:** items of `S49_UIUX_REVIEW.md`.
- **P, S, F, R and D codes with a "P-" prefix:** items of `S49_PRODUCT_REVIEW.md`. For example P-D1 is its flow redesign D1.
- **FM codes:** items of `S49_FUNCTION_REVIEW.md`. For example FM3 is its M3.

The walk researcher is PI-4 (A5026494099). No other researcher is named here.

## 1. Decisions

Dakshitha delegated S49 decisions to Perch-dev. The design forks below are settled here. Each one goes into `docs/DECISIONS.md` when the orchestrator records this spec.

- **Lowercase Temple titles stay as the page wrote them (U50 over S2):** a title is copied record text. Changing it, even its first letter, breaks the copy-only spirit of rule 3. The lowercase titles go to round 2 as a data-quality item for the Temple page parser.
- **Closed calls are hidden by default on the funding list only (P2):** the "Show closed calls" switch is off by default on `#/funding`. The awards list hides nothing by date. The reason is the past-cycle decision: 22 Temple awards show last cycle's date and most of them recur. Hiding them by date would undo that decision.
- **A past date on an award reads as a past date, not "Closed":** on the awards list, an award whose date has passed gets the muted tag "Past date on the page". Funding keeps the "Closed" tag, because a Grants.gov close date is final. Both are written by code from the record's own date.
- **Temple internal funding is a third route button (`route: "T"`):** it sits between Grants and Industry, as "Temple internal". It matches the existing switch pattern, and it keeps those calls in their own list, as the decision asks. Section 3.4 has the contract.
- **My Perch is the signed-in home (P-D1, U41):** a signed-in user's `#/` shows My Perch. The hero landing moves to `#/start` for signed-in users. Guests and signed-out visitors keep the hero at `#/`.
- **The saved list holds saved awards and kept leads together (P1, F1, F3):** My Perch lists both, in one list sorted by date. One server call returns both, so the page needs no fan-out over briefs.
- **Industry leads stay off My Perch:** they hold no date and they are inferences. They stay inside their brief, with their "inferred" label.
- **Samples cannot be saved (rule 11):** the server refuses an id from the SYNTHETIC corpus. The sample screen shows no Keep button.
- **Guests get no Keep button on the lists:** a guest saves nothing. Instead, one line above the list says to sign in.
- **Cover-letter points for guests are offered once per list (U16, S9):** guests see one line above the list and nothing on each card.
- **The "withheld explanation" message appears once per list (U3):** each card keeps one quiet line.
- **The finished brief folds its progress card into a chip (U37, S8):** the chip reads "Ready · 7 s" and sits beside Export. It opens the Steps. While a brief builds or after it fails, the full card stays.
- **Form screens use one centred column (U31):** welcome, account, the student start, and Find and pick use a centred 760 px column. Lists, briefs and My Perch use the full 1180 px page column (U7).
- **Lead cards put the title first, on both sides:** the agency, the code and the program move into one muted line under the title. Closes and Amount are always shown, with a muted "Not stated" when missing. This removes the empty-tag bug (M1) for good.
- **Browse lists use dense rows (U38):** the title and the line under it go on the left. Amount and deadline go in a fixed right column. Keep and an icon link to the source go at the far right.
- **Default sort per list (P3):** awards sort "A to Z". Most awards state no date, so a date sort would bury them. Funding sorts by "Closing soonest", which puts open calls first.
- **School counts are hidden while a search or level is set (U1):** this is a front-end fix. `/filters` stays as it is.
- **The page's own deadline words are shown when there is no date (FM3):** `deadline_quote` is already in the browse and brief payloads. The card shows it in quotes under "Deadline", so it never claims "Not stated".
- **P6 waits for round 2:** the "what the rules checked" line needs rule output that the server does not yet return, and the product review asks for a live capture first (S15).
- **The hand-off progress (P7) uses the cheap version, in Tier B:** while the model writes, the box lists the kept lead titles and the office name it already has. There is no server change.

### For Dakshitha

- **None this round.** Every fork above is settled under the S49 delegation. One item needs the orchestrator, not a design choice: route T depends on the back-end function package (FM9). If that package does not ship route T in round 1, FE-A item A9 and BE-S item V6 are dropped.

## 2. Scope for round 1

The budget is about 6 hours of builder time, run by 3 builders in parallel at about 2 hours each. Each package lists its items in build order with minute estimates. **Tier A** must ship. **Tier B** ships only if the package is under budget. A builder cuts from the bottom of Tier B first.

- **Tier A adds up to about 410 minutes:** FE-A is about 140, FE-B about 145 and BE-S about 125. That is about 7 hours, one hour over the target. The must-fix items and the four decisions alone need about 5 hours.
- **The cut line, if the orchestrator holds to 6 hours:** move these to round 2, in this order.
  1. **FE-A A5's ready chip:** keep the tab names and the button label, and leave the progress card as it is. This saves 15 minutes.
  2. **FE-B B4's documents card:** My Perch keeps two cards. This saves 8 minutes.
  3. **FE-B B3's sort select:** keep the "Show closed calls" switch, and keep funding sorted by closing date with no control. This saves 10 minutes. BE-S V1 still ships `open_only` and `sort`. browse.js still sends `sort=closing` on `#/funding`, because the server's default is `name`.
  4. **FE-A A8's pick-screen link:** keep the rerun route. This saves 5 minutes.
  5. **BE-S S1's student card restyle:** keep the withheld line and the deadline quote only. This saves 8 minutes.
- **Why the target slips:** the must-fix list grew by six product items and four decisions after the S48 design was sized.

### Must-fix coverage

Every must-fix item from the five documents is in Tier A:

- **S48 notes and design:**
  - D1 is FE-A A2.
  - D2 is BE-S S6.
  - D3 is FE-A A7.
  - D4 is FE-A A8 with FE-B B4.
  - D5 is FE-A A4 and A1.
- **S48 review:**
  - M1 is FE-A A4.
  - M2 is FE-A A1.
  - M3 is FE-A A1.
  - M4 is FE-A A7.
  - M5 is FE-B B5 and BE-S S5.
  - M6 is FE-B B7.
- **UI/UX review:**
  - U1 is FE-B B3.
  - U2 is FE-B B5 with BE-S V4.
  - U3 is FE-A A5 and BE-S S2.
  - U4 is FE-A A1.
  - U5 is FE-B B6.
  - U6 is FE-B B7.
- **Product review:**
  - P1 is BE-S V2 with FE-B B3 and B4.
  - P2 is BE-S V1 with FE-B B3.
  - P3 is BE-S V1 with FE-B B3.
  - P4 is BE-S V5 with FE-A A3.
  - P5 is FE-B B5 and BE-S S5.
  - P7 is FE-B Tier B.
  - P8 is FE-A A3.
- **Deferred must-fix:** P6 goes to round 2, as decided above.

### Deferred to round 2, with reasons

- **U40, cover points in two columns:** this is a layout rebuild of `pointsBlock`. Round 1 already changes that block for U14 and U15.
- **U46, U47 and U48, profile polish:** the profile tab is not on the demo's main path. U46 is FE-A Tier B.
- **U20, U51 and U52, Scout layout:** these are polish only, and Scout's chat sizing is fragile. U21 ships.
- **U44, owl in empty states:** polish only. It is FE-B Tier B.
- **U45, hide empty Compare columns:** it is FE-B Tier B.
- **U18, a close button on the guest banner:** the compact brief header already gives back the space. It is FE-A Tier B.
- **S14, a shorter samples page:** it is FE-B Tier B.
- **F2, F4, F5, F7, F8, F10, P-D2, P-D3 and P-D4:** these are features or flow rebuilds of a medium-to-large size. They wait until round 1 is stable.
- **F6, delete one brief:** a brief owns cover points, hand-off drafts and a Scout session. A one-row delete would leave those behind. A cascading delete needs its own design and tests.
- **F9, suggested questions in Scout:** Scout already shows example question chips. Moving the tool list behind a disclosure is FE-B Tier B.
- **U49, capitalising rule values on the profile:** it is BE-S Tier B.
- **S4, the match number hint:** the pill already carries a title and screen-reader text. It is FE-A Tier B.
- **S10, Back follows where the user came from:** it is FE-A Tier B.
- **R2, JSON export for students:** it is FE-A Tier B.
- **S2:** declined, as decided above.
- **The type scale cut to 12/14/16/19/24 for old rules:** new and changed rules use the scale. A full sweep of old rules is round 2.
- **S48 review should-fix left for round 2:** splitting the funder and activity-code filter chips, short labels and no indent for cover-point citations (with U40), and an honest match count per section. Each needs a closer look at the data first.
- **S48 review nice-to-have items:** the heading focus ring, equal landing buttons, the account consent row, the phone hand-off box height and dark-mode button borders. They are polish only. B6's textarea sizing covers part of the hand-off box item.

## 3. Build packages

### 3.0 Step 0, done by the orchestrator before any builder starts (about 10 minutes, one commit)

These changes let three worktrees build in parallel without touching each other's files.

- **New stylesheet:** create `web/pages.css` with one comment line, `/* S49: page styles owned by FE-B. Loaded after styles.css. */`.
- **Link it:** in `web/index.html`, add `<link rel="stylesheet" href="pages.css">` right after the styles.css link.
- **Preview script:** in `scripts/build_ui_preview.py`, inline `pages.css` after `styles.css`, the same way styles.css is inlined.
- **Stub for cover notices:** in `web/cover.js`, add `export function coverListLine() { return null; }`. FE-A and BE-S import it. FE-B replaces the body.
- **Walk flow loader:** at the end of `scripts/ux_walk.py`, before `main`, add a loader:
  - **What it imports:** every `scripts/walk_flows/*.py`.
  - **What each module must define:** `register(U) -> tuple[dict, list]`. Here `U` is the ux_walk module, from `sys.modules[__name__]`. The tuple holds the module's flows and its plant names.
  - **What it merges:** the flows into `FLOWS` and the plant names into `PLANTS`, before argparse reads them.
  - **The folder:** create `scripts/walk_flows/__init__.py` empty.
- **Check the new files are served:** the app serves `web/` through a directory mount (`WebFiles`) and the CSP has `style-src 'self'`. After the commit, confirm with one curl that `GET /pages.css` returns 200 from the dev server.
- **Who owns which flow file:** FE-A owns `scripts/walk_flows/s49_fe_a.py`. FE-B owns `scripts/walk_flows/s49_fe_b.py`. BE-S owns `scripts/walk_flows/s49_be_s.py`.

### 3.1 Rules for every package

- **Isolation:** each package is built in its own worktree (`isolation: "worktree"`). It touches only the files it owns. Never switch branches in the main checkout, because the v1 deploy runs from it.
- **Fail first:** every new walk check is written before the code change. The builder runs it on the untouched worktree, records FAIL, implements, then records PASS. Both results and the base commit go in the commit message body as `fail-first: <check> FAIL on <sha>, PASS after`. A check that cannot fail on the old code is not a check: rewrite it.
- **Walk runs:** one walk server runs at a time on port 8191. Start it from your own worktree with `scripts/run_limited.sh`. Use `--only <your flows>` and stop the server when done.
- **Existing checks:** existing walk checks that your change breaks on purpose are updated in your own flow file, never in another package's file. Example: the `scoutmarks` flagged text, or `landing` assuming `#/` is the hero for signed-in users. If the old check lives in `ux_walk.py`, tell the orchestrator. It edits `ux_walk.py` after the merge.
- **Tests:** `make test` passes in your worktree before you hand back. FE-A owns `tests/test_web.py`. FE-B writes new tests only in `tests/test_web_pages.py`. BE-S writes new tests in `tests/test_saved.py`, `tests/test_browse_sort.py` and in the existing compare and export tests.
- **Copy:** all copy in this spec is final. Remove the "DRAFT copy … for Dakshitha to review" comments in the files you touch.
- **Commits:** small commits with the project's attribution trailer, as given in the orchestrator's brief. No session links in commit messages.
- **Escalate instead of guessing:** escalate any record field you would have to invent, any office name not in `perch/offices.py`, any number not from a record, and any change to a file you do not own.

### 3.2 Shared contracts

#### Hash routes (FE-A builds them; FE-B links to them)

- **`#/`:**
  - **Signed in, welcome done:** My Perch home. FE-A's `route()` calls `renderMyPerch(main(), rt, { home: true })` with `screen("home")`.
  - **Everyone else:** the hero landing, as now.
- **`#/me`:** the same My Perch home, with `screen("home")`.
- **`#/start`:** the hero landing (`renderFind`) for anyone. On first entry, a signed-in user's `S.who` follows `session.audience`.
- **`#/find`:** as now. When there are no candidates, `renderPick` redirects to `#/start`, not to `#/`.
- **`#/rerun/<briefId>`:** loads the brief with `api.brief(id)`. Then:
  - **Student brief:** `goReplace("#/student")`. The start screen shows the stored CV and entries, ready to edit.
  - **Researcher brief:** fills `S.find` from the brief and goes with `goReplace("#/find")`, the pick screen with the person already picked. Section A8 has the details.
- **The wordmark** links to `#/` as now. That is My Perch for a signed-in user.

#### Card markup (FE-A styles it; FE-A and BE-S emit it)

```
(list item) .card.lead[.kept][.gone][.is-sample][data-id]
  div.lead-top
    div.lead-name
      h3.lead-title > button.title-btn > span(title) + evMark()
      p.lead-sub            muted line; parts joined by " · "; may hold span.tag.sample / span.tag.ember
    div.lead-end            verdict chip (student only), match pill, div.actions (Keep, Dismiss | Restore)
  dl.facts.facts-2          always two div.fact: [Closes | Deadline] and [Amount]
  ...notes, reasons, explanation...
  p.withheld-line           only on a flagged card (replaces the amber box)
  div.cover                 cover.js
```

- **The title fallback** is `"Untitled opportunity"`, never the record id (D5).
- **A missing fact** is `dd > span.missing` with the text `"Not stated"`.
- **A deadline with no date but a `deadline_quote`** is `dd > span.quote-date` with the text `The page says: “<deadline_quote>”`. It applies to scholarships and Temple opportunities (FM3).

#### List header and notice slot (FE-A and BE-S emit it; FE-B fills it)

Each brief list, on both sides, renders this above its `ol.leads`:

```
div.list-head
  h2.section-title#routes-title        the count heading
  div.sort-group                       the existing Sort switch
p.hint.model-line                      researcher grants only: "Model text is a model's reading of the fit, checked against the records it cites."
div#list-notices
  p.notice.info.list-note              only when two or more visible cards are flagged
  <coverListLine(ctx) result>          from cover.js; null when there is nothing to say
```

- **The flagged note text:** "Some written reasons failed Perch’s citation check, so they are left out. Every date, amount and rule result on the cards is still copied from the record."
- **The per-card withheld line:** `p.hint.withheld-line` with the text "Written reason withheld: it failed the citation check."

#### `coverListLine(ctx)` (FE-B builds it in cover.js)

- **Input:** `ctx` is the same object `coverBlock` takes.
- **Returns for a guest:** `p.list-note` holding icon("pen"), the text "Cover-letter points need an account. ", and `a[href=ctx.signIn]` with the text "Sign in".
- **Returns after a daily-allowance error in this page view:** `p.notice.info.list-note[role=status]` holding the server's message and, when `/usage` answered, " It comes back at <time>." The time is `resets_at` formatted in local time, hour and minute. If it is not today, a short date comes first.
- **Returns otherwise:** `null`.
- **Redraw:** on a quota error, cover.js redraws `#list-notices` itself with `document.getElementById("list-notices")`. If that element is missing, it falls back to the per-card error, as now.

#### Student offices in the brief (BE-S builds and reads it; FE-A passes it)

- **BE-S, server side:** `GET /briefs/{id}` adds `offices` for student briefs only:

```json
"offices": {
  "F": {"key": "sdfa", "name": "Scholar Development and Fellowships Advising", "url": "https://undergraduate.temple.edu/fellowships"},
  "S": {"key": "sfs", "name": "Student Financial Services", "url": "https://sfs.temple.edu/"}
}
```

  The values come from `perch/offices.py` `for_route("F")` and `for_route("S")`. Nothing is typed by hand.
- **FE-A:** `renderStudentPanel` passes `offices: S.brief.offices || api.studentOffices`.
- **BE-S, student.js:** `officeName` already reads `ctx.offices[r].name`. No change is needed beyond checking it.

#### Saved list API (BE-S builds it; FE-B calls it)

All three routes need a signed-in account. A guest gets `403 {"error": "account_required"}`. `POST` and `DELETE` need the CSRF header and consent (`_consented`). `audience` works as on `/me/docs`, through `_side`: the session's side when it is left out. `_side` does not check the account's roles, so the front end chooses the side:

- **Saving from a list:** browse.js sends the list's own side (`student` on `#/awards`, `researcher` on `#/funding`) when the account has that role. Otherwise it sends the session's side, so the item shows on the My Perch the user can open.
- **Reading on My Perch:** the "Kept and saved" card calls `api.saved(side)` for the side shown, and reloads when the side switch changes.

`GET /me/saved?audience=student` returns `200`:

```json
{
  "audience": "student",
  "total": 2,
  "items": [
    {
      "record_id": "temple_pages:example-award",
      "saved_id": "6f1c…-uuid",
      "saved_at": "2026-11-04T21:10:00+00:00",
      "kept_in": [{"brief_id": "9a2e…-uuid", "built_at": "2026-11-03T18:00:00+00:00"}],
      "record": { "...": "the browse item() shape: the record's own fields plus kind, scope, schools, levels, deadline, amount_max, sample, source, source_url, fetched_at" }
    },
    {
      "record_id": "grants_gov:12345",
      "saved_id": null,
      "saved_at": null,
      "kept_in": [{"brief_id": "9a2e…-uuid", "built_at": "2026-11-03T18:00:00+00:00"}],
      "record": null
    }
  ]
}
```

- **What it holds:** one item per `record_id`. That is every `saved_item` row of the side, plus every lead with status `kept` in the side's stored briefs.
- **Kept leads included:** kind `opportunity` or `scholarship` only, never `sample`.
- **`saved_id`:** null when the record is only kept in a brief.
- **`record`:** looked up in the public store at read time. It is null when the store no longer holds it.
- **Order:** first, items whose `record.deadline` is today or later, by date ascending. Then past dates, newest first. Then items with no date, then items with no record. Ties go by title, case-folded. The date is the record's `deadline` column from `columns(r)`. Nothing is computed.

`POST /me/saved?audience=student` with body `{"record_id": "temple_pages:example-award"}`:

- **New:** `201 {"saved_id": "<uuid>", "record_id": "...", "saved_at": "<iso>"}`.
- **Already saved:** `200` with the same shape. The call is idempotent.
- **Unknown record:** `404 {"error": "not_found"}`.
- **A SYNTHETIC record**, by source `synthetic` or an id starting `sample:`: `422 {"error": "sample_not_saved"}`.
- **More than 200 saved on the side:** `409 {"error": "saved_full"}`.
- **Storage:** the row is stored as `SavedItem` (kind `saved_item`), encrypted like every user row. It is never logged with its record id in plain text beside the user id.

`DELETE /me/saved/{saved_id}` returns `200 {"ok": true}`, or `404 {"error": "not_found"}`.

#### Browse parameters (BE-S builds them; FE-B sends them)

Both `GET /awards` and `GET /opportunities` gain two parameters:

- **`sort`:** `name` (the default and the current order), `closing` or `amount`.
  - **`closing`:** dates today or later ascending, then past dates newest first, then no date. Ties go by name, then id.
  - **`amount`:** `amount_max` descending, with nulls last. Ties go by name, then id.
- **`open_only`:** a bool, false by default. When true, it keeps `deadline IS NULL OR deadline >= today`, using the server's date.
- **The cursor** stays opaque to the front end. For `closing` and `amount`, it may be an offset token. The lists hold under 1,000 rows.
- **The response** gains `"sort": "<the sort used>"`. Nothing else changes.

#### Brief summaries (BE-S builds them; FE-B reads them)

- **New fields in each `GET /me/briefs` item:** `"kept"`, the number of kept public leads, and `"sample_kept"`.

#### Compare rows (BE-S builds them; FE-B reads them)

- **The row title:** each `rows[]` item's `title` is the title alone, such as "MPS Chemistry Research Programs".
- **The number:** a new field, `"number"`, holds the opportunity number or `null`.
- **Export:** `perch/export.py` prints `"<number>: <title>"` when there is a number, so the export reads as before.

### 3.3 Package FE-A: brief screen, lead cards, landing, header, routing, base styles

**Files FE-A may touch:**

- `web/app.js`
- `web/styles.css`
- `tests/test_web.py`
- `scripts/walk_flows/s49_fe_a.py`

**Budget:** Tier A is about 140 minutes. FE-A is the critical path, so it starts first.

#### A1. Base stylesheet pass (25 minutes)

Do this first, as its own commit.

- **Merge duplicate rules (U53):** fold the duplicates so each selector is defined once, at its first location.
  - **`.cite`:** lines about 135, 1116, 1127, 1221 and 1455 become one rule.
  - **`.tag.sample`:** lines about 443 and 882 become one rule.
  - **`.foot p`:** lines about 443 and 967 become one rule.
  - **Commit message:** list the computed values that changed. There should be none.
- **New tokens on `:root`:**
  - `--page: 1180px`
  - `--form: 760px`
  - `--fs-12: 12px; --fs-14: 14px; --fs-16: 16px; --fs-19: 19px; --fs-24: 24px`
  - `--s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px; --s-5: 24px; --s-6: 32px`
- **One left edge (U7):** all four containers are `max-width: calc(var(--page) + 32px); margin: 0 auto; padding-left: 16px; padding-right: 16px`.
  - **The four:** `.bar-in`, `#banner p`, `main`, and `.foot p` with `.foot .promises`.
  - **`main` by screen:**
    - `body[data-screen="list"]`, `"brief"` and `"home"` use the page width.
    - `body[data-screen="form"]` uses `max-width: calc(var(--form) + 32px)`, centred, with `padding-top: 32px` (U31, U32).
    - `"landing"` stays 712 px and `"help"` stays 852 px.
- **Citation chips inline (M2):** `.cite` is `display: inline; line-height: inherit; min-height: 0; padding: 0 6px`. Remove the `min-height: 44px` from the `.cite` rule. Inline targets are exempt under WCAG 2.5.8. Keep the 44 px for `.paper-ref` buttons, which are blocks.
- **Visible scrollbar (U4):** delete `scrollbar-color: transparent` on `html` and the `html.bar-near` rule. In app.js, delete the mousemove toggle (about lines 2287 to 2288).
- **Disabled cursor (U9):** `.btn[disabled], .btn[aria-disabled="true"]` get `cursor: not-allowed`. Add `.btn[aria-busy="true"] { cursor: progress; }`.
- **One search focus ring (U23):** `.searchbox:focus-within { outline: 2px solid var(--focus); outline-offset: 2px; }`. Add `.searchbox input:focus-visible { outline: none; }`.
- **Balanced headings (U36):** `.landing h1, h1.page, .lead-title { text-wrap: balance; }`.
- **Boxes do not stretch (M3, D5):** `.box-grid { align-items: start; }`.
- **Lighter dark sample banner (U54):** in dark mode, `.sample-note` uses `background: var(--surface); border: 1px dashed var(--ember);`.

**Walk checks:**

- **`s49_left_edges_1280`:** the left edge of the text inside `.bar-in`, `#banner p`, `main > .screen` and `.foot p` is within 1 px. Measure on `#/awards` and on the guest researcher brief. Old code: 52, 66, 100 and 98, so it fails.
- **`s49_cite_inline`:** on a stubbed explained card, every `.explain .cite` has computed `display: inline` and a height of at most 1.6 times the paragraph's font size.
- **`s49_scrollbar_visible`:** `getComputedStyle(document.documentElement).scrollbarColor` is not `transparent transparent`.

#### A2. Landing fits one laptop screen (D1) (10 minutes)

- **Sizes:**
  - **Hero art:** `.landing .hero-art { height: 96px; }`.
  - **Owl:** 72 px, `top: 12px`.
  - **Gaps:** `.landing { gap: 16px; }`.
  - **Headline:** `.landing h1 { font-size: clamp(36px, 4.6vw, 48px); margin-top: 0; }`.
  - **Lede:** `.landing .lede { margin-top: -6px; }`.
- **Short screens:** `@media (max-height: 740px)` hides `.landing .hero-art .scene` and keeps the owl at 56 px.
- **Promises:** `.foot .promises` is one row at 1280: `flex-wrap: nowrap; gap: 32px; font-size: var(--fs-14)`.
- **Footer promise text:** FE-B changes it in index.html (B10).

**Walk check:**

- **`s49_landing_no_scroll`:** signed out, at 1280×720 and 1366×768, on both the Student and the Researcher tab, `document.documentElement.scrollHeight <= innerHeight`. Old code at 1280×720 is about 860, so it fails.

#### A3. Header, guest paths, signed-in home (20 minutes)

- **One sign-in link for guests (U17):** while the guest banner shows, `drawWho` draws no header "Sign in" button. The "Guest" chip stays. The banner's link is the one sign-in.
- **One guest path when sign-in is down (U19, R5):** when `S.signinDown`, the Student tab drops `guestLine`. The fit button "Try a sample student" stays. The Researcher tab keeps `guestLine`, because it is that tab's only guest path.
- **A My Perch link for signed-in users (P8):** add `a.btn.quiet#my-perch-link` with the text "My Perch" and `href="#/"`. It goes before the account button, at 480 px and wider. Under 480 px it is hidden, because the menu already holds "My Perch". Set `aria-current="page"` on it when the screen is home.
- **Routing:** build the routes in section 3.2: `#/` home for signed-in users, `#/me`, `#/start`, and `#/rerun/<id>`.
  - **Change in `renderPick`:** `goReplace("#/")` becomes `goReplace("#/start")`.
  - **Change in `renderMissing`:** its button goes to `#/` with the text "Back to the start".
- **P4 glue:** pass `offices: S.brief.offices || api.studentOffices` in `renderStudentPanel`.

**Walk checks:**

- **`s49_guest_one_signin`:** a guest on a brief has exactly one visible link whose text is "Sign in" in `header` and `#banner` together. Old code has two, so it fails.
- **`s49_signed_in_home`:** with the mocked signed-in session (`flow_mocked` stubs, plus `/me/saved` and `/me/briefs` stubs), `#/` renders `h1` "My Perch" and `#my-perch-link` is visible at 1280. Old code renders "Find funding that fits.", so it fails.

#### A4. Researcher lead card (30 minutes)

- **Markup:** follow the card markup in section 3.2 exactly.
- **The line under the title:** `p.lead-sub` joins these parts with " · ", skipping empty parts:
  1. `f.agencyShort(o.agency, o.parent_agency)`
  2. `o.activity_code`
  3. a status tag: "Forecast", or the status word when it is not "posted"
- **When every part is empty:** there is no `p.lead-sub`. No empty tag is ever drawn (M1).
- **The opportunity number** leaves the card (R3). It is still in the evidence panel, which shows every field.
- **Facts (D5):** always two facts.
  - **First fact:** "Closes" or "Announcement", with the current far-date, expiry and note rules.
  - **Second fact:** "Amount", with `f.awardSize(o)`, or `span.missing` "Not stated".
  - **Removed:** the old `p.no-size` line.
  - **Urgency:** `soon` and `closed` colour the `dd` text, `var(--ember)` and `var(--brick)`. There is no tinted box.
- **Withheld text (U3):** a flagged card shows `p.hint.withheld-line` instead of the amber `.notice.warn`.
- **Model text said once (U43):** the per-card provenance line "Checked against the records it cites." goes. `p.what` starts with the small `span.tag.model` "Model text", followed by the sentence. The list header carries `p.model-line` from section 3.2.
- **List header:** build the `div.list-head` and `div#list-notices` from section 3.2. `#list-notices` holds the flagged note and `coverListLine(ctx)`. The route row holds only the route switch (U10).
- **CSS:**
  - **Card:** `.card.lead { padding: 18px 20px; gap: 10px; }`. Between cards: `ol.leads { gap: 12px; }`.
  - **Top row:** `.lead-top { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px 16px; align-items: start; }`.
  - **End block:** `.lead-end { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; }`.
  - **Title:** `.lead-title { font: 600 var(--fs-19)/1.3 var(--serif); }`.
  - **Sub line:** `.lead-sub { margin-top: 2px; font-size: var(--fs-14); color: var(--ink-3); }`.
  - **Facts:** `.facts-2 { display: flex; flex-wrap: wrap; gap: 4px 32px; margin: 0; }`.
  - **One fact:** `.facts-2 .fact { background: none; padding: 0; }`.
  - **Fact label:** `.facts-2 dt { font-size: var(--fs-12); letter-spacing: .04em; text-transform: uppercase; color: var(--ink-3); font-weight: 600; }`.
  - **Fact value:** `.facts-2 dd { font-size: 15px; font-weight: 600; }`.
  - **Missing value:** `.facts-2 .missing { color: var(--ink-3); font-weight: 500; }`.
  - **Withheld line:** `.withheld-line { font-size: var(--fs-14); color: var(--ink-3); }`.
  - **Cover block:** `.lead .cover { margin-top: 0; }`. This closes the gap above the cover button.
  - **Evidence mark (S48 review):** `.lead-title .ev-mark { font-size: 13px; vertical-align: baseline; }`.
  - **"Why it fits" on one line (S48 review):** `.why > summary > span:first-child { white-space: nowrap; }`.
  - **Filter chips wrap (S48 review):** `.filter-box` chips use `flex-wrap: wrap`, so no chip is cut off at the edge.
- **Phone, under 600 px:**
  - **Top row:** `.lead-top { grid-template-columns: 1fr; }`.
  - **End block:** `.lead-end { justify-content: space-between; flex-wrap: wrap; }`. The pills sit on the left and the actions on the right, on one row under the title (S6).
- **Student card CSS:** the same classes serve the student card. Add `.reason` and `.fit-reason` spacing of 6 px. Add `.about-list` for BE-S S2, styled like `details.more-opts`, with the summary at 14 px, 600 weight, `var(--ink-2)`.

**Walk checks:**

- **`s49_no_empty_tag`:** no `.lead .tag` and no `.lead .lead-sub` has empty text, on both briefs. It needs a stubbed lead with no agency. Old code draws an empty agency tag for that lead, so it fails.
- **`s49_title_first`:** in every `.lead`, the first visible text-bearing element is the `.lead-title`. Old code: the tags come first, so it fails.
- **`s49_two_facts`:** every non-dismissed researcher `.lead` has exactly two `.facts-2 .fact`.
- **`s49_card_height`:** at 1280, the median height of the first five grant cards is at most 260 px. Old code: about 400 with the cover button, so it fails.
- **`s49_phone_title_top`:** at 360, each card's `.lead-title` top is above its first `.actions` button top. Old code: the buttons come first, so it fails.

#### A5. Brief header folds once ready (U37, S8, U8, U55, S3, U11) (20 minutes)

- **When the brief is done:** `renderProgress` draws `details.ready-chip` inside `div.brief-tools`, to the left of Export. The large `.pcard` is not drawn.
  - **Summary:** `owl("done", "owl-xs")`, then the text "Ready · <elapsed>", for example "Ready · 7 s". The elapsed time uses the existing `f.elapsed`.
  - **Popover:** the same Steps `ol`, at 360 px wide and absolutely positioned under the chip, like `.export-pop`. Escape closes it and returns focus to the summary.
  - **Data:** this is purely client time from stage timestamps, as now.
- **While queued, running or failed:** the full `.pcard` stays as now. Its Steps summary drops the "(n of m done)" count once done (U8). When done, the chip replaces it anyway.
- **Header rhythm (U55):**
  - **Brief gap:** `.brief { gap: 16px; }`.
  - **Back to title:** 8 px, using `.brief > .back + .title-row { margin-top: -8px; }`.
  - **Sample note and tabs:** they follow at 16 px.
- **Change details button (signed-in only):** in `div.brief-tools`, add `a.btn.quiet` "Change details and run again" with `href="#/rerun/<id>"`. Under 700 px it moves into the Export menu as its first row.
- **Tab names (S3):** the second tab reads "What Perch read" on both sides. The short label is "Read" on both.
- **Shortlist button (U11):** "Compare and draft" on both sides. The disabled state is an outline button with the hint "Keep a lead first" under it (S48 review).

**Walk checks:**

- **`s49_first_lead_top`:** at 1280, for the guest researcher brief with the guest banner showing, the first `.lead`'s top is at most 500 px. Old code is about 632, so it fails.
- **`s49_ready_chip`:** once the brief is done, `.ready-chip` exists, no `.pcard` is visible, and pressing the chip shows the Steps list.
- **`s49_tab_names`:** `#tab-profile` reads "What Perch read" on both briefs. Old code reads "Profile" on the researcher brief, so it fails.

#### A6. Lead list head on both sides (5 minutes)

- **What it is:** build the `div.list-head` row from section 3.2, with the count heading on the left and Sort on the right. It is the same on the researcher side (here) and the student side (BE-S S3).
- **Phone (U27):** under 560 px, `.list-head` wraps. The sort group sits on its own line, left-aligned, with `width: auto`. The sort buttons use the same height and padding as the route switch: `.sort-switch .route-btn { min-height: 40px; padding: 0 14px; }`.

**Walk check:**

- **`s49_sort_on_count_row`:** on both briefs at 1280, `.sort-group` and `#routes-title` share a row: their vertical centres are within 12 px. Old student code puts Sort on its own row, so it fails.

#### A7. Researcher CV card on the first visit (D3, M4) (15 minutes)

- **Placement:** `cvBox()` moves out of the folded "Tell Perch more" panel. It renders right under the picked candidate card and above the panel.
- **Signed in:**
  - **Heading:** `section.box` with `h2.section-title` "Add your CV (optional)".
  - **Hint:** "Used for cover-letter points and Scout. Stored encrypted. Contact details are blanked before a model reads it."
  - **Stored documents:** shown as ticked checkboxes, as now. A new upload is ticked automatically.
  - **Upload control:** `label.btn[for=r-cv-file]` with the text "Upload a file", and a hidden `input#r-cv-file[type=file][accept=".pdf,.docx,.txt,.md"]`.
  - **Paste control:** a `details` with the summary "Paste text instead". It holds a `textarea#r-cv-text` (6 rows, maxlength 60000) and a `button.btn` "Save my CV".
  - **The call:** `api.addDoc({kind: "cv", filename, data}, "researcher")` for a file. `api.addDoc({kind: "cv", text, filename: "cv.txt"}, "researcher")` for pasted text.
  - **No documents yet:** "No stored documents yet."
- **Guest:** `p.note` with the text "Sign in to add your CV." and a `Sign in` link.
- **Signed out:** no box, as now.

**Walk check:**

- **`s49_cv_card_visible`:** on the mocked signed-in pick screen, `#r-cv-file` exists and is not inside a closed `details`. Old code: the box is inside the folded panel and its text says "Check my fit page", so it fails.

#### A8. Change details and run again (D4) (15 minutes)

- **`#/rerun/<id>` for a researcher brief:**
  - **The candidate:** `cand = {id: researcher.id, display_name, institutions, orcid, works_count, cited_by_count, topics: []}`, from `brief.researcher`.
  - **Fill `S.find`:** `q: display_name`, `candidates: [cand]`, `picked: cand`.
  - **Options from `brief.brief.options`:**
    - `direction` from `direction`.
    - `include` from `include_keywords`, joined with ", ".
    - `exclude` from `exclude_keywords`, joined with ", ".
    - `stage` from `career_stage`.
    - `minAmount` from `min_amount`, as a string.
    - `explain` from `explain`.
    - `docIds` from `doc_ids` (a Set).
  - **Missing keys:** a key absent from the options stays blank.
  - **Then:** `goReplace("#/find")`.
- **Pick screen link:** with someone picked, add `a.quiet-link` with the text "Choose someone else" and `href="#/start"`, beside "Back to the matches".
- **Guests** keep "Start again" and "Back", as now.

**Walk check:**

- **`s49_rerun_prefills`:** with a mocked brief whose options hold `direction: "SYNTHETIC test direction"`, `#/rerun/<id>` lands on `#/find` with `#ctx-direction` holding that text. Old code has no route and shows the landing, so it fails.

#### A9. Temple internal route (FM9 contract) (10 minutes; drop it if the function package does not ship route T)

- **When it shows:** `routeSwitch()` gets a third button, "Temple internal", with key `T`, between Grants and Industry. It shows only when `routeLeads("T").length > 0`. Its readiness follows `route_a`.
- **The list:** `renderRoutes` treats T like A, with the same `leadCard`, sort and filters.
- **Heading:** "<n> Temple internal calls".
- **Hint under the heading:** "Temple’s own funding calls for faculty, kept apart from federal grants. Each call’s page says whom to contact."
- **Shortlist label:** `KIND_SHORT.T = "Temple"`.

**Walk check:**

- **`s49_route_t_apart`:** with a stubbed brief holding A and T leads, pressing "Temple internal" lists only T leads. No T lead appears under Grants.

#### FE-A Tier B, in order

- **U18:** a close button on the guest banner, remembered in `sessionStorage` key `perch.guestBannerClosed`, inside try and catch. When it is closed, the header "Sign in" comes back.
- **S10:** the brief's Back goes to the hash the user came from (`S.briefFrom`), when that was `#/`, `#/me`, `#/find` or `#/student`.
- **R2:** a student brief's Export menu drops "Records as JSON".
- **U46 and S5:** a past horizon date uses the body size. Above it, a plain line reads "No running federal award found in the linked records."
- **S4:** the Match pill's `title` reads "Match: how closely the listing’s text matches <what>, from 0 to 100. It is not the odds of funding."

**FE-A Tier A total: about 140 minutes**, plus 10 for A9 if route T ships.

### 3.4 Package FE-B: lists, My Perch, account, compare, hand-off, cover points, Scout, help

**Files FE-B may touch:**

- `web/browse.js`
- `web/account.js`
- `web/compare.js`
- `web/handoff.js`
- `web/cover.js`
- `web/scout.js`
- `web/help.js`
- `web/api.js`
- `web/index.html`
- `web/pages.css`
- `tests/test_web_pages.py` (new)
- `scripts/walk_flows/s49_fe_b.py`

FE-B never edits `styles.css`. Its rules go in `pages.css`, which loads after styles.css.

**Budget:** Tier A is about 145 minutes.

#### B1. api.js (5 minutes)

Add these methods:

- `saved: (side = null) => p(\`/me/saved${query({ audience: side })}\`)`
- `save: (recordId, side = null) => post(\`/me/saved${query({ audience: side })}\`, { record_id: recordId })`
- `unsave: (savedId) => p(\`/me/saved/${encodeURIComponent(savedId)}\`, { method: "DELETE" })`
- `usage: () => p("/usage")`
- `samples(audienceName, cursor, limit)`: an optional `limit`, for Tier B S14.
- **`list(kind, params)`:** this already passes any params. Callers add `sort` and `open_only`.

#### B2. pages.css base (3 minutes)

- **Section comments:** add one fenced comment per screen in the order of this package.
- **Type scale:** use the tokens FE-A adds (`--fs-*`, `--s-*`). Until the merge, write the literal values with the token as a fallback, for example `font-size: var(--fs-14, 14px)`.

#### B3. Browse lists: dense rows, Keep, sort, closed calls (45 minutes)

- **Row markup:** replace `recordCard` with this markup:

```
(list item) .award-row[.is-sample][data-id]
  div.ar-main
    h3.ar-title > button.title-btn > span(name || "Untitled award") + evMark()
    p.ar-sub          parts joined " · ": schools, level words, "Open to one school" | "Open across Temple",
                      sponsor (temple_sdfa), agency (opportunities); span.tag.sample first on a sample;
                      span.tag.ember "Temple-funded" when temple_funded
    blockquote.ar-quote   first eligibility quote, clamped to 2 lines (-webkit-line-clamp: 2)
  div.ar-facts
    dl  dt "Amount" dd …    dt "Deadline"|"Closes" dd …
        | one p.missing "No amount or deadline on the page" when both are missing (U24, S1)
    p.ar-src  "Source: <SOURCE_WORDS>"
  div.ar-acts
    button.btn.keep (signed in, not a sample)    a.btn.icon-only[href=source_url] aria-label="Open at source: <name>" title="Open at source"
```

- **Dropped tag (U25):** "Scope not stated on the page" is gone from the row. Evidence still shows the field.
- **Deadline with no date but `deadline_quote` (FM3):** the deadline `dd` reads `The page says: “<quote>”`, in 13 px muted text.
- **Past date:**
  - **Awards:** `span.tag.past` "Past date on the page". In pages.css, `.tag.past { background: var(--chip); color: var(--ink-2); }`.
  - **Funding:** `span.tag.closed` "Closed".
- **Row CSS:**
  - **Grid:** `.award-row { display: grid; grid-template-columns: minmax(0, 1fr) 220px auto; gap: 4px 24px; align-items: start; padding: 14px 18px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-card); }`.
  - **Between rows:** `ul.award-list { display: grid; gap: 8px; list-style: none; padding: 0; margin: 0; }`.
  - **Title:** `.ar-title { font: 600 17px/1.3 var(--serif); }`.
  - **Sub line:** `.ar-sub { font-size: 13px; color: var(--ink-3); margin-top: 2px; }`.
  - **Quote:** `.ar-quote { margin: 6px 0 0; padding-left: 10px; border-left: 2px solid var(--line); font-size: 14px; color: var(--ink-2); }`.
  - **Facts column:** `dl` uses `grid-template-columns: auto 1fr; gap: 2px 10px;`. `dt` is 12 px uppercase `var(--ink-3)`. `dd` is 14 px, 600 weight.
  - **Samples:** `.award-row.is-sample { border-style: dashed; border-color: var(--ember); }`.
  - **Phone, under 600 px:** `grid-template-columns: 1fr;`. `.ar-acts` is a row with `justify-content: space-between`.
- **Filter bar:**
  - **Row 1:** the search box (flex 1), then `div.field-pick` with a visible label "Level of study" and the select (U26). Then `div.field-pick` with the label "Sort by" and a select.
    - **Awards sort options:** "A to Z" (`name`, the default), "Deadline soonest" (`closing`), "Largest amount" (`amount`).
    - **Funding sort options:** "Closing soonest" (`closing`, the default), "A to Z" (`name`), "Largest award" (`amount`).
    - **Heights:** the search, the selects and the Search button are all 44 px tall (S48 review).
    - **Labels:** 13 px, `var(--ink-3)`, above the control.
  - **Row 2:** the school chips wrap onto as many lines as they need (S11). There is no sideways scroller.
  - **Hidden counts (U1):** while `st.q` or `st.level` is set, no chip shows a count.
  - **Row 3, funding only:** the "Temple only" switch, then a switch "Show closed calls" (`role="switch"`), off by default. Off sends `open_only=true`.
- **Keep on rows (P1, F1):**
  - **Who sees it:** signed-in users only, and never on a sample row.
  - **Saved state:** on list load, call `api.saved(saveSide)` once and build a map from `record_id` to `saved_id`. `saveSide` is the list's side when the account has that role, else the session's side (section 3.2).
  - **Saving:** `api.save(recordId, saveSide)`.
  - **Pressing Keep:** calls `api.save` and changes the button to "Kept" with `aria-pressed="true"`.
  - **Pressing Kept:** calls `api.unsave`.
  - **On error:** revert the button and `announce(e.message)`. On 403 `consent_required`, announce "Agree to the consent first."
- **Line for visitors who are not signed in:** above the list, `p.hint.keep-line` with the text "Sign in to keep <noun>. What you keep, with its date, collects on My Perch." and a "Sign in" link. `<noun>` is "awards" or "calls".
- **Samples screen gap (U33):** the sample notice goes after the title's wrapper `div`, not inside it, so the normal 22 px gap applies.

**Walk checks (`awards` and `funding` stubs are not needed; use the walk server's data):**

- **`s49_row_height`:** at 1280, the median `.award-row` height on `#/awards` is at most 130 px. Old cards are 230 to 290 px, so it fails.
- **`s49_no_double_not_stated`:** no `.award-row` shows "Not stated" twice.
- **`s49_counts_hide_on_search`:** after a search for "zzzzqqxx", no `.tag-chip .n` is visible. Old code still shows "CST 25", so it fails.
- **`s49_funding_hides_closed`:** on `#/funding` by default, no row has a `.tag.closed`. After "Show closed calls", at least one does. Old code shows closed calls first, so it fails.
- **`s49_level_label`:** a visible label "Level of study" is bound to `#list-level`.
- **`s49_keep_saves`:** in `flow_mocked`, with a `/me/saved` stub that counts POSTs, pressing Keep on the first row sends one POST with that row's `record_id`. The button then reads "Kept".
- **`s49_no_keep_on_samples`:** `#/samples/student` has no `.keep` button, signed in or not.

#### B4. My Perch home (P-D1, U41, U30, F3) (35 minutes)

The signature is `renderMyPerch(root, ctx, { home })`. With `home` set, there is no Back link.

- **Layout:**

```
div.screen.my-perch
  div.title-row   h1.page "My Perch"   [side seg, when both roles]
  p.page-sub      student: "Your kept awards, their dates and your briefs."
                  researcher: "Your kept calls, their dates and your briefs."
  div.start-row   student: a.btn.primary "Browse Temple awards" (#/awards), a.btn "Check my fit" (#/student)
                  researcher: a.btn.primary "Find a researcher" (#/start), a.btn "Browse funding" (#/funding)
  div.home-grid
    section.box.home-kept   h2 "Kept and saved"
    section.box.home-briefs h2 "Briefs"
    aside.box.home-docs     h2 "Your documents"
```

- **Grid:** `.home-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 24px; align-items: start; }`. Kept and Briefs stack in the first column. Documents is in the second. Under 900 px it is one column, in the order Kept, Briefs, Documents.
- **Kept and saved:** from `api.saved(side)`, in the server's order. Each row, a list item `.kept-row`:
  - **Title:** a `button.title-btn` that opens Evidence via `ctx.openEvidence(record, opener)`.
  - **Date:**
    - **Upcoming:** "Closes <formatDate(deadline)>" plus `span.rel` from `f.closesIn(days)`.
    - **Past:** for awards, `span.tag.past` "Past date on the page"; for opportunities, `span.tag.closed` "Closed".
    - **No date:** if `deadline_quote` exists, `The page says: “<quote>”`. Otherwise the muted text "No date on the record".
  - **From line:** "Saved from the list", or "Kept in your brief of <formatDate(built_at)>". When both apply, the two are joined with " · ".
  - **Remove:** `button.btn.quiet` "Remove", only when `saved_id`. It calls `api.unsave`.
  - **Record gone:** if `record` is null, the row reads "This record is no longer in Perch’s data." with Remove.
  - **Empty state:** `owl("look", "owl-sm")`, then "Nothing kept yet. Press Keep on an award and it shows here with its date." and `a.btn` "Browse Temple awards". Researchers see "calls" and "Browse funding".
- **Briefs (U30):** from `api.myBriefs(side)`, newest first. Each row:
  - **Title:**
    - **Student:** "Options checked <formatDate(created_at)>".
    - **Researcher:** the first three topics, or "Researcher brief, <date>".
  - **Meta line:** "<n> leads · <k> kept", plus " · <s> sample" when `sample_leads` is above 0.
  - **Status:** shown only when it is not "done": "Still building" for queued or running, "Stopped" for failed.
  - **Actions:** `a.btn` "Open", and `a.quiet-link` "Change details and run again" (`#/rerun/<id>`).
  - **Empty state:** "No briefs yet." with the start button for the side.
- **Your documents:** from `api.docs(side)`.
  - **CV stored:** "CV stored: <name>".
  - **No CV:** "No CV stored." with a link "Add your CV" to `#/student` for students, or `#/start` for researchers.
  - **More documents:** "<n> other documents".
  - **Footer link:** `a.quiet-link` "Manage in Account and data" (`#/account`).
- **Guest version:** keep the current guest My Perch, but change its line to "Sign in to keep awards, their dates and your briefs."

**Walk checks (in `flow_mocked`, with stubs for `/me/saved`, `/me/briefs` and `/me/docs`):**

- **`s49_home_three_cards`:** `#/` signed in shows `.home-kept`, `.home-briefs` and `.home-docs`. At 1280, `.home-docs` sits to the right of `.home-kept`.
- **`s49_kept_sorted`:** with the stub returning an upcoming date, a past date and no date, the rows show in that order. The past one shows "Past date on the page".
- **`s49_brief_row_named`:** no brief row title is "Student brief", and no row shows the word "done". Old code shows both, so it fails.

#### B5. Compare (M5, P5, U2, S7) (8 minutes)

- **Order:**
  1. The heading, the hint and the sort select.
  2. The industry notice.
  3. The table.
  4. `div.handoff-box`.
- **Row heading:** the route tag, then `span.row-title` (`r.title`), then `span.row-num` (`r.number`, 13 px, muted, its own line) when it is not null, then the office note.
- **Phone pills (U28):** in pages.css, `.compare.stack td .verdict, .compare.stack td .fit { justify-self: start; width: auto; }`.

**Walk checks:**

- **`s49_compare_table_first`:** in the researcher Compare tab, the `.compare-wrap` top is above the `.handoff-box` top. Old code puts the hand-off first, so it fails.
- **`s49_compare_title_clean`:** no `.row-title` matches `/^[\w.-]+-\d+:/`. This needs BE-S V4. Until the merge, run it against a stubbed `/compare` response.

#### B6. Hand-off (U5, U12, U13, U34) (8 minutes)

- **Readable disabled hint (U5):** in pages.css, `.office-opt.off { opacity: 1; }`, `.office-opt.off input, .office-opt.off b { opacity: .55; }`, and `.office-opt.off .hint { color: var(--ink-3); }`.
- **Textarea size (U12):** `rows` = `min(18, max(8, wrappedLines + 1))`. Here `wrappedLines` is the sum over the body's lines of `max(1, ceil(line.length / 80))`.
- **Draft again (U13):** once a draft exists, the top action row has no button. "Draft again" becomes a `button.btn.quiet` after "Open in my mail app" in the draft's action row.
- **To line (U34):** "To: add the address yourself."

**Walk check:**

- **`s49_draft_again_below`:** in `flow_handoff`, after a draft, the `[data-key=handoff-make]` top is below the `#handoff-body` top.

#### B7. Cover-letter points on cards (U6, U14, U15, U16, M6) (20 minutes)

- **Guests (U16):** `coverBlock` returns `null` for guests. Build `coverListLine` as in section 3.2.
- **Points again under the points (U14):** with a result, the order is `pointsBlock`, then the action row with "Points again".
- **Short heading (U15):** `pointsBlock(p, ctx, { short: true })` puts "Cover-letter points" in the summary. Scout's call keeps the long heading "Points for your cover letter: <title>".
- **Allowance used (U6):** on 429 `quota_exceeded`:
  - Set the module state `QUOTA = { text: e.serverMessage || "You have used today’s model allowance." }`.
  - Try `api.usage()` once for `resets_at`.
  - Redraw `#list-notices`.
  - On the card, show only `p.hint` "Today’s allowance is used. See the note above the list."
- **Phone heading (M6):** in pages.css, `.scout-points > summary { flex-wrap: nowrap; }` and `.scout-points > summary > span:first-child { flex: 1; min-width: 0; }`.

**Walk checks (extend `flow_cover`'s stubs):**

- **`s49_cover_guest_once`:** a guest brief has 0 `[data-cover] a` sign-in links and exactly one `#list-notices a` "Sign in". Old code has one per card, so it fails.
- **`s49_quota_once`:** after two cards get a stubbed 429 `quota_exceeded`, there is one `#list-notices .notice` and no `.cover .notice.error`.
- **`s49_points_again_below`:** after a result, the "Points again" top is below the `.scout-points` top.

#### B8. Account and welcome (U22, U32, U35, R6, S13) (8 minutes)

- **Label (U35, S12):** "Using Perch as".
- **Strong delete confirm (U22):** in pages.css, `#del-go { background: var(--brick); border-color: var(--brick); color: var(--bg); }`. This passes contrast in both themes. The opener and Cancel keep their current styles.
- **Welcome top space (U32):** in pages.css, `.screen.welcome { padding-top: 44px; }`.
- **Version line (R6):** delete the welcome hint "Consent text, version N.". The account page keeps the version.
- **Graduate hint (S13):** under "1. What brings you here?", the hint becomes "You can pick both. Graduate students: pick Student for fellowships, and Researcher too if you have published papers."

**Walk check:**

- **`s49_delete_confirm_solid`:** the computed background of `#del-go` equals the computed `--brick`.

#### B9. Scout (U21) (3 minutes)

- **One warning for a flagged answer:** the provenance line under the amber notice reads only "Written by a model." Update the `scoutmarks` constant in `s49_fe_b.py`'s copy of the check, and tell the orchestrator to update `CHECKED_FLAGGED` in `ux_walk.py` after the merge.

#### B10. index.html and help (12 minutes)

- **Footer promise:** "Your CV is encrypted and deletable."
- **Comments:** remove the "DRAFT copy" comments.
- **Help:** update `web/help.js` as section 4 says.

#### FE-B Tier B, in order

- **P7, cheap hand-off progress:** while the model writes, the box lists "Leads in this note:" and the kept titles for that office. Above the status line, it shows the office name.
- **U45:** hide a Compare column when every row's cell text equals `C.data.none`. Add a note under the table: "<label>: none of these records state one."
- **U44:** `owl("look", "owl-md")` in the browse empty state and the list error state.
- **S14:** the samples page loads 12 records, then "Show more".
- **F9:** in Scout's welcome, the example question chips come first. The `CAN_USE` list moves into `details` with the summary "What I can do".

**FE-B Tier A total: about 145 minutes.**

### 3.5 Package BE-S: server routes and fields, and the student screens

**Files BE-S may touch:**

- `perch/browse/routes.py`
- `perch/store/base.py`
- `perch/store/postgres.py`
- `perch/store/sqlite.py`
- `perch/store/hybrid.py`
- `perch/user/routes.py`
- `perch/user/saved.py` (new)
- `perch/compare.py`
- `perch/export.py`
- `perch/api.py`, only the `brief_view` function and the router include for `/me/saved`
- `web/student.js`
- `web/sample_student.js` (new)
- `tests/test_saved.py` (new)
- `tests/test_browse_sort.py` (new)
- the existing compare and export tests
- `scripts/walk_flows/s49_be_s.py`

**Conflict warning for the orchestrator:** the back-end function package (FM1, FM3, FM7, FM9) and the back-end correctness package (B1 touches `perch/api.py` near `get_brief`) may also edit `perch/api.py` and `perch/compare.py`. Run them after BE-S merges, or give them disjoint functions.

**Budget:** Tier A is about 125 minutes. Server work is about 75 minutes and student screens are about 50.

#### V1. Browse sort and open-only (30 minutes)

- **What:** the contract in section 3.2, built in both stores and passed through by `hybrid.py`.
- **Postgres:** use the `deadline` and `amount_max` columns.
- **Tests:**
  - **Order for each sort:** on a SYNTHETIC fixture set in sqlite, test the order for each sort, with nulls last.
  - **`open_only`:** it keeps a record with a null deadline and drops a past one.
  - **Paging:** two pages of `closing` with `limit=2` give the same order as one page.

#### V2. Saved list (30 minutes)

- **What:** `perch/user/saved.py` holds the logic. `perch/user/routes.py` holds the three routes from section 3.2.
- **Reading records:** reuse the repository factory that `perch/api.py` passes to `make_router`. If the user router cannot reach it, expose it on `app.state` in the same place the router is included. Build `record` with `perch.browse.routes.item`.
- **Tests (SYNTHETIC user and records):**
  - **Idempotent POST:** a second POST returns 200 with the same `saved_id`.
  - **Samples refused:** a sample id gets 422.
  - **Merge:** a kept lead in a stored brief and a saved row for the same record become one item with both `saved_id` and `kept_in`.
  - **Order:** upcoming, then past, then none.
  - **Guests:** 403.
  - **Delete:** DELETE removes the row.
  - **No plain text:** no plain record id appears in the audit log or app log lines the route writes.

#### V3. Brief summaries (3 minutes)

- **What:** `kept` and `sample_kept` in `_summary`, from `StoredBrief.leads`.

#### V4. Compare number (8 minutes)

- **What:** `Row.number`. The title is the title alone. Export composes `"<number>: <title>"`.
- **Tests:** update the existing compare and export tests to the new shape.

#### V5. Student offices in the brief (4 minutes)

- **What:** `offices` in `brief_view` for student briefs, as in section 3.2.
- **Test:** a student brief view holds the two names from `perch/offices.py`.

#### V6. Route T in Compare (10 minutes; only if the function package ships route T)

- **Rows:** `compare()` includes route T leads, built like route A, with `Row.route = "T"`.
- **Office cell:** `Cell("Named on the call’s page", None, rid)`. Perch does not say which Temple office handles internal calls. That is UNVERIFIED and is not invented.
- **Hand-off list:** `rows_json` `offices` stays A and B only.

#### S1. Student card markup (12 minutes)

- **Markup:** the card follows section 3.2.
- **The line under the title:** `r.sponsor`, `r.award_type`, "NIH <activity_code>", and the tag "Forecast: not open yet", joined with " · ".
- **`.lead-end`:** the verdict chip, the match pill and the actions.
- **Facts:**
  - **Always two:** "Deadline" and "Amount".
  - **Fellowships:** these opportunities show "Amount" as `span.missing` "See the record".
  - **Page words:** a date or amount copied from the award's page keeps `span.from-page` " from the award's page".
  - **Deadline quote (FM3):** a deadline with no date but `deadline_quote` shows `The page says: “<quote>”`.
- **Removed:** the old "Deadline and amount: not stated in the record." line. `NO_FACTS` leaves the common-lines logic.

#### S2. Student list head and preamble (U3, U42, R4) (12 minutes)

- **Order under the route row:**
  1. `div.list-head` with the count heading and Sort, as in section 3.2.
  2. `details.about-list` with the summary "About this list". Inside it go the source paragraph and the "Unless a card says otherwise" lines, when there are any.
  3. `div#list-notices` with the flagged note and `coverListLine(ctx)`.
- **Flagged cards (U3):** a flagged card shows `p.hint.withheld-line`. The amber box goes.
- **Sample route:** the sample route's `notice.warn.sample-note` stays above the list head. It is a rule 11 banner and is never folded.

**Walk checks:**

- **`s49_student_withheld_once`:** on the sample student brief with the fake model, there are at most one `.list-note` and 0 `.lead .notice.warn`. Old code has one per card, so it fails.
- **`s49_student_preamble_folded`:** the first `.lead` top is at most 120 px below `#routes-title`'s bottom. Old code is about 180, so it fails.

#### S3. Sort on the count row (U10) (2 minutes)

- **What:** the student route row holds only the route switch. Sort sits in `.list-head`. FE-A's check `s49_sort_on_count_row` covers it.

#### S4. Labels and copy (U29, U34) (3 minutes)

- **Matching headings (U29):** add `h3.mini` "Your interests" before the interests list.
- **To line (U34):** "To: add the address yourself."
- **Interests text cut at a word (S48 review):** the 220-character cut in `studentProfile` ends at the last space before 220, followed by "…".

#### S5. Student compare order (P5) (4 minutes)

- **What:** the tables come first, then `section.handoff`, the note. The sample `notice` stays first.

#### S6. Load sample on the signed-in student start (D2) (18 minutes)

- **`web/sample_student.js`:** exports `SAMPLE_STUDENT = { cv, interests, achievement }`.
  - **The text:** a shortened version of `data/synthetic/persona-ug/cv.md`, `interests.md` and the first item of `achievements.md`.
  - **First line of each text:** "SYNTHETIC example student (invented). Canary: <that file's canary token>".
  - **What it must not hold:** no persona name, email, phone, street or link. Use "Sample student" where a name would go.
- **The button:** only when no CV is stored. A quiet `button.btn.quiet[data-key=load-sample]` with the text "Load sample" sits in a row with the "Your CV" heading.
- **Hint under the button:** "Fills the boxes with an invented student. Nothing is saved until you press Save."
- **Pressing it:** fills `#cv-text`, `#st-interests` and `#st-ach`. It shows `span.tag.sample` "SYNTHETIC example" after the "Your CV" heading. The tag is removed on the first `input` event in any of the three boxes.
- **Existing text:** if any box already holds text, an inline `div.inline-confirm[role=group]` shows "Replace what you typed with the sample?" with `button.btn` "Replace" and `button.btn.quiet` "Keep mine".
- **Guests** keep "Try a sample student".

**Walk check:**

- **`s49_load_sample`:** on the mocked signed-in student start, with a `/me/docs` stub returning `[]`, pressing Load sample fills `#cv-text` with text containing "SYNTHETIC" and "Canary:". The tag "SYNTHETIC example" shows. Old code has no button, so it fails.

#### BE-S Tier B

- **U49:** in `studentProfile`, code-written values start with a capital letter. Record text is never changed.

**BE-S Tier A total: about 125 minutes**, plus 10 for V6 if route T ships.

### 3.6 Merge order and the run-through

1. **Step 0** (orchestrator).
2. **Merge BE-S first.** The others rely on its routes and fields.
3. **Merge FE-A next.** It owns the routes and the base styles.
4. **Merge FE-B last.**
5. **After the merge:**
   - The orchestrator updates the two old checks in `ux_walk.py`: `CHECKED_FLAGGED`, and `landing`'s signed-in assumption.
   - Then QA runs the full walk at 1280 and 360, in light and dark.
   - QA opens every changed screenshot.

## 4. Help page (`web/help.js`, FE-B)

Every sentence below is true of the code after round 1. FE-B checks each one against the merged code before it closes B10.

- **Keep from the lists:** "On Temple awards and Research funding, Keep saves a record to your account. Kept and saved records collect on My Perch with their dates. Sample records cannot be kept."
- **Sort and closed calls:** "Sort a list A to Z, by the soonest date or by the largest amount. Records that state no date or amount come last. Research funding hides calls whose close date has passed; turn on Show closed calls to see them."
- **A past date on an award:** "Many Temple awards recur each year. When an award’s page shows a date that has passed, the card says Past date on the page, and a check of your fit says may be eligible, with the date from the page. Check the page for this year’s date."
- **My Perch as home:** "When you are signed in, Perch opens on My Perch: what you kept and saved, sorted by date, your briefs, and your documents. Start a new search from there."
- **Change details and run again:** "Change details and run again opens the start screen with your details filled in. Running it makes a new brief; the old one stays on My Perch."
- **The researcher CV:** "A researcher may add a CV before building a brief. It is optional. Perch uses it for cover-letter points and Scout, stores it encrypted, and blanks contact details before a model reads it."
- **Temple internal** (only if A9 ships): "A researcher brief may show a third list, Temple internal: Temple’s own funding calls for faculty. They are kept apart from federal grants. Each call’s page says whom to contact."
- **The lead card** (update the anatomy figure and its callouts): "The title comes first, then the agency and code. Closes and Amount are always shown; Not stated means the record leaves it blank. The page says means the date is in the page’s words, not a date field."
- **Model text:** "Model text marks a model’s sentence, checked against the records it cites. When a sentence fails that check twice, the card says so in one line and keeps only the fields copied from the record."
- **Cover-letter points:** keep `COVER_HELP`. Add: "When today’s allowance is used, one note above the list says so, with the time it comes back."
- **Scout:** keep the line that Scout can read your saved list. It is now true.
- **Sample data:** keep the existing sample-data paragraph. Add "Sample records cannot be kept or saved."
