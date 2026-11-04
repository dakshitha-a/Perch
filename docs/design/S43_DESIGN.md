# S43 design — student-first UI on the v1 stack

Design pass for Phase 7 of `docs/REBUILD_PLAN.md`. This document proposes; it builds nothing. The visual language stays the S24 one in `docs/design/S24_REBUILD.md`: same tokens, type, shapes, sizes and motion. Only screens, states and copy change.

Gate: Thursday 5 Nov 2026, 18:00. Each item below is marked **[gate]** or **[later]**.

The gate means three things work live:

- **Guest or sign-in:** a visitor can sign in, or start a guest session, or just browse.
- **Temple awards:** the awards list shows Temple awards with the Temple-only toggle and the school tags.
- **A brief on the cloud model:** a researcher brief from an OpenAlex id builds on the cloud profile. A student brief from a stored CV is also gate if S42 lands its account route by Thursday morning. If S42 slips, the researcher brief alone meets the gate.

---

## 0. What the current code does that blocks this design

Read this section first. Each item is a backend change the UI cannot work around.

- **Temple-only filters on the wrong field.** `perch/store/postgres.py` adds `temple_funded` to the WHERE clause when `temple_only` is set. In `temple_awards_v1.jsonl`, `temple_funded` is true for 4 of 285 records. A toggle built on this shows 4 awards. Fork F1 decides the fix.
- **Unstated scope turns into "external".** `perch/store/denorm.py` maps a missing scope to `external`. The manifest counts 30 scholarships with scope unstated. They are listed on Temple pages, but today they would drop out of every Temple filter. Denorm must keep Temple-page records inside Temple, whatever their scope. Fork F2 decides how they are labelled.
- **School tags are cleared when scope is not "school".** `denorm.columns` empties `schools` unless scope is `school`. So tag counts from the database will be lower than the manifest's `by_school` numbers. The UI must render counts from `GET /filters` only, never from the manifest.
- **Browse routes do not exist yet.** `GET /awards`, `GET /opportunities`, `GET /filters` and `GET /samples` are in the contract, section 9.2, but no route serves them. The store's `browse` method exists, so each route is a thin wrapper.
- **Account routes the design needs do not exist yet.** `GET /me/saved`, `PUT /me/saved/{record_id}`, `DELETE /me/saved/{record_id}`, `POST /briefs/{id}/cover-points` and `GET /briefs/{id}/handoff/{draft_id}` are missing. `GET /me` is missing too, so the account page has nothing to read.
- **The student brief has no account route yet.** `POST /briefs` still requires an OpenAlex `author_id`, and `request_models.py` has no `audience` field. The student brief moves onto the account path in S42, which is running in a worktree now. S43 builds against the S42 result.
- **Guest compare contradicts guest keep.** Section 7.4 says a guest can compare and export. Section 9.1 makes keep, dismiss and restore need a signed-in user. Compare works on kept leads, so a guest cannot compare. Fork F3 decides the fix.
- **`GET /usage` needs a user.** The contract says any session. This decides whether a guest sees a budget line. The design below shows no budget to guests, so this is not a gate blocker.
- **`/welcome` is a server-rendered placeholder page.** It is labelled PLACEHOLDER and tells the reader to POST by hand. S43 replaces it with an app screen at `#/welcome`. The server route should just redirect to `/#/welcome`.
- **Three strings on screen are now false under rule 10.**
  - The footer promise "Nothing about you is stored" is false, because signed-in users' CVs are stored encrypted.
  - The header chip "Local · nothing stored" is false, because the deployment runs on the cloud profile.
  - The meta description leads with researchers only.
  - Replacements are in section 1.5.
- **Private-mode code goes away.** `web/mode.js`, `web/private.js`, the Local or Cloud dialog, the "End session" button and every `privApi` and `PRIVATE_ID` branch in `web/app.js` are removed by S42. S43 must not rebuild any of them.

---

## 1. Landing

### 1.1 Layout [gate]

The landing keeps the owl, the headline and the 680 px column. What changes is the order: students come first.

