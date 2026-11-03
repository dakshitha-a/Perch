# REBUILD_PLAN.md — Perch v1, built to deploy

Written 2026-11-03 by Perch-dev, from Dakshitha's direction on 3 Nov 2026. This plan replaces S34 and the roadmap in `docs/PLAN.md`. The S-numbered sessions here follow the same session protocol as before (CLAUDE.md).

## Why we are rebuilding

- **The advice:** an advisor to the challenge, a former Facebook CIO, said the strongest pitch is a tool Temple could give students soon. He also said local GPUs cost more to run at scale than a cloud API key does.
- **The direction (Dakshitha):** make Perch as close to deployment-ready as possible. Aim for 1,000 concurrent users. Use no GPUs. Send model work to cloud models and do everything else on CPU.
- **The scope cut (Dakshitha):** private mode and unpublished research are removed completely.
- **What is added (Dakshitha):** real Temple scholarships and fellowships, a Temple-only toggle, school tags, Temple SSO as the future way in, and encrypted storage of each user's CV and entries.
- **The approach:** this is a rebuild, but most of the code carries over. The pipeline, sources, schemas, validator, skills, Scout and UI parts are kept and moved onto a new base. What changes is the base: storage, jobs, sign-in, model hosting and the private-mode layer.

## The fallback

- **What it is:** the current hybrid demo, frozen on 3 Nov 2026 at commit d6f6210.
- **Where it lives:** git tag `v0.1-demo-fallback`, branch `fallback/v0.1-demo`, a saved Docker image, a copy of the demo store and the package ZIP built from that commit. The local notes list the machine paths.
- **The rule:** `main` stays on the fallback until the rebuild passes the Friday gate below. Rebuild work happens on the branch `rebuild/v1` and merges into `main` only when green.
- **The Friday gate:** the submission is due 6 Nov 2026 at 12:00 pm. At 6:00 pm on Thursday 5 Nov, the orchestrator checks the gate and reports. If the gate fails, the fallback is submitted, the rebuild branch is linked as the deployment track, and this plan becomes the roadmap slide.
- **The gate:** the student path works end to end on the new stack. A guest can sign in, see Temple awards with the toggle and tags, and build a brief on a cloud model with CPU ranking. `make test` is green. The walk with axe is clean on the new screens. The demo URL serves the new build.
- **Honest estimate:** the full plan is about 15 sessions. Before Friday, Phases 0 to 4 and part of Phase 6 might be done at best. The gate is most likely met by a partial rebuild, or the fallback is submitted.

## Decisions taken on 3 Nov 2026

### Dakshitha decided

- **Standing rules 1 and 5 change as proposed.** The proposed wording is below. Dakshitha edits CLAUDE.md, because the agent may not edit standing rules.
- **The researcher side stays, behind a student-first UI.** Students land first. The researcher path is ported to the new stack.
- **Sentence checking uses MiniCheck on CPU.** MiniCheck is already the default grounder in `perch/grounding.py`. Clef and its GPU servers are retired.
- **Jev is a bench challenger only.** Jev is a hosted decision model. The existing `perch/llm/systemone.py` adapter says it is Jev-compatible, but that is UNVERIFIED: the Jev site shows a `POST /v1/decide` endpoint, so compatibility is checked when access arrives. Its site says it is in early access. Its privacy page is template text, and it states no data-retention terms. Jev gets a bench row once we have access and written data terms. A switch would be a later decision based on those numbers.
- **Stored user data is kept until the user deletes it,** with an automatic purge after 12 months of inactivity.
- **If CPU rerank is too slow, measure and then shrink.** If one brief's rerank takes over 10 seconds on CPU, Perch reranks fewer candidates and caches the results. The back-test is rerun for whatever setup ships, and the result is reported as measured.
- **Temple award pages are read once and cached for now.** Those awards have run for years and change slowly. For a real deployment, Temple supplies a verified dataset through an API, a database or a structured file, and Perch imports it.

### Perch-dev decided (override any of these)

