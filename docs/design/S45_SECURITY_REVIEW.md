# S45 security review: Scout v2 prompt injection and scope gate

Fresh-context Opus review, read-only, 2026-11-04. Judged the code on rebuild/v1 after the grounding fixes (40bda68).

## Must-fix
- **M1. CSRF missing on Scout and other write routes.** `POST /briefs/{id}/scout`, `POST /scout/{sid}/{action}`, `DELETE /scout/{sid}`, `/cover-points`, `POST /briefs` and `/handoff` use `account_session`, not `account_session_csrf`. Fix: switch them; test that a POST without the token gets 403.

## Should-fix
- **S1. Budget can suppress distress.** The gate charges the budget first, so a user out of budget who writes a crisis message gets the budget text. A model decline shows the plain refusal with no support links. Fix: a free keyword check for crisis words before the quota and gate; a decline with those words shows DISTRESS.
- **S2. Refused questions reach the model through history.** `history_of` passes earlier refused questions. Fix: drop user messages answered with a refusal or distress, and those replies.
- **S3. Exempt sentences skip content checks.** Headings, questions and "nothing found" sentences skip the award-name and eligibility checks; `ABSENT_RE` is broad. Fix: run `general_reasons` on them, tighten `ABSENT_RE` to short sentences, add "qualify", "eligible for", "meet the requirements" to the eligibility words.
- **S4. Placeholder ids count as support; flags hidden in the UI.** `[user:saved]` can back any claim. web/scout.js never shows unsupported, flagged, withheld or the General advice part. Fix: placeholder ids cannot support a claim; the UI shows them.
- **S5. Contact blanking misses formats.** `www.` and bare-domain links, phones without separators, international phones; entry labels and document titles go out raw. Fix: broaden patterns, blank `label` and `title`.
- **S6. No cap on tool calls per step.** One step can call `read_record` many times at 12,000 characters each; attempt 2 reuses attempt 1's messages. Fix: cap tool calls per step and tool-result characters per turn; trim attempt 2.
- **S7. Help text wrong.** web/scout.js says "eight model calls" and that the CV is read only for cover points.

## Nice-to-have
- **N1.** Audit prompt hashes are unsalted SHA-256; use an HMAC with a server secret.
- **N2.** Layer 1 pools numbers across cited sources; check amounts and deadlines against public records only.
- **N3.** Abbreviation merging joins a sentence ending in a single capital or "No." to the next.
- **N4.** `URL_RE` misses bare domains and emails; record text is not contact-blanked (rendering is textContent, so low risk).
- **N5.** Buttons have no rate limit; a race between the busy check and the append can queue two jobs.
- **N6.** `scout_turn` max_attempts=2 can charge a crashed turn twice.

## Clean
Tool allowlist, cross-user access, logging, rendering (textContent, no XSS) and the fail-open gate design.

## Re-check after the fixes (fresh-context Opus, 2026-11-04)

- **Fixed:** M1 (all nine write routes check CSRF), S6 (caps; the real ceiling is about 52,000 characters), S7 (Help), and the S4 UI.
- **Partly fixed:**
  - **S1:** the crisis list misses "I wish I were dead", "suicidal thoughts", "thinking about suicide", "end it all", "no reason to live", "can't go on" and "dont wanna live". With the budget spent mid-job these get the budget text.
  - **S2:** a question answered with the budget text, or cancelled before the gate, stays in history unscreened.
  - **S3 and S4:** headings, questions and placeholder-cited "nothing" sentences can still carry eligibility or fit claims ("**Undergraduates may apply:**", "Nothing in your saved list requires citizenship [user:saved]"). A bare "eligible", "require", "may apply", "open to" and "fit" are not caught.
  - **S5:** some phone shapes, short-domain links and "at ... dot edu" still reach the model; a 10-digit grant number is blanked.
- **New must-fix:**
  - **R1:** the withheld text says "The records Scout read are listed below the answer", but nothing is listed (rule 10).
  - **R2:** the S3 and S4 gaps above.
  - **R3:** the S2 gap above.
- **Should-fix:**
  - The notice says "They are listed here" when only some are listed.
  - Attempt 2 puts tool data in a user message, which makes injected record text easier to obey.
  - Help's "start a new one" conflicts with the daily budget.
  - The free distress path has no rate limit.

## Re-checks 3 and 4 and the close (2026-11-04)

- **Round 3 (Opus)** replaced the word lists with shapes and made distress screening independent of the budget. **Re-check 4** found the shapes held for headings, "nothing found" and placeholder sentences, and the free gate cap had no bypass.
- **Must-fix from re-check 4, fixed by the orchestrator:** offers, how-to lead-ins and help lines could carry a reason or verdict after the allowed opening ("…, since you rank first on both?"); now removed (`help_with_claim`, and the tail rule on questions and lead-ins). Scout's waiting line claimed an amount filter, and Help offered cover-letter points that no screen requests; both removed.
- **Left for S46 (should-fix):**
  - Crisis regex: the research-noun guard also blocks "My grant got rejected and I want to die"; such messages still reach the gate, free when the budget is spent. "I'm planning to end it after the pilot" matches. A rate-limited crisis message gets a plain 429 without a screen. Ordinary out-of-budget questions use up the 10 free screens.
  - Contacts: "@janedoe_lab", "jdoe@temple", spaced or spelled-out digits still reach the model; "NSF 2215204123" is over-blanked; "due at grants.gov" loses "due".
  - Help says Scout "cites each claim"; reworded to exclude General advice, check again in S46.
  - The cover-points route has no button in the UI.
  - Stricter shapes withhold more: on the stored s45f drafts, clean drafts fell from 16 to 10. Templates for common process sentences ("I did not read <CV part>") would recover some.