```
laptop and phone, signed out
+--------------------------------------------------+
| Perch                    [Sign in] [Help] [Auto] |
+--------------------------------------------------+
|        (owl on the branch)                       |
|  Find funding that fits.                         |
|  Temple scholarships and research funding,       |
|  every claim linked to its record.               |
|                                                  |
|  [ Student | Researcher ]   <- Student chosen    |
|                                                  |
|  [ Browse Temple awards ]        <- primary      |
|  [ Check my fit with my CV ]     <- secondary    |
|  Try it as a guest. Nothing is saved.            |
+--------------------------------------------------+
| promises row                                     |
+--------------------------------------------------+
```

- **The control:** the existing Student | Researcher segmented control stays. Student is chosen by default.
- **The student side:** two buttons. "Browse Temple awards" opens the awards list and needs no session. "Check my fit with my CV" starts sign-in, or opens the student brief start screen if the user is signed in.
- **The researcher side:** the existing search field with Find, plus a quiet link "Browse funding" that opens the funding list.
- **The guest line:** under the buttons, one quiet line with a "Try it as a guest" link. It calls `POST /auth/guest` with the chosen audience.
- **The memory:** a signed-in user lands on the side in `last_audience`. A signed-out visitor always lands on Student.

### 1.2 States [gate]

Every state is driven by `GET /auth/session`. No state is guessed on the client.

| State | Session fields | Header right side | Landing shows |
|---|---|---|---|
| Signed out | `signed_in: false`, no `guest` | Sign in, Help, theme | Both buttons, the guest line |
| Guest | `guest: true`, `expires_at` | "Guest" chip, Sign in, Help, theme | The guest banner, both buttons; "Check my fit" reads "Try a sample student" |
| Signed in, new | `needs_welcome: true` | Account chip | Redirects to `#/welcome` |
| Signed in | `signed_in: true`, `needs_welcome: false` | Account chip, Help, theme | Both buttons; "Check my fit" goes to the start screen |
| Consent raised | `consent.required: true` | Account chip | Redirects to `#/welcome`, consent step only |

### 1.3 The guest banner [gate]

- **Where:** in the existing `#banner` slot under the header, on every screen of a guest session.
- **Text:** the string the server already sends in `notice`: "Nothing is saved in a guest session. It ends in an hour."
- **Action:** a "Sign in" link at the end of the banner, which goes to `/auth/login?return_to=` the current hash.
- **Style:** the chip colour background with ink text and an info icon. It is not amber, because amber means sample data.
- **Exports:** a guest export carries the same text at the top, as the contract says.
- **Expiry:** when a call returns 401 in a guest session, the app shows "Your guest session has ended. Nothing was saved." with Start again and Sign in buttons.

### 1.4 The account chip [gate]

- **What replaces the Local chip:** a button with the user's `display_name`, or "Account" if there is none.
- **What it opens:** a small menu with "My Perch", "Account and data", the side switch when the user holds both roles, and "Sign out".
- **Sign out:** calls `POST /auth/logout`, then follows the IdP end-session URL if one comes back.

### 1.5 Copy replacements [gate]

- **Footer promise 1 stays:** "Every claim cites a public record."
- **Footer promise 2, replacing "Nothing about you is stored":** "Your CV is stored encrypted. You can delete it at any time." DRAFT for Dakshitha.
- **Footer promise 3 stays:** "Hand-offs are drafts; nothing is sent."
- **Meta description:** "Perch lists Temple scholarships and research funding that fit you, every claim linked to its record." DRAFT for Dakshitha.
- **Headline sub-line:** "Temple scholarships and research funding, every claim linked to its record." DRAFT for Dakshitha.

---

## 2. Sign-in, welcome and the account page

### 2.1 Sign-in [gate]

- **No sign-in screen of our own:** "Sign in" is a plain link to `/auth/login?return_to=<current hash>`. The IdP shows its own page.
- **The return:** the callback lands on `return_to`. If `needs_welcome` is true, the app goes to `#/welcome` first and then back.
- **Errors:** a failed login returns to the landing with "Sign-in did not finish. Try again." in the banner slot.