- **One database: Postgres with pgvector.** Postgres holds records, vectors, users, encrypted user data, briefs, jobs, the audit log and the spend ledger. LanceDB is dropped. SQLite stays only as the fast store for unit tests, behind the same `perch/store/base.py` interface.
- **Redis for shared fast state.** Redis holds sign-in sessions, rate-limit and quota counters, and the short-lived response cache.
- **A job manager on Postgres.** Briefs, Scout turns, ingest and purges become jobs in a Postgres table. Workers take jobs with `SELECT … FOR UPDATE SKIP LOCKED`. This keeps the `JobRunner` interface in `perch/jobs.py`, which already names Postgres as the replacement for the thread pool.
- **Two process types.** The web process is stateless FastAPI. The worker process loads the CPU models and runs jobs. Both scale by adding copies.
- **CPU models stay the same models.** The embedder stays Qwen3-Embedding-0.6B and the reranker stays Qwen3-Reranker-0.6B. Keeping the same models means the back-test rows stay comparable, and no query costs money.
- **Cloud models through `perch/llm/`.** Anthropic is the default provider. Rule 6 is unchanged, so an OpenAI-compatible provider can be swapped in by config. Model choices per job are measured in Phase 3, not assumed.
- **Sign-in through an interface.** The `AuthProvider` interface has an OIDC implementation for Temple SSO. Temple's SSO service supports SAML, OIDC and CAS. Development uses Keycloak in Docker as a stand-in identity provider. A guest mode lets judges try Perch without an account, and it stores nothing.
- **Envelope encryption for user data.** Each user gets their own data key, AES-256-GCM through the `cryptography` package. A master key wraps each data key. In development the master key comes from `.env`. In production it comes from a key management service. Deleting a user destroys their data key, which makes their rows unreadable. Wrapped keys live in their own table with their own backup and retention, so restoring a database backup does not bring a deleted key back.
- **Containers, not a specific cloud.** Docker images for web and worker, Docker Compose for one host, and manifests that also run under Kubernetes. Postgres and Redis can be self-run or managed.
- **Scout is rebuilt as an open, grounded assistant (Dakshitha).** Fixed questions move to code. Open questions go to the cloud model with read tools and cited answers. A daily budget per account replaces the old per-address caps. Phase 8 has the detail.

### Security and speed (Dakshitha asked Perch-dev to lead, 3 Nov)

- **User rows are fenced in the database.** Postgres row-level security limits every user-data table to the signed-in user's id, so a bug in a query cannot read another user's rows.
- **Least privilege.** The web process and the worker use separate database roles. Neither can read the key table directly; only the key service code can unwrap a data key.
- **Sessions.** Sign-in sessions are random ids in Redis, sent as HttpOnly, Secure, SameSite cookies, with a short idle timeout. Every write request carries a CSRF token.
- **Transport and headers.** TLS between every service, a strict Content-Security-Policy, and no third-party scripts, as today.
- **Secrets.** Secrets come from the environment or a secrets manager, never from files in the image. The master key never leaves the key management service in production.
- **Logs.** Structured logs hold ids and hashes, never user text. The Phase 6 leakage check enforces it.
- **Fast reads.** pgvector uses an HNSW index. A connection pooler sits in front of Postgres. The web process is async and never runs a model.
- **Fast CPU models.** Each worker loads its models once. Phase 3 measures int8 ONNX versions of the embedder and reranker, and uses them only if the back-test shows no loss.
- **Fast first answers.** The brief page shows the deterministic leads first and streams the model text in as it arrives, as the staged brief already does.

### Proposed wording for standing rules 1 and 5 (Dakshitha to apply)

- **Rule 1, proposed:** "Public data only in the repo. No private or unpublished text in the repo, fixtures, tests, logs, or examples. Any sample data is synthetic and labelled `SYNTHETIC`. Perch does not accept unpublished research. A signed-in user's own CV and entries are stored encrypted under that user's key, may be sent to the deployment's contracted cloud provider after one consent at sign-up, and are deleted when the user asks or after 12 months of inactivity. Tests of user data use SYNTHETIC text only."
- **Rule 5, proposed change:** keep the first part. Replace the CV sentence with: "A session's models may read the user's CV and entries. Contact details (emails, phones, links) are blanked before any model sees them. User data is stored only encrypted, never in logs, caches or the audit log in plain text, and never leaves the deployment except to its contracted provider."
- **A related build-time note:** the one-time extraction of Temple award pages uses a cloud model as an offline data-preparation step. It is not a runtime model job. Every value it produces is checked by code against a quoted page sentence (rules 2 and 3), and the output is a reviewed dataset file. Dakshitha confirmed this on 3 Nov (Q46).

## Target architecture

### Request paths and what each one costs

