# Private by default, Local or Cloud

[Back to the README](../README.md)

Perch has no user accounts, so since S23 it keeps nothing about the people who use it. Every brief runs in a session held in the server's memory. Models run on the server unless a user turns Cloud on. Your own documents (a CV, a draft proposal, unpublished work) are read only by local models. Design and limits: `docs/design/PRIVATE_MODE.md`.

## What is stored, and what is not

- **Not stored:** briefs, leads, keep and dismiss choices, hand-off drafts, Scout conversations, anything you type or add, and any log of your session. Running the same researcher again builds a fresh brief; nothing is reused. The browser keeps no history of briefs; only the theme choice is remembered.
- **Stored:** public records Perch fetches for a brief (OpenAlex researchers and works, NIH RePORTER and NSF awards, the companies behind industry leads) are written to the store, so the next brief is faster. They hold nothing about the person who asked. Grants.gov opportunities and the search index are built ahead of time, as before. `PERCH_PUBLIC_CACHE=0` turns the public cache off too.
- **Warm demo briefs (S24):** with `PERCH_WARM_AUTHORS` set, the server builds each listed researcher's default brief when it starts and holds it in memory, never on disk. A visitor who asks for that brief with nothing added gets a copy in their own session at once, with their own keep and dismiss state. The progress card says it was built when the server started. A warm brief is rebuilt when the day changes.
- **Ends:** with End session at the top of any screen, after 30 minutes idle, or when the server restarts.
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
PERCH_CLOUD_DOCUMENTS=       # "1": documents may go to Cloud after a second warning (off; see below)
PERCH_WARM_AUTHORS=          # OpenAlex ids whose default briefs are built at start, in memory
```

Every local chat model must be an Ollama or OpenAI-compatible server on an allowed host, or a session will not open. Keep `OLLAMA_DEBUG` unset and do not pass `-v` to llama.cpp. `PERCH_PRIVATE_MODE=0` turns sessions off, and the web app then has no briefs.

## Local or Cloud

- **Local is the default.** Every model runs on the Perch server.
- **Cloud is a choice.** Where `PERCH_CLOUD` is set, the chip at the top opens a dialog that offers it. Before it turns on, a warning names the company and says what is sent: what you type (the researcher and any direction or keywords) and the text of the public papers and listings in your brief. The user confirms first; the API checks that the confirm names the provider.
- **What Cloud changes:** only the three model skills, the profile summary, the fit explanations and the hand-off opening, use the cloud model. Search, ranking, the citation checks and Scout stay local.
- **Documents never go to the cloud.** Cloud cannot turn on while a session holds documents, documents cannot be added while Cloud is on, and student mode turns Cloud off. This keeps the challenge rule that private text is used only on local models. A real deployment could choose otherwise, for example with a zero-data-retention cloud key. S24 built that path behind `PERCH_CLOUD_DOCUMENTS=1`: a second, stronger warning about the documents, a box to tick, and a second confirm the API checks ("send my documents to <provider>"). It stays off until the standing rule changes (Q33); tests use SYNTHETIC text only.
- **Spend:** the Anthropic adapter's $100 cap still applies, and the server allows `PERCH_CLOUD_BRIEFS_PER_DAY` cloud briefs a day. The adapter's spend ledger records tokens and cost per call, with no text.

## Using your documents

1. Under **I'm a researcher**, follow **Add a CV or unpublished work (optional, Local only)**. If you paste a CV or long text into a box on Find, Perch offers to add it as a document; nothing is sent until you choose.
2. The session opens on arrival. The page shows the privacy statement, which names who runs the server.
3. Paste or upload any of four documents: plain text, Markdown, Word (.docx) or PDF.
   - **Your CV:** checks career-stage rules and past sponsors only. It does not steer the search.
   - **Draft proposal:** the strongest steer, 0.5 of the private weight.
   - **Research direction:** 0.3 of it.
   - **Unpublished work:** 0.2 of it.
4. Add your OpenAlex ID if you want your public papers to count too. Your documents then take 60% of the weight and your papers 40%. Without an ID, the brief runs on your documents alone.
5. Build the brief. Explanations may cite your documents, and each such citation shows a lock.
6. Exports and hand-off drafts leave out text drawn from your documents. While the session holds documents, every model-written text counts as drawn from them, because the models read them: exports leave out the summary and the explanations with a stated count, and the hand-off opens with a plain sentence (S8). You can choose to mask it instead: names, contact details, identifiers and phrases found only in your documents become labels such as `[PERSON-1]`, and you can unmask them on screen. Masking cannot hide what your research is about.

## How it is checked

- **Canary tests:** each SYNTHETIC test document carries a unique token. After a full session, no token may appear in any file, log, temporary file or outbound request off the allowlist, and the store gains no brief or lead row (`tests/test_private.py`, with the public cache on and off).
- **Live canary:** `scripts/private_canary.py` runs on the real store and models: a visitor's brief with no documents, the Cloud refusal check, and two briefs with the persona-1 documents.

```
PERCH_TLS_AT=server PERCH_PRIVATE_OPERATOR="..." PERCH_CLOUD=anthropic:claude-sonnet-5-5 \
  uv run python scripts/private_canary.py
```

## Student mode

Choose **I'm a student** on the Find screen. Student mode always runs on local models. Add your CV, an interests note and up to five achievements. Code reads the CV by rule (level, year, major, GPA, enrolment, expected graduation, referees); no model reads it. Routes has **Fellowships (public)**, from Temple Scholar Development and Fellowships Advising's list and NIH F-series listings, and **Scholarships and awards (sample)**, from an invented test corpus badged Sample data on every card. Each lead says "eligible", "may be eligible" or "not eligible" by rule, and lists what is still needed. Compare drafts a note to SDFA or Student Financial Services; Perch sends nothing. Exports carry a sample banner and withhold lines that quote the CV, and the model's explanations, unless masked. Scores on planted cases: `bench/results/STUDENT_MODE.md`.

## Monitoring is shelved

The weekly watch (S16) needs to know whom to watch, and Perch now keeps nothing about its users. Its code is in `perch/shelved/monitor/`, with a README on how to reconnect it once a user system exists.