### 2.2 The welcome screen, `#/welcome` [gate]

It has two steps on one page. Both must be done before the user continues.

```
+----------------------------------------------+
| Welcome to Perch                             |
|                                              |
| 1. What brings you here?                     |
|  [x] I am a student      <- 56 px rows       |
|  [ ] I am a researcher                       |
|  You can pick both. You can change this      |
|  later on the account page.                  |
|                                              |
| 2. How Perch uses your CV                    |
|  (consent text, version N)                   |
|  [ ] I agree                                 |
|                                              |
|  [ Continue ]                                |
+----------------------------------------------+
```

- **Step 1, the side:** two checkbox rows, Student and Researcher. At least one must be ticked. This calls `POST /me/roles`.
- **Researcher extra:** if Researcher is ticked, an optional field "Your OpenAlex author id" appears, with a Find link that reuses the researcher search. This calls `PUT /me/openalex`. It can be skipped.
- **Step 2, consent:** the full text from `perch/auth/consent.py`, shown as written, with its version number. An "I agree" checkbox. This calls `POST /me/consent` with the version.
- **Continue:** disabled until both steps are done. It goes to `return_to`, or to the side's home.
- **The baseline consent text is the contract text.** It names the provider from `PERCH_CONSENT_PROVIDER_NAME`. It states the blanking of contact details, encrypted storage, delete-my-data, the 12-month rule, backups clearing within 35 days, and withdrawal.
- **A proposed plainer version, DRAFT for Dakshitha:**
  - "Perch sends the text of your CV and entries to {provider}, so it can write your briefs, hand-off drafts and cover points."
  - "Before any text is sent, Perch blanks emails, phone numbers and links."
  - "Your CV and entries are stored encrypted, under a key that belongs to you."
  - "You can delete all your data at any time, on the account page."
  - "If you do not use Perch for 12 months, your data is deleted."
  - "After you delete your data, backups clear within 35 days."
  - "You can withdraw this consent at any time. That stops these model jobs. It does not delete your data."
- **A changed text needs a new version.** The `consents` row stores the hash of the exact text. If Dakshitha takes the plainer version, `PERCH_CONSENT_VERSION` must rise, and every existing user sees the consent step again.
- **No Temple policy is stated.** The text says nothing about Temple's own data rules, because the code does not know them.

### 2.3 The account page, `#/account` [gate for delete, later for the rest]

```
+----------------------------------------------+
| Account and data                             |
|                                              |
| Signed in as  <display name>                 |
| Your sides    [x] Student  [x] Researcher    |
| OpenAlex id   A50... [Change]                |
| Consent       Version N, agreed. [Withdraw]  |
|                                              |
| Your documents                               |
|   CV (label)                    [Remove]     |
|                                              |
| Delete my data                               |
|   (what is deleted, the 12-month rule)       |
|   [ Delete my data... ]   <- danger button   |
+----------------------------------------------+
```

- **Sides:** the same two checkboxes as the welcome screen, calling `POST /me/roles`. [later]
- **OpenAlex id:** shown only to researchers. Change reuses the welcome field. [later]
- **Consent:** shows the version agreed. Withdraw calls `POST /me/consent/withdraw` after a confirm that says it stops the model jobs and does not delete data. [later]
- **Documents:** the labels from `GET /me/docs`, each with Remove. [gate, because the student brief needs a stored CV]
- **Delete my data:** a danger button that opens a dialog. [gate]

### 2.4 The delete dialog [gate]

- **What it says is deleted:** "Your CV and entries, your briefs, your saved awards and leads, your hand-off drafts and cover points, and your account. Your key is destroyed, so nothing stored under it can be read again."
- **What it says about backups:** "Backups clear within 35 days."
- **What it says about the 12-month rule:** "Even if you do nothing, Perch deletes your data after 12 months without use."
- **The confirm step:** a text field labelled "Type delete to confirm". The Delete button stays disabled until the field holds exactly `delete`. The body sent is `{"confirm": "delete"}`.
- **After:** the server returns 202 and ends the session. The app shows the landing with "Your data was deleted." in the banner slot.
- **Keyboard:** the dialog is a real `<dialog>`. Focus starts on the text field. Escape cancels. Focus returns to the danger button on cancel.