- **Browse and filter:** a student opens the Temple awards list, flips the Temple-only toggle and picks school tags. This is a database read with a cached response. It needs no model and no worker.
- **Build a brief:** a signed-in user asks for their brief. The web process puts a job on the queue and the page polls for stages, as it does today. A worker embeds the query on CPU, retrieves with pgvector, applies the rules, reranks on CPU, then calls the cloud model for the summary and explanations. MiniCheck on CPU checks each sentence.
- **Ask Scout:** each turn is a job. The worker runs the loop on the cloud model with the same allowlisted tools.
- **Hand-off and cover points:** cloud model calls through the same job path, with the same validator.
- **Ingest and pre-cache:** scheduled jobs refresh public sources, embed new records and warm the caches.

### What 1,000 concurrent users means here

- **The definition:** 1,000 signed-in users active in the same 5-minute window.
- **The assumed mix:** every user browses, and up to 1 in 5 builds a brief in that window. That is about 40 briefs a minute at the peak. The mix is an assumption, and the load test reports results at several mixes.
- **Targets to test against:** browse p95 under 300 ms. A brief completes with p95 under 90 seconds at the peak mix. No errors from our own services.
- **The real ceiling is the provider.** At peak, the cloud provider's per-minute token limit decides how many briefs run at once. That limit is a contract number and is UNVERIFIED until Temple's account tier is known. The load test measures tokens per brief so the needed tier can be stated.

### Caching and pre-caching

- **Record vectors:** computed once at ingest and stored in pgvector. They are never computed per user.
- **Researcher profiles:** OpenAlex author data and topic threads are public. They are cached per author for 7 days and shared across users.
- **Researcher pre-cache:** a nightly job runs the deterministic stages for every Temple-affiliated OpenAlex author. Those stages are retrieval, rules and rerank. A researcher's first brief then needs only the model text.
- **Model text on public inputs:** a fit explanation for a researcher depends only on public records. It is cached by record id, profile hash, prompt version and model version.
- **Model text on user data:** a student's explanations depend on their CV. They are stored only in that user's encrypted rows and never in a shared cache.
- **HTTP cache:** the awards list, filters and record pages are cached in Redis for a short time and refreshed after each ingest.
- **Provider prompt caching:** fixed system prompts and tool schemas are sent as cacheable prefixes, which the Anthropic adapter supports.

### What is kept, moved or removed

| Area | Today | In v1 |
|---|---|---|
| `perch/sources/` | Fetchers with live-verified fixtures | Kept. A Temple awards importer is added. |
| `perch/schemas.py` | pydantic records | Kept. `Scholarship` gains `school`, `temple_funded` and a source-sentence field per value. |
| `perch/store/` | SQLite and LanceDB | Postgres with pgvector added behind `base.py`. LanceDB removed. SQLite kept for tests. |
| `perch/jobs.py` | In-process thread pool | `PostgresRunner` and a `perch worker` command. |
| `brief.py`, `retrieve.py`, `rerank.py`, `score.py`, `eligibility.py`, `route_b.py`, `student.py` | Deterministic pipeline | Kept. Retrieval moves to pgvector. Rerank runs on CPU in the worker. |
| `perch/validate.py`, `perch/grounding.py` | Layers 1 and 2 | Kept. MiniCheck on CPU is the only grounder. |
| `perch/skills/` | Four model jobs | Kept and run on the cloud model. |
| `perch/scout/` | Agent loop, ten researcher and eight student tools, code-written answers | Loop and validator kept. Tools merge into a few broad read tools. Fixed questions move to code. Budgets move to per-account quotas. |
| `perch/llm/` | Providers, budget, audit, `decide`, systemone | Kept. The spend ledger moves to Postgres. Systemone stays for the Jev bench row only. |
| `perch/private/` | Sessions in memory, the student brief, the CV parse, warm briefs | Split up. The student brief, the CV parse, the file inputs and the threads move into the main package. Memory sessions, the write overlay and warm briefs are deleted. |
| `perch/egress.py`, `perch/privacy.py` | Private-mode masks and egress filter | Deleted. Contact blanking before model calls is kept and moved into `perch/llm/`. |
| `perch/model_server.py`, `perch/remote_models.py` | GPU model server for the hybrid demo | Deleted. Workers load the CPU models directly. |
| Clef units, `make decide-up` and `decide-down`, `deploy-2gpu` profile | GPU decision servers | Deleted. A `cloud-cpu` profile is the default. |
| `perch/api.py`, `request_models.py` | HTTP API | Kept. Session routes fold into it, with sign-in, accounts, consent and delete-my-data added. |
| `web/` | Vanilla JS UI | Kept. Student-first landing, award filters and an account page are added. `private.js` and the Local or Cloud dialog are removed. |
| `bench/`, `tests/`, `scripts/` | Bench, tests, walk | Kept. Private-mode tests and the canary are replaced by a user-data leakage check. |

