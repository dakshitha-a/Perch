# Private mode — design

Asked for by Dakshitha on 2026-10-29 (S8). Extends SPEC §4. Built in S13, with
pieces in S9, S10, S12, S14 (MCP) and S16 (QA) (see PLAN.md). Synthetic test persona:
`data/synthetic/persona-1/`.

## What it is

- **Purpose:** a researcher can add sensitive material and get routes tailored to it. Examples are a current CV, an ongoing research summary, an unfinished grant proposal or an unpublished manuscript.
- **Measured, not asserted:** the promise counts as kept only when the canary test below passes (standing rule 9).

## Where it runs (trust boundary: the Perch server)

- **Self-hosted models:** private mode is served wherever every model runs on the deployer's own hardware. That can be the lab node, a laptop, or a university server. A public URL is allowed (Dakshitha, Q12, 2026-10-29).
- **Self-hosted endpoints only:** while a private session is open, the provider layer refuses any model endpoint that is not on the deployment's own allowlist (`PERCH_PRIVATE_ENDPOINTS`, default loopback). That covers the Anthropic adapter, remote OpenAI-compatible hosts and hosted Jev. The refusal is an error, not a fallback.
- **The secure connection:** many quick tunnels decrypt traffic at the provider's edge, which would expose private text to the tunnel provider. Verify this for the chosen tunnel in S9. On a public URL, private mode requires `PERCH_TLS_AT=server`, meaning the connection is decrypted on the Perch server. If the deployer sets `PERCH_TLS_AT=tunnel:<provider>`, the privacy statement names that provider.
- **Many users:** each private session is isolated. It has a random session token, memory and size caps, a 30-minute idle timeout, and a rate limit of its own.
- **The promise, in the UI:** "Private mode uses only models running on the Perch server, run by <operator>. What you add is held in memory for this session and is never saved, logged or sent elsewhere." The operator could still read server memory in principle, so the page names who runs the server.
- **No downloads mid-session:** model hubs run offline (`HF_HUB_OFFLINE=1`).

## Inputs

- **Normal mode has its own lighter fields (Q16), all optional:** a direction, include and exclude keywords, and a career stage. They use the same thread mechanism, but they are saved with the brief and may reach a hosted model. A CV is accepted only in private mode, because CVs carry contact details.

- **Ways in:** text pasted, or a file uploaded. Files are parsed from memory as text, Markdown, DOCX or PDF, with no temp files. Each input has a size limit.
- **Kinds:** a CV, a direction (a few sentences), a draft proposal (aims or a summary), and unpublished work (an abstract or a manuscript).
- **Private-only brief:** a session can run with no OpenAlex id at all. Threads then come from the private documents alone. This serves new faculty with nothing published yet, which the public pipeline cannot help.

## What private context changes

- **Threads:** each private document is chunked and embedded as queries. The chunks form one or more private threads. Private threads get a share of the thread weight; the proposed default is 0.6 (Q13). That number is a default, not a finding. Public threads share the rest.
- **Retrieval and rerank:** these are unchanged. They run on the local embedder and reranker, and the private threads are just more threads.
- **Eligibility unlock:** a deterministic CV parse reads degree year, rank, appointments and prior sponsors. Opportunities now dropped as "restricted by career stage" can then be kept, labelled "eligible per your CV (private)". NIH's early-stage investigator definition must be cited from the NIH page in S13; until then it is UNVERIFIED.
- **Sponsor history:** prior sponsors listed on the CV raise the rank of the same sponsor's programmes. This is a rule in code, shown on the lead.
- **Explanations:** these come from the local model only. They may cite private documents. The display uses a lock icon and the label "from your private document".

## Citations and the validator (rules 3 and 4)

- **Session records:** each private document is a record that lives only in the session. It has `source: private`, a session-scoped id such as `private:aims#2`, no URL, and `fetched_at` set to the upload time.
- **Validator:** inside the session, the validator accepts session records as citations. Numbers and dates must still appear in a cited record, whether public or private.
- **Never stored:** session records never reach the Repository, the vector index, caches, exports or the audit log.

## The no-logs inventory (every write path today)

| Path | Normal mode | Private mode |
|---|---|---|
| `data/perch.db` (briefs, leads) | written | nothing from the session; the private brief lives in memory |
| `data/logs/model_calls.jsonl` | prompt hashes, tokens | **nothing**; hashes of sensitive text can be guessed by dictionary |
| `data/logs/brief_timings.jsonl` | timings and ids | nothing |
| embedding cache `data/cache/embeddings.db` | vectors by text hash | bypassed for private text |
| rerank cache | scores by profile hash | bypassed |
| LanceDB | opportunities only | unchanged, because private text is never indexed |
| uvicorn access log | method and path | private input travels in POST bodies only; log level stays at warning |
| Python tracebacks | full text | the error handler scrubs request bodies; the job error keeps the exception type only |
| Ollama server log | UNVERIFIED whether prompts are logged | verify first in S13; run with debug off |
| llama.cpp server log | UNVERIFIED | verify first in S13 |
| browser storage | tab, theme | no private text in local storage; inputs cleared when the session ends |
| upload temp files | — | none, because parsing works on bytes |
| core dumps, swap | system default | core dumps off in the process (`RLIMIT_CORE=0`); swap is not controllable and is documented |

- **Session end:** "End private session" drops everything. So does a 30-minute idle timeout or a server restart.

## Leaving the app

- **Default:** nothing derived from private text leaves. This covers exports, hand-off drafts (S12), Scout and MCP.
- **Opt-in obfuscated export:** the user can include private-derived content in an export, masked, behind a visible warning.
  - **Typed placeholders:** names, emails, phones, ORCIDs, grant numbers, institutions and other identifiers are replaced with placeholders such as `[PERSON-1]` and `[AWARD-1]`, the same placeholder each time.
  - **Novel phrases:** phrases that appear in the private documents and not in any cited public record are replaced with `[PRIVATE-PHRASE-n]`.
  - **The key:** the mapping back to the original stays in memory, so the user can unmask the text on screen.
- **Honest limit:** masking hides identifiers. It cannot hide the research direction, because a paraphrased aim still reveals the aim. The warning says so.

## Tests that define done

- **Canary test:** each synthetic file holds a unique token. After a full private brief, export and session end, no token appears in any file under `data/`, in any log, in `/tmp`, in browser storage or in an outbound request. Outbound requests are captured through a mock transport plus a proxy log.
- **Refusal test:** opening a private session with a hosted provider, or an endpoint off the allowlist, raises an error. A public URL without `PERCH_TLS_AT` refuses private mode.
- **Isolation test:** two concurrent private sessions cannot read each other's documents or results.
- **Masking test:** identifiers built at test time are masked consistently. Unmasking restores them.
- **Mechanism, measured (S13, if time):** NIH RePORTER carries each funded project's abstract. Using it as a stand-in for the "unfinished proposal" on the back-test rows shows whether private context raises hit rate. Report it as an upper bound, because the funded abstract is closer to the award than a real draft. The abstract field must be verified live first (rule 2).

## Floor if time runs short (cut order)

- **Paste-only input:** no upload parsing.
- **Core mechanics:** private threads and session records.
- **Safety:** the self-hosted-endpoint gate, session isolation, the no-logs paths and the canary test.
- **Dropped:** CV-based eligibility unlock, obfuscated export, MCP private tools.