---

## 3. The awards list and the funding list

### 3.1 One list component, two screens [gate]

- **Students:** `#/awards`, served by `GET /awards`. Kind is `scholarship`.
- **Researchers:** `#/funding`, served by `GET /opportunities`. Kind is `opportunity`.
- **Shared:** both use one list module with the same filter bar, card and paging. Only the record fields on the card differ.

### 3.2 The filter bar [gate]

```
laptop
+--------------------------------------------------------------+
| Temple awards                                    (n) awards  |
| [ Temple only (on) ]   [search box.........]  [Level v]      |
| [All] [All Temple] [CST 26] [Liberal Arts 23] [TFMA 21] ...> |
+--------------------------------------------------------------+

phone at 360 px
+--------------------------------+
| Temple awards        (n)       |
| [ Temple only (on) ]           |
| [search box..................] |
| [Level v]                      |
| [All][All Temple][CST 26] ...> |  <- the row scrolls inside itself
+--------------------------------+
```

- **Temple-only toggle:** a switch with the label "Temple only". It sets `temple_only`. Its meaning is fixed by fork F1.
- **School tags:** one chip per school from `GET /filters`, each with its count. The order is by count, highest first.
- **The "All" chip:** clears the school filter.
- **The "All Temple" chip:** shows Temple records with no school on them. Fork F2 decides its exact content.
- **Tag labels:** what the `schools` field holds, such as "CST" or "Fox School of Business". Fork F4 decides whether short names are expanded.
- **One school at a time:** the tags act as a single choice, like radio buttons. Fork F5 decides whether a school's view also shows university-wide awards.
- **A record with several schools:** six records name two to four schools. Such a record appears under each of its tags.
- **Level filter:** a select with "Any level", "Undergraduate", "Graduate", "Faculty", and "Several levels" for `mixed`. Records with no level appear only under "Any level".
- **The tag row on a phone:** one line that scrolls sideways inside itself, with a fade at the right edge. The page itself never scrolls sideways.
- **The researcher side:** the toggle defaults to off, because most research funding is external. The tags apply only when the toggle is on.
- **The student side:** the toggle defaults to on. The contract's `FilterView` holds only schools and levels, so it cannot tell the page whether any scholarship is outside Temple.
- **Decided for the gate:** `GET /filters` also returns `total` and `temple_total`. If they are equal, the student toggle is hidden and the page title reads "Temple awards". This is a small addition to the contract, listed in section 10.

### 3.3 The award card [gate]

Field coverage drives the card. Out of 285 records, 48 state a maximum amount, 15 state a deadline and 130 state an apply link. "Not stated" is the usual case, so the card must not look broken without them.

```
+------------------------------------------------+
| [CST]  Undergraduate  ·  Open to one school    |
| [Award name from the record]  (serif)     |
| "...awarded to full-time undergraduate         |
|  students majoring in..."   <- quoted sentence  |
| Amount: not stated · Deadline: not stated       |
| [Save]  [Evidence]  [Open at source ->]         |
+------------------------------------------------+
```

- **Top line:** school tags, the audience level, and the scope line.
- **The scope line:** "Open to one school" for scope `school`. "Open across Temple" for scope `temple_wide`. "Scope not stated on the page" for unstated.
- **Title:** the record's `name`, in Newsreader, as a button that opens the evidence sheet.
- **The quote:** the first eligibility sentence from `field_quotes`, in quotation marks. It is copied, never written by a model.
- **Facts:** amount and deadline are rendered by `format.js` from the record fields. A missing value reads "not stated".
- **Temple-funded badge:** shown only when `temple_funded` is true. It reads "Temple-funded".
- **Actions:** Save for a signed-in user, Evidence, and "Open at source", which links to `source_url`.
- **Save for a guest or a signed-out visitor:** the button reads "Sign in to save" and links to sign-in.
- **Sort:** the default order is by name. A "Closes soonest" sort is offered, and records with no deadline go last under it.
- **The funding card:** the same shape, with agency, close date and award ceiling from the opportunity fields.