## Phases and sessions

Each session follows the session protocol in CLAUDE.md. Code agents work in worktrees on Sonnet. Reviews run on Opus with fresh context and are given the code, not the builder's conclusions. QA is tester-then-fixer on Sonnet.

### Phase 0 — Rules, decisions, clean-up (S34)

1. Dakshitha applies the rule 1 and 5 wording, or edits it. Perch-dev updates CLAUDE.md's engineering conventions to name Postgres with pgvector as the deployment store, and adds the award-title exception to the public-ready convention: award titles copied from Temple's public pages may name people, while staff names and contacts stay out. `tests/test_public_hygiene.py` follows.
2. Record the decisions above in `docs/DECISIONS.md` and the plan change in `docs/PLAN.md`. This step was done on 3 Nov.
3. Create the branch `rebuild/v1` from `main`.
4. Stop the dev Clef units with `make decide-down`, then tell the other session sharing the node that those GPUs are free. The public demo stays up as the fallback.
5. The API budget is confirmed: about $30 of the $100 cap for the rebuild (Dakshitha, 3 Nov).

Done when: the rules are amended, the branch exists, and the dev GPUs are released.

### Phase 1 — Discovery and design (S35)

1. **Temple award inventory.** Find every public Temple page that lists scholarships, fellowships or awards. Sources include each school and college, Student Financial Services, Scholar Development and Fellowships Advising, the Graduate School, the Honors Program, Education Abroad and the international campuses. Search each temple.edu sitemap, check each page's HTTP status and robots.txt, and record every page in `docs/SOURCES.md`. Pages behind AccessNet sign-in, ScholarshipUniverse included, are listed and not read.
2. **Temple SSO facts.** Record what Temple's public pages say about OIDC and SAML registration. The claim names, such as school or role, are UNVERIFIED until Temple IT answers. The plan does not depend on a school claim.
3. **Provider facts.** Record the default model per job, prices and rate-limit tiers from the provider's current documentation.
4. **Reuse map.** A line-by-line map of `perch/private/`, `perch/api.py` and `web/` into keep, move and delete. This map is the brief for Phase 5.
5. **Architecture document.** `docs/ARCHITECTURE_V1.md` gives the data model, job states, cache keys, the encryption design, the auth flow and the threat model.
6. **Review:** an Opus design review with fresh context, given the document and the current code. It looks for gaps in scale, encryption and auth before any code is written.

Done when: the inventory, the reuse map and the reviewed architecture document are committed.

### Phase 2 — Data layer and job manager (S36, S37)

1. Postgres schema and migrations: records, record vectors in pgvector, users, user data keys, encrypted user rows, briefs, stages, jobs, the audit log and the spend ledger.
2. `PostgresRepository` behind `perch/store/base.py`. The existing repository tests are run against both SQLite and Postgres.
3. The encryption module: data-key creation, wrapping, field encryption, key rotation and crypto-shredding. Tests prove a deleted user's rows cannot be read.
4. Wrapped data keys live in a separate key table with its own backup schedule and retention, so a restore of the data backup cannot revive a deleted key.
5. The job manager: a `PostgresRunner`, the `perch worker` command, retries, timeouts and a dead-letter state. A test proves no job runs twice when ten workers start together.
6. Redis for sessions, quotas and the response cache.
7. Migrate the current public corpus into Postgres and compute every record vector once.
8. Docker Compose for local development: web, worker, Postgres, Redis and Keycloak.
9. **Review:** an Opus review with fresh context of the encryption module and key handling, before anything is built on it.

Done when: the corpus is in Postgres, a brief job runs on a worker from the queue, and the encryption tests pass.

### Phase 3 — The pipeline on cloud and CPU (S38)

