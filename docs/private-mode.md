# Private by default, Local or Cloud

> **Retired in S42.** Private mode does not exist on `rebuild/v1`: there are no in-memory sessions, masks or Local or Cloud choice. A signed-in user's CV and entries are stored encrypted under that user's key and read by the user's own briefs (`docs/ARCHITECTURE_V1.md`). This page describes the fallback build at the tag `v0.1-demo-fallback`.

[Back to the README](../README.md)

Perch has no user accounts, so since S23 it keeps nothing about the people who use it. Every brief runs in a session held in the server's memory. Models run on the server unless a user turns Cloud on. Your own documents (a CV, a draft proposal, unpublished work) stay on local models unless you choose Cloud and confirm which documents leave. Design and limits: `docs/design/PRIVATE_MODE.md`.

## What is stored, and what is not

- **Not stored:** briefs, leads, keep and dismiss choices, hand-off drafts, Scout conversations, anything you type or add, and any log of your session. Running the same researcher again builds a fresh brief; nothing is reused. The browser keeps no history of briefs; only the theme choice is remembered.
- **Stored:** public records Perch fetches for a brief (OpenAlex researchers and works, NIH RePORTER and NSF awards, the companies behind industry leads) are written to the store, so the next brief is faster. They hold nothing about the person who asked. Grants.gov opportunities and the search index are built ahead of time, as before. `PERCH_PUBLIC_CACHE=0` turns the public cache off too.
- **Warm demo briefs (S24):** with `PERCH_WARM_AUTHORS` set, the server builds each listed researcher's default brief when it starts and holds it in memory, never on disk. A visitor who asks for that brief with nothing added gets a copy in their own session at once, with their own keep and dismiss state. The progress card says it was built when the server started. A warm brief is rebuilt when the day changes.
- **Ends:** with End session at the top of any screen, after 30 minutes idle, or when the server restarts.
- **One side at a time:** a session holds a researcher brief or a student brief, never both. Opening the other side's form, such as the student form while a researcher's brief is open, shows a warning that lists what the session holds. End session and start fresh discards it and opens the form empty; Keep goes back to the brief. The server refuses the other side's brief until the session ends.
- **Older stores:** stores from before S23 still hold the briefs visitors ran. `uv run python scripts/forget_briefs.py data/demo/perch.db` deletes every brief, lead and digest and compacts the file.
- **Operator tools still write:** `perch brief` on the command line, the bench and the back-test store their own briefs in the operator's store. They are run by whoever runs the server, not by visitors. The stored-brief API routes exist only with `PERCH_STORED_BRIEFS=1`, for development and replays.

## Settings

Sessions are on by default. Set these in `.env`:

```
PERCH_PRIVATE_OPERATOR=<who runs this server, as users should read it>   # needed on a public URL
PERCH_TLS_AT=server          # needed on a public URL; or tunnel:<provider>
PERCH_PRIVATE_ENDPOINTS=     # model hosts a session may call; default loopback
PERCH_CLOUD=                 # e.g. anthropic:claude-sonnet-5-5 to offer Cloud; empty is Local only
PERCH_CLOUD_BRIEFS_PER_DAY=30
PERCH_CLOUD_DOCUMENTS=       # "1": a user may send their documents to Cloud after a second warning (the demo sets it)
PERCH_WARM_AUTHORS=          # OpenAlex ids whose default briefs are built at start, in memory
```

Every local chat model must be an Ollama or OpenAI-compatible server on an allowed host, or a session will not open. Keep `OLLAMA_DEBUG` unset and do not pass `-v` to llama.cpp. `PERCH_PRIVATE_MODE=0` turns sessions off, and the web app then has no briefs.

## Local or Cloud

- **Local is the default.** Every model runs on the Perch server.
- **Cloud is a choice.** Where `PERCH_CLOUD` is set, the chip at the top opens a dialog that offers it. Before it turns on, a warning names the company and says what is sent: what you type (the researcher and any direction or keywords) and the text of the public papers and listings in your brief. The user confirms first; the API checks that the confirm names the provider.
- **What Cloud changes:** only the four model skills, the profile summary, the fit explanations, the hand-off opening and Scout's cover points, use the cloud model, and their text is tagged "Cloud: <provider>". Search, ranking, the citation checks and Scout's own model stay local; Scout's fit, draft and cover-points steps follow the session's choice and say so on their step.
- **Documents go to the cloud only by your choice.** Documents stay on local models unless you turn Cloud on and confirm a second warning (standing rule 1 as amended, Q33; `PERCH_CLOUD_DOCUMENTS=1`, set on the demo). The warning names the provider and lists each document in the session as you added it, such as "your CV (cv.pdf)" or "your draft proposal (pasted text)". It says that a CV carries contact details and career facts, that a draft proposal or unpublished manuscript is unpublished research, that the provider's API terms then apply and Perch stores nothing, and that the choice lasts for this session and can be turned off. The confirm is a plain button that stays off until you tick a box; nothing is sent before it. Student sessions get the same warning with the CV wording.
- **How consent is held:** the server records consent per document, by a hash of its kind and text, in the session's memory only. A cloud call passes the gate only while every document the session holds has consent, so a document added or replaced later turns Cloud off until you confirm it too; the same text added again keeps its consent. Turning Cloud off or ending the session clears it, and nothing more is sent. Without `PERCH_CLOUD_DOCUMENTS=1`, Cloud cannot turn on while a session holds documents. Tests use SYNTHETIC text only.
- **Spend:** the Anthropic adapter's $100 cap still applies, and the server allows `PERCH_CLOUD_BRIEFS_PER_DAY` cloud briefs a day. The adapter's spend ledger records tokens and cost per call, with no text.