### 3.4 Sample records [gate]

- **Own list, never mixed:** sample records come only from `GET /samples`. They never appear in `/awards` or `/opportunities`.
- **Where:** a separate screen, `#/samples/student` or `#/samples/researcher`, linked from the foot of each list by "See how Perch works with sample records".
- **Badges:** every sample card keeps the S24 dashed amber border and the dashed "Sample data" badge.
- **Banner:** the sample screen opens with the existing sample note: "These are invented records from a test corpus. ... Do not apply to them."
- **Evidence:** the sheet for a sample record states "Source: synthetic".
- **No counts:** sample records never count toward any number on the awards or funding page.

### 3.5 Empty, error and loading states [gate]

- **Loading:** three shimmer cards.
- **No match:** "No awards match these filters." with a "Clear filters" button.
- **Error:** "Perch could not load the list. Try again." with a Retry button.
- **End of list:** a "Show more" button that follows the `cursor`. It is a button, not infinite scroll, so the keyboard and the footer stay reachable.

---

## 4. My Perch: saved items, past briefs and drafts

### 4.1 Layout [later, except past briefs]

```
+----------------------------------------------+
| My Perch                  [Student|Researcher]|
| [Saved (n)] [Briefs (n)] [Drafts (n)]        |
|----------------------------------------------|
| list of cards for the chosen tab             |
+----------------------------------------------+
```

- **Where:** `#/me`, opened from the account chip.
- **The side control:** shown only when the user holds both roles. It sets the `audience` query on every call.
- **Saved:** cards from `GET /me/saved`, the same card as the list, with the user's note and Remove. [later]
- **Briefs:** rows from `GET /me/briefs`, each with the date built, the subject and an Open link. [gate, because the S41 done-when needs "return and see it"]
- **Drafts:** hand-off drafts, each with the office, the date and Open. [later]
- **Guest:** `#/me` is not offered. A guest who opens it sees "Sign in to keep briefs and saved awards."

---

## 5. Porting every researcher screen

The screens stay as S24 built them. These are the changes.

- **Find:** unchanged search and candidate cards. The "Tell Perch more" panel loses the "Local only" labels. A signed-in researcher can attach a stored CV from `GET /me/docs` with a checkbox. A guest sees the panel without the CV box, and a line "Sign in to add your CV". [gate]
- **Find, pre-filled:** a researcher with a linked OpenAlex id sees "Build my brief" as the first action on the researcher landing. [later]
- **The brief:** built through `POST /briefs` and polled through `GET /jobs/{id}` and `GET /briefs/{id}`, as S41 wired it. The progress card stays. A failed job shows the fixed message for its `error_code`: consent required, quota exceeded or budget exceeded. [gate]
- **Leads, the Routes tab:** unchanged cards. Keep and Dismiss work for a signed-in user. For a guest, they follow fork F3. [gate for signed-in]
- **Leads, Temple filter:** the Temple-only toggle and school tags inside the brief's Routes tab. [later]
- **Compare:** unchanged for a signed-in user. For a guest, it follows fork F3. [later]
- **Hand-off:** now a job. Draft shows the progress line until the job ends, then the stored draft. Guests see "Sign in to draft a hand-off". [later]
- **Export:** unchanged menu, minus the mask option, since masks are gone. A guest export carries the guest banner text. [gate for signed-in]
- **Scout:** port only so it does not break. The tab exists for signed-in users and calls the account-backed `POST /briefs/{id}/scout`. Guests see "Sign in to ask Scout". Phase 8, in S44 and S45, rebuilds Scout, so S43 spends no time on its design. [later]
- **Profile:** unchanged. [gate]
- **Removed:** the Local or Cloud dialog, the second Cloud warning, "End session", the private bar, the mask option and every "Local only" label.