1. Add the `cloud-cpu` profile and make it the default. Workers load the embedder, reranker and MiniCheck on CPU.
2. Measure on CPU: query embed time, rerank time for the top 50, and MiniCheck time per sentence. Apply the shrink rule if rerank takes over 10 seconds.
3. Run the four model jobs and Scout on the cloud model. Measure tokens and cost per brief, for researchers and students separately.
4. Build the caches listed under Caching and pre-caching, and the nightly researcher pre-cache job.
5. **Re-measure:** rerun the back-test with its keyword-only baseline on the shipped setup. Rerun the grounding bench and the Scout bench on the cloud model. Report every number as measured, including any drop from the GPU setup.
6. Add a Jev bench row if access and written data terms exist by then. Otherwise record why it is missing.

Done when: a brief runs with no GPU anywhere, and the bench rows for the new setup are in `docs/RESULTS.md`.

### Phase 4 — Temple scholarships and fellowships (S39, S40)

1. A one-time reader for the inventoried pages. It fetches each page politely, at one request per second per site and within robots.txt, and saves `<main>` only, with staff names and emails removed.
2. Extraction into `Scholarship` records. A cloud model may propose fields. Code keeps an amount, date, link or eligibility value only when it appears in a quoted sentence from that page. A year is never inferred. The rest stays "not stated".
3. New fields: `school` from the page's owner, `temple_funded` only when the page says the award is Temple's, and an audience level.
4. Dedupe across sites, because university-wide programs appear on several school pages. Each kept record links every page it appeared on.
5. Write the reviewed result to a versioned dataset file with provenance on every row (rule 4), and load it at deploy time.
6. **The verified-feed seam:** an importer that reads Temple's own dataset from an API, a database or a CSV or JSON file into the same records. The ScholarshipUniverse module becomes one implementation of it once a real export is seen.
7. The SYNTHETIC sample scholarships stay as their own list, badged as before (rule 11). Public Temple records and samples never share a list.
8. **QA:** a hand-check of a random 10% of records against their pages, with the error rate reported.

Done when: the Temple dataset is loaded, the hand-check is reported, and `docs/SOURCES.md` lists every page.

### Phase 5 — Sign-in, accounts and user data (S41)

1. The `AuthProvider` interface with an OIDC implementation, tested against the Keycloak stand-in.
2. Guest mode: no account, nothing stored, short-lived, with a clear banner.
3. Account roles: student, researcher and office staff. Staff screens are out of scope for v1. The role exists so they can be added.
4. Consent at sign-up, naming the provider that will read the user's CV and entries.
5. CV and entry storage, encrypted per user. The existing CV parse and contact blanking are kept.
6. Delete my data, which destroys the user's key, and the 12-month inactivity purge job.
7. Per-account quotas replace the per-address and per-hour caps.

Done when: a user can sign in, store a CV, build a brief, sign out, return and see it, then delete it all.

### Phase 6 — Remove private mode (S42)

1. Follow the Phase 1 reuse map. Move the student brief, CV parse, inputs and threads out of `perch/private/`.
2. Delete memory sessions, the write overlay, warm briefs, the egress filter, the masks, the Local or Cloud dialog and the second Cloud warning.
3. Replace the canary with a user-data leakage check. It plants a SYNTHETIC CV with a canary token and proves the token never appears in logs, caches, the audit log, job payloads or any plain-text column. The check must fail first, on a planted leak.
4. Remove the private-mode tests, and keep any that still test a kept behaviour.

Done when: no private-mode code remains, and the leakage check passes after failing on the planted leak.

### Phase 7 — Student-first UI (S43)

1. The landing page leads with students, and researchers are one click away.
2. The awards list gets a Temple-only toggle and school tags across the top. Tags come from the `school` field. Records with no stated school show under "All Temple".
3. Saved awards, past briefs and an account page with delete-my-data.
4. Help is rewritten for the new flow, with every claim checked against the code.
5. The walk gains flows for sign-in, guest, filters and delete. Each new geometry check is proven to fail first.
6. **Review:** an Opus UI/UX review with fresh context on the new screens.

Done when: the walk is clean with axe on laptop and phone, and the review's must-fix items are closed.

### Phase 8 — Scout, rebuilt as an open, grounded assistant (S44, S45)

Dakshitha (3 Nov): Scout comes up empty on most questions outside a fixed set. A fixed set is better served by a script, so Scout should answer open questions well, as long as its answers are grounded in cited records and the user's own CV.

