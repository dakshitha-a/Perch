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