## Using your documents

1. Under **I'm a researcher**, follow **Add a CV or unpublished work (optional, local by default)**. If you paste a CV or long text into a box on Find, Perch offers to add it as a document; nothing is sent until you choose.
2. The session opens on arrival. The page shows the privacy statement, which names who runs the server.
3. Paste or upload any of four documents: plain text, Markdown, Word (.docx) or PDF.
   - **Your CV:** code reads it for the career-stage rules and past sponsors. It does not steer the search. When you ask Scout what a cover letter for one lead could say, the cover-points skill reads the CV too, with contact details (emails, phone numbers, links, ORCID) blanked and the text capped at about 3,500 characters, preferring education, appointments and positions, funding, awards and skills. Without a CV the points come from your papers and public awards.
   - **Draft proposal:** the strongest steer, 0.5 of the private weight.
   - **Research direction:** 0.3 of it.
   - **Unpublished work:** 0.2 of it.
4. Add your OpenAlex ID if you want your public papers to count too. Your documents then take 60% of the weight and your papers 40%. Without an ID, the brief runs on your documents alone.
5. Build the brief. Explanations may cite your documents, and each such citation shows a lock.
6. Exports give the full brief. Markdown, print (PDF) and JSON carry the summary, topics, explanations, inferences and rule notes, and for a student the CV values in the verdict lines. Nothing is left out. An export that holds your documents says so: "This brief includes text drawn from your documents. The file stays on your computer after the session ends." The Export menu has its own optional box, **Mask my ongoing research**. It shows only when the session holds a draft proposal, a research direction or unpublished work, and it masks only phrases found in those documents, as `[PRIVATE-PHRASE-1]` and so on. It does not mask your CV, names or identifiers. You can unmask on screen. Masking cannot hide what your research is about.
   Hand-off drafts are different. They still leave out text drawn from your documents: the hand-off opens with a plain sentence instead. Their own box, **Mask private text in hand-offs**, masks names, contact details, identifiers and private phrases instead.
7. Ask Scout "What could my cover letter for the top lead say?" and the points show on the card with Copy, each cited to the record and to your CV, a document, a paper or an award. They never enter an export or a hand-off draft, and Perch sends nothing.

## How it is checked

- **Canary tests:** each SYNTHETIC test document carries a unique token. After a full session, no token may appear in any file, log, temporary file or outbound request off the allowlist, and the store gains no brief or lead row (`tests/test_private.py`, with the public cache on and off).
- **Live canary:** `scripts/private_canary.py` runs on the real store and models: a visitor's brief with no documents, the Cloud consent check (a document added with Cloud on turns Cloud off, with no cloud call), and two briefs with the persona-1 documents.

```
PERCH_TLS_AT=server PERCH_PRIVATE_OPERATOR="..." PERCH_CLOUD=anthropic:claude-sonnet-5-5 \
  uv run python scripts/private_canary.py
```

## Student mode

Choose **I'm a student** on the Find screen. Student mode runs on local models unless you choose Cloud and confirm the second warning, which names your CV. Add your CV, an interests note and up to five achievements. Code reads the CV by rule (level, year, major, GPA, enrolment, expected graduation, referees) for every verdict. One model step reads the CV text: when you ask Scout what your application for one fellowship or sample scholarship should highlight, the cover-points skill reads your CV, interests note and achievements, with contact details blanked, and returns points checked against that record and your own text; on a sample scholarship the card says the points are for an invented sample. It runs on local models unless you chose Cloud and confirmed the warning that names your CV. Routes has **Fellowships (public)**, from Temple Scholar Development and Fellowships Advising's list and NIH F-series listings, and **Scholarships and awards (sample)**, from an invented test corpus badged Sample data on every card. Each lead says "eligible", "may be eligible" or "not eligible" by rule, and lists what is still needed. Compare drafts a note to Scholar Development and Fellowships Advising or Student Financial Services; Perch sends nothing. Exports carry a sample banner and give the full brief, with the CV values in the verdict lines; cover points never enter an export or the note. Scores on planted cases: `bench/results/STUDENT_MODE.md`.

## Monitoring is shelved

The weekly watch (S16) needs to know whom to watch, and Perch now keeps nothing about its users. Its code is in `perch/shelved/monitor/`, with a README on how to reconnect it once a user system exists.