1. **Fixed questions go to code.** The questions Scout handles well today, such as top leads, deadlines, compare and the hand-off, become buttons and deterministic answers written by code. No model is needed for them.
2. **Open questions go to the cloud model.** Scout answers in its own words, using the provider's native tool use. The MCP server stays as an extra way in for outside clients, and it no longer shapes how Scout works inside Perch.
3. **Tools become read tools.** Scout gets a small set of broad read tools: search records, read one record, read the user's brief, read parts of their CV and entries, and read their saved items. The tools are still allowlisted (rule 5), and none of them writes or sends anything.
4. **The grounding contract.** Every sentence about a record or about the user cites the record or the CV part it comes from. Layer 1 still checks every number, date and link, and MiniCheck still flags unsupported sentences. General guidance, such as how to structure a personal statement, is allowed and is shown under a "General advice" label. It may not name an award or state a number, date or eligibility fact.
5. **Feedback on the user's own material.** Scout may give feedback on the user's CV and entries against a cited record, for example what a fellowship asks for that the CV does not yet show.
6. **Budgets.** A per-account daily budget is shown to the user.
7. **A new bench.** The old 30-task bench measures tool choice on a fixed set. It is replaced by a set of open questions written by Perch-dev and Dakshitha, scored for citation validity, MiniCheck flags, empty answers and answer usefulness, which a person grades. Questions where the old Scout came up empty are included. The old bench is kept as a baseline.
8. **Review:** an Opus review with fresh context of prompt injection through record text and CV text, since Scout now writes more freely.

Done when: the open-question bench is reported against the old Scout, and the review's must-fix items are closed.

### Phase 9 — QA cycle (S46)

1. Tester then fixer, on Sonnet, for two rounds.
2. Measured: `make test`, the full walk with axe, the bench, the rehearsal script on the new stack, and the leakage check.

Done when: two rounds close with no open must-fix items.

### Phase 10 — Load test and operations (S47)

1. A load test with a pinned Python tool against the Compose stack, at 1,000 simulated users and the mixes above. The cloud model is replaced by the fake provider with measured latencies injected, so the test costs nothing. A small run of 20 briefs on the real provider confirms those latencies.
2. Report p50 and p95 per path, errors, worker queue depth and tokens per minute. State the provider tier that the measured peak needs. Every number is reported as measured, whether or not it meets the target.
3. Operations: health checks, structured logs with no user data, metrics, Postgres backups and a restore test.
4. `docs/deploy.md` is rewritten as a runbook: one host with Compose, or many hosts with managed Postgres and Redis.

Done when: the load-test report and the runbook are committed.

### Phase 11 — Security review, docs and release (S48)

1. **Review:** an Opus security review with fresh context on encryption, sign-in, sessions, injection through record text, quotas and secrets. Every must-fix item is fixed, then re-checked.
2. The docs are rewritten against the code: README, SPEC, ARCHITECTURE, SOURCES, RESULTS, the hosted spec and the deck's deployment slide. The last step checks every claim against the code.
3. Rebuild the demo on the new stack. Rehearse, walk and run the leakage check on the public URL.
4. `make package`, and tag `v1.0-deploy`.

Done when: the review is closed, the docs are verified, and the tag is pushed.

## Budget

- **Spent so far:** $2.60 of the $100 Anthropic cap, from the spend ledger on 3 Nov.
- **Planned for the rebuild, an estimate:** about $5 for the grounding and Scout bench reruns, about $5 for Temple page extraction, about $10 for smoke tests and rehearsals, and about $10 of margin. That is about $30 in total, inside the cap.
- **Not yet known:** the cost per student brief on the cloud model is UNVERIFIED. Phase 3 measures it. The deck uses only measured numbers.

## Risks

- **Time:** the plan does not fit before Friday. The fallback covers the submission.
- **CPU speed:** rerank and MiniCheck speed on CPU are not measured yet. Phase 3 measures them, and the shrink rule applies.
- **Temple pages:** many pages state no amounts or deadlines, and some list stale dates. Those values stay "not stated".
- **SSO:** Temple IT must register Perch as an application before real sign-in works. Until then, guest mode and Keycloak cover the demo.
- **Provider limits:** the needed rate-limit tier is a contract question for Temple.
- **Jev:** access and data terms are unknown, so it stays off the request path.
- **Names in award titles:** many endowed scholarships carry a donor's name in their title. The public-ready convention allows no other people's names in tracked files, so award titles copied from Temple's public pages become an exception (Dakshitha, 3 Nov).