### 5.1 The student brief [gate]

- **Start screen, `#/student`:** "Tell Perch about you." A signed-in student picks a stored CV or adds one with `POST /me/docs`, then adds interests and achievements. The button reads "Find awards that fit".
- **The privacy line on that screen, DRAFT for Dakshitha:** "Your CV is stored encrypted. Contact details are blanked before {provider} reads it."
- **The guest student:** the guest cannot upload a CV, by contract section 7.4. The start screen offers only "Try a sample student". This builds a brief for the SYNTHETIC persona, with the sample badge and banner.
- **The call to action for a guest:** "Sign in to use your own CV", shown on the sample brief.
- **The tabs:** "Your options", "What Perch read", "Compare" and "Ask Scout", as S24 built them.
- **Your options:** the real Temple scholarships and public fellowships come first, with verdict chips. Sample records do not appear in this tab. Fork F6 decides where they go.

---

## 6. Mobile at 360 px [gate]

- **Width:** every screen is checked at 360 px as well as 1280 px. The walk's phone size changes from 390 px to 360 px.
- **No sideways scroll:** the page never scrolls sideways. Only the tag row scrolls inside itself.
- **Header at 360 px:** the wordmark, the account chip or "Sign in", and Help. The theme button moves into the account menu for signed-in users. For a signed-out visitor it stays as an icon-only button with a label.
- **Account chip:** shows the first word of the name, cut with an ellipsis at 10 characters.
- **Tap targets:** every chip, toggle, checkbox row and button is at least 44 px tall. Primary buttons are 48 to 56 px.
- **Filter bar:** the toggle, the search and the level select stack, each at full width.
- **Cards:** the action row wraps. "Open at source" takes the full width when it wraps.
- **Dialogs:** the delete dialog takes the full width minus a 16 px gutter.
- **Focus order on the lists:** the toggle, then the search, then the level select, then the tag row from left to right, then the first card. Each card is title button, Save, Evidence, then Open at source.
- **Focus order on the welcome screen:** Student, Researcher, the OpenAlex field if shown, the consent text region, "I agree", then Continue.
- **Focus on a tag chip off screen:** focusing it scrolls it into view inside the row.
- **Focus after a filter change:** focus stays on the chip pressed, and the live region announces "n awards".

---

## 7. The walk

### 7.1 Flows to add [gate]

- **Guest:** landing, "Try it as a guest", the banner, the awards list, a sample student brief, and the expired-session state.
- **Sign-in:** the dev Keycloak login with a SYNTHETIC test user, the welcome screen, roles, consent, then the side's home.
- **Filters:** the toggle on and off, three school tags, "All Temple", the level select, Show more, and Clear filters on the empty state.
- **Delete:** the account page, the dialog, a wrong word that keeps Delete disabled, the right word, and the landing after.
- **Researcher brief, signed in:** the existing PI flow, now on the account path.
- **Student brief, signed in:** a SYNTHETIC CV stored, the brief built, then sign out, sign in and see it under My Perch.

### 7.2 New checks, each proven to fail first [gate]

Each check is run once against a planted fault and must fail, then run against the real build and must pass. Each plant is listed below.

| Check | Passes when | How it is made to fail first |
|---|---|---|
| Guest banner | Every guest state has the banner with the server's notice text | Render one guest state with the banner hidden |
| No sample in public lists | No card in `#/awards` or `#/funding` has a `sample:` id or the sample badge | Route `/awards` to return one sample record |
| Badge on every sample | Every card on `#/samples/*` carries the "Sample data" badge | Drop the badge on one card |
| Tag row at 360 px | The page has no sideways scroll, and every chip is at least 44 px tall | Give one chip a long label and a smaller height |
| Tag row contained | The tag row's scroll width is larger than its client width, and the page's is not | Remove `overflow-x: auto` from the row |
| Counts from the server | Each chip's count equals the count in `GET /filters` | Route `/filters` to return different counts than the chips show |
| Focus order on lists | Tab order is toggle, search, level, tags, first card | Swap the toggle and search in the DOM |
| Delete is keyboard-reachable | The dialog opens, takes focus, and Escape returns focus to the button | Open the dialog without moving focus |
| Delete guard | Delete stays disabled until the field holds `delete` | Enable the button on open |
| Old copy gone | The strings "Nothing about you is stored" and "Local · nothing stored" do not appear on any state | Restore the old footer on one state |
| No dead modules | No request for `mode.js` or `private.js` | Add the old import back |

