# Private mode

[Back to the README](../README.md)

## Turning it on

Private mode tailors a brief to a CV, a draft proposal, a research direction or unpublished work. It runs only on self-hosted models, and what a user adds stays in memory for the session (design and limits: `docs/design/PRIVATE_MODE.md`). It is off by default. To turn it on, set these in `.env`:

```
PERCH_PRIVATE_MODE=1
PERCH_PRIVATE_OPERATOR=<who runs this server, as users should read it>
PERCH_TLS_AT=server          # needed on a public URL; or tunnel:<provider>
PERCH_PRIVATE_ENDPOINTS=     # model hosts a session may call; default loopback
```

Every chat model must be an Ollama or OpenAI-compatible server on an allowed host, or a session will not open. Keep `OLLAMA_DEBUG` unset and do not pass `-v` to llama.cpp. To check that a session leaves no trace on the real store and models, run the live canary:

```
PERCH_PRIVATE_MODE=1 PERCH_TLS_AT=server PERCH_PRIVATE_OPERATOR="..." \
  uv run python scripts/private_canary.py
```

## Using it

1. On the Find screen, open **Options** and choose **Private mode: add a CV, a draft proposal or unpublished work**.
2. Start a private session. The page shows the privacy statement, which names who runs the server.
3. Paste or upload any of four documents: plain text, Markdown, Word (.docx) or PDF.
   - **Your CV:** checks career-stage rules and past sponsors only. It does not steer the search.
   - **Draft proposal:** the strongest steer, 0.5 of the private weight.
   - **Research direction:** 0.3 of it.
   - **Unpublished work:** 0.2 of it.
4. Add your OpenAlex ID if you want your public papers to count too. Your documents then take 60% of the weight and your papers 40%. Without an ID, the brief runs on your documents alone.
5. Build the brief. Explanations may cite your documents, and each such citation shows a lock.
6. Exports and hand-off drafts leave out text drawn from your documents. You can choose to mask it instead: names, contact details, identifiers and phrases found only in your documents become labels such as `[PERSON-1]`, and you can unmask them on screen. Masking cannot hide what your research is about.
7. End the session when you are done. It also ends after 30 minutes idle, or when the server restarts.

## What it promises, and how that is checked

- **Held in memory only:** nothing from a session reaches the database, the caches, the logs or the search index.
- **Checked by a canary test:** each test document carries a unique token. After a full session, no token may appear in any file, log, temporary file, browser storage or outbound request (`tests/test_private.py`, and `scripts/private_canary.py` on the real models).
- **The full design:** the write-path inventory, the masking rules and the limits are in [design/PRIVATE_MODE.md](design/PRIVATE_MODE.md).