### 7.3 Checklist changes

- **Item 11, "Private mode visible at a glance":** retired with private mode.
- **Item 7, the private switch half:** retired. The rest of item 7 stays.
- **Item 10, no sideways scroll:** now at 360 px and 1280 px.
- **Item 12, samples never unbadged:** now covered by two automatic checks above, not only by hand.
- **New item 14, guest banner:** every guest state.
- **New item 15, delete confirm:** keyboard-reachable and guarded.

---

## 8. Forks for Dakshitha

Each fork has the recommendation first.

### F1. What does "Temple only" mean?

- **Recommended, A: listed on a Temple page.** The filter keeps records whose source is `temple_pages`. That gives 285 records. It matches what a student expects.
- **B: Temple-funded, as stated on the page.** The filter keeps records with `temple_funded` true. That gives 4 records today. It is stricter, but the list is nearly empty.
- **Cost of A:** the `records` table already has a `source` column, so browse can filter on `source = 'temple_pages'`. That is a change to the `temple_only` WHERE clause in `postgres.py` and `sqlite.py`, plus a test, about 30 minutes. The "Temple-funded" badge stays as a separate fact on the card.
- **A cleaner version of A, if F2 is built first:** once unstated Temple records stop being stored as `external`, Temple only becomes `scope <> 'external'`. Then F1 and F2 are one fix.
- **The vector table differs:** `record_vectors` has `temple_funded` and `schools` but no `source` or `scope`. So the Temple filter inside a brief, which is a later item, needs one more column there.

### F2. Where do the 30 records with unstated scope go?

- **Recommended, A: under "All Temple", with the line "Scope not stated on the page".** They stay findable, and the card says honestly what is not known.
- **B: a separate "Scope not stated" chip.** It is more precise, but one more chip crowds the row on a phone.
- **C: hide them.** It is the cleanest list, but it loses 30 real awards.
- **Cost of A:** denorm must stop mapping unstated Temple records to `external`. That needs a new scope value or a flag column, and a migration, about 1 hour.

### F3. How does a guest keep and compare?

- **Recommended, A: allow keep and dismiss on a guest brief, stored in its Redis result.** The guest brief already lives under `guest_sid_hash` for one hour, so nothing new is stored.
- **B: keep only in the browser for the guest session.** It needs no backend change, but compare then runs on the client and diverges from `compare_rows`.
- **C: no compare for guests.** It is the cheapest, but the contract's can-do list would need editing.
- **Cost of A:** the three keep routes accept a guest session, checked through `guest_tx`, about 1 hour. Not needed for the gate.

### F4. How are short school names shown?

- **Recommended, A: show the stored name for the gate, and add a checked display-name map later.** Names such as CST, CEHD, LKSOM, STHM, TFMA and CPH stay as they are on Thursday.
- **B: expand them now from a map in `data/overrides/`.** Each full name must be checked against the school's own page, by rule 10. It reads better for a first-year student.
- **Cost of B:** about 45 minutes to build and check 15 names. Without the check, a wrong school name is an invented fact.

### F5. Does a school's view also show university-wide awards?

- **Recommended, A: yes, in two labelled groups.** A Fox student sees "Fox School of Business (16)" first, then "Open across Temple (n)" below.
- **B: no, a school chip shows that school only.** It is simpler, but a student who picks their school misses most of what they can apply for.
- **Cost of A:** two calls per view, or one call with a flag, plus a group heading. About 1 hour. B is the gate fallback if time runs out.

### F6. Where do sample records live for students?

- **Recommended, A: their own screen, linked from the foot of each list and from the brief.** Rule 11 is then met by layout, not only by badges.
- **B: a third tab in the student brief, "Samples".** It keeps today's shape, but a sample tab next to real awards is easy to misread.
- **Cost of A:** one small screen that reuses the list component. About 30 minutes.

### F7. Must consent be given at sign-up, or only before a CV is added?

- **Recommended, A: at sign-up, as the backend does now.** Standing rule 1 says "one consent at sign-up", and `needs_welcome` already enforces it.
- **B: just in time, when a CV is first added.** Browsing and saving work without it. It is a gentler start, but it needs a rule 1 wording change from Dakshitha and a backend change.
- **Cost of A:** none. B costs about 1 hour plus the rule edit.

### F8. Where does a user with both roles switch sides?

- **Recommended, A: in the account menu, and as a control on My Perch.** It is one tap away and keeps the header small at 360 px.
- **B: a Student | Researcher control always in the header.** It is always visible, but it crowds the phone header.
- **Cost of A:** small, about 20 minutes, using `POST /me/audience`.

---

## 9. Routine choices, decided

- **Delete confirm:** the user types `delete`, because the backend requires that body.
- **Banner text:** the server's own `notice` string, so the UI and the API never disagree.
- **Banner colour:** neutral chip colour, so it is not confused with the amber sample style.
- **Sign-in page:** none of our own; the IdP's page is used.
- **Welcome as an app screen:** `#/welcome` in the single page app, with the server route redirecting to it.
- **Default sort on lists:** by name, because only 15 of 285 records state a deadline.
- **Paging:** a Show more button, not infinite scroll.
- **The quote on a card:** the first eligibility sentence from `field_quotes`, copied as is.
- **Counts:** always from `GET /filters`, never from the manifest.
- **Guest My Perch:** not offered; a sign-in prompt instead.
- **Theme button on a phone:** moves into the account menu for signed-in users.
- **Help:** each changed screen gets its Help section rewritten in S43, with each claim checked against the code. The rest of Help is rewritten later.

---

## 10. Must-have for the gate, in build order

1. **Backend, F1:** fix the `temple_only` filter.
2. **Backend, F2:** keep unstated Temple records inside Temple.
3. **Backend:** `GET /awards`, `GET /opportunities`, `GET /filters` and `GET /samples` as thin wrappers over `browse`. `GET /filters` also returns `total` and `temple_total`.
4. **Backend:** the `/welcome` server route redirects to `/#/welcome`.
5. **Header:** the account chip or Sign in; the Local chip and End session removed.
6. **Landing:** Student first, the two student buttons, the researcher search, and the guest line.
7. **Guest:** `POST /auth/guest`, the banner on every guest screen, and the expired state.
8. **Welcome screen:** roles, consent with the contract text, Continue.
9. **Awards list:** the toggle, the tags, "All Temple", the level select, the card, and the states.
10. **Funding list:** the same component on opportunities.
11. **Samples screen:** its own list, badged.
12. **Researcher brief:** on the account path, with Find, Profile, Routes, keep for signed-in users, and export.
13. **Student brief:** stored CV, built on the cloud model; the guest sample persona. This is gate only if S42 lands the account route by Thursday morning. If it does not, the researcher brief alone meets the gate.
14. **Account page:** documents and delete-my-data with the dialog.
15. **My Perch, Briefs tab only:** so a returning user sees past briefs.
16. **Copy:** the footer, the meta description and the sub-line.
17. **Walk:** the new flows and the checks in 7.2, each failing first.

### Later, after the gate

- Saved awards and leads.
- Hand-off drafts as jobs, and the Drafts tab.
- Cover points in the UI.
- Guest keep and compare, fork F3.
- School groups in a school view, fork F5, if B shipped for the gate.
- Expanded school names, fork F4.
- The Temple filter inside the brief's Routes tab.
- Scout's redesign, which belongs to Phase 8.
- Sides, OpenAlex link and consent withdrawal on the account page.
- The rest of the Help rewrite.
