# Perch — technical specification v1.4

*See every route to fund your work.*

Temple AI Build Challenge, Fall 2026. Owner: Dakshitha. Public data only. Items marked **[verify]** are believed true and must be checked against the source before Demo Day. The published HTML version of this spec is the canonical one; its source is `docs/design/spec.html` (v2.0, as built, S33), and this Markdown copy is for Claude Code.

## 1. Users, working backwards

The question nobody at Temple can answer quickly today: *if this lab's federal line ends or is cut, what else fits this specific body of work, and what is the evidence?* Pivot-RP and SPIN answer "which calls match these keywords?". Perch answers the question above, from the researcher's own papers, with a measured hit rate.

A student has the same shape of question: *which fellowships and scholarships could I apply for, what do I still need, and what would I say for myself?* Perch answers it from the student's CV, checked by rule against each record, with the points an application could make (S18, S33). Both audiences are primary users and are sold equally (Dakshitha, 2026-11-01).

| User | Role in v1 | Job |
|---|---|---|
| Principal investigator | primary | See realistic alternatives for *my* work, ranked, with reasons I can check; decide which office to talk to. Keeps/dismisses leads, edits and sends the hand-off. |
| Student (undergraduate or graduate) | primary | See the fellowships and scholarships I may be eligible for, each checked against *my* CV by rule, with what I still need; the points my application could make; a note to the right office, which I send myself. |
| Research Development staff (Office of the VP for Research) | secondary | Receive a hand-off that already contains the evidence. |
| Technology Commercialization staff | receives (v1), uses (v2) | Receive industry-route hand-offs. Leads are labelled inferences; the app never says "should partner". |
| Scholar Development and Fellowships Advising staff | receives | Receive a student's note about public fellowships, with the rule read-out and what is still needed. |
| Student Financial Services staff | receives | Receive a student's note about scholarships. Until a real feed is licensed, the scholarship records are a SYNTHETIC sample, and the note says so. |

Out of scope for v1: postdocs (NIH F32 and F33 listings are shown to a student only to say why they do not fit); department-wide batch scans (opt-in, v2); anything built from real unpublished or confidential text. The scholarship corpus is a SYNTHETIC sample until a real feed is licensed (§13, phase 3); the fellowship list is public.

## 2. Why this is not another Pivot

Temple subscribes to Pivot-RP, SPIN and Dimensions (research.temple.edu). The comparison must quote Temple's own descriptions of those tools **[verify before the slide]**.

| Capability | Pivot-RP / SPIN / Dimensions | Perch |
|---|---|---|
| Starting point | Keywords, or a profile the researcher maintains | The researcher's published papers, resolved automatically |
| What you get back | A list of matching opportunities | Ranked list + fit explanation citing the researcher's own papers and the opportunity text |
| Routes | Funding opportunities; Dimensions adds patents/grants as records | Grants, foundations and industry leads compared side by side |
| Accuracy | Not reported | Back-tested on Temple's public awards; hit rate on the results slide |
| What happens next | Researcher writes an email | Pre-filled hand-off to the owning Temple office, evidence attached |
| Trigger | Keyword alerts | Award-horizon monitoring |
| Where it runs | Closed vendor SaaS | Open source; any model provider or a local model; can run entirely inside Temple |
| Reach from other tools | Web portal | MCP server usable from Copilot **[verify]**, Claude, or a local agent |

One-line answer for the judges: Pivot finds things that mention your keywords. Perch reads what you have published, tells you which routes fit and why, shows you how often it is right, and plugs into whatever AI platform Temple already uses.

## 3. Inputs and outputs

**In**
- Researcher identity, one of: name + "Temple University"; ORCID iD; OpenAlex author ID; up to 20 DOIs. Resolved to one OpenAlex author record; user confirms the match before anything runs.
- Optional constraints: amount range, horizon (months), routes to consider, up to 5 emphasis keywords, exclusion keywords.
- Optional documents (§4), held in the session only: a CV, a research direction, a draft proposal, unpublished work. Tests and demos of them use SYNTHETIC text.

**In — student brief (S18, S33)**
- A CV, pasted or uploaded (text, Markdown, DOCX or PDF). Code reads level, year, major, GPA, enrolment, expected graduation and the number of referees by rule.
- An interests note, which steers the search; up to five achievements, which are session records an explanation or a cover point may cite.
- No public identity is needed. A student session is private by construction: choosing Student opens the session before any text leaves the browser.

**Out — the resourcing brief**
- Research profile: 3–6 topic labels, 5–10 key papers (title, year, venue, DOI link), public federal awards with start/end dates, and the **public award horizon** (end date of the last public award). Nothing about lab finances is inferred.
- Route A, grants and foundations: up to 10 open opportunities; sponsor, title, deadline, award size and eligibility *copied from the record*; 2–3 sentence fit explanation citing 1–3 of the researcher's papers; fit score.
- Route B, industry leads: up to 5 organisations; the public signals found; suggested relationship type; fit explanation; confidence label; always "inferred from public signals; not verified".
- Comparison: money, time to decision, effort, IP implications, evidence strength. Likelihood only for Route A, only as the back-tested hit rate for that opportunity type.
- Hand-off draft: editable email to Research Development or Technology Commercialization. Never sent by the app. The hand-off screen and the researcher export carry a fixed note: before anything goes to a sponsor, Temple routes it through ERA for institutional review and approval, and the note links to Find your research administrator. Routing does not change.
- Application points (S33, model skill 4, on request through Scout): for one record, 3 to 6 points a cover letter could make. Each point pairs what the record asks for, cited to the record, with what the applicant has, cited to the CV, a document, a paper or a public award; up to three things the record asks for that no document shows are listed too. Checked by the validator and the grounding model; shown on the card to copy; never in exports or hand-off drafts.
- Evidence panel: every claim links to its record. A claim with no record is not shown.
- Export: PDF and Markdown; JSON of records.

**Out — the student brief**
- Your options: Fellowships (public), from Temple's Scholar Development and Fellowships Advising list and NIH F-series listings, and Scholarships and awards (sample), from the SYNTHETIC corpus, never in one list. Each option carries a verdict by rule (eligible, may be eligible, not eligible), the rule it rests on, Still needed (what the record asks for that the CV does not show), and a one-sentence fit explanation checked against the listing and the student's own text. Deadline and amount copied from the record.
- What Perch read: the rule read-out of the CV, so the student can check it.
- Application points (S33): the same skill 4, for one fellowship or sample scholarship, from the CV, the interests note and the achievements. A sample scholarship gives sample points, and the card says so.
- Compare and the note: kept options in two tables, public and sample apart; a code-written note to Scholar Development and Fellowships Advising or Student Financial Services. Never sent by the app.
- Export with a sample banner; the full brief, including the CV values in verdict lines, with a note that it includes text from the user's documents.

## 4. Private context: CV and unpublished directions

> **Retired on `rebuild/v1` (S42, 4 Nov 2026).** Dakshitha's decision of 3 Nov 2026 (DECISIONS.md) replaced private mode with accounts: a signed-in user's CV and entries are stored encrypted under that user's key, and a guest's brief lives in Redis for one hour. Private sessions, the Local and Cloud switch, masks and the second warning are gone. Unpublished research is not accepted. The text below is kept as history of the fallback build at the tag `v0.1-demo-fallback`.

**Private by default** (S23, 2026-10-29, Dakshitha). With no user accounts, every brief is a session held in memory: no stored briefs, no reuse, no browser history, no per-user logs. Public records fetched for a brief stay cached. Models are local by default; a Local / Cloud switch sends the four model skills to a named cloud provider after a warning the user confirms; a session that holds documents gets a second warning that lists which documents would leave, and nothing leaves until the user confirms it (rule 1 as amended 2026-11-01; the deployer may also disable this with `PERCH_CLOUD_DOCUMENTS`). Monitoring is shelved until a user system exists (`perch/shelved/monitor/`). User guide: `docs/private-mode.md`.

**Private mode** (expanded 2026-10-29 at Dakshitha's request; full design in `docs/design/PRIVATE_MODE.md`; since S23 the documents part of every session). A researcher adds a current CV, a research summary, an unfinished proposal or unpublished work, and the routes are tailored to it.

- Self-hosted only: served wherever every model runs on the deployer's own hardware, a public URL included (Q12); the provider layer refuses endpoints off the deployment's allowlist; on a public URL the connection must be decrypted on the Perch server, or the tunnel provider is named; sessions are isolated.
- No logs: nothing from the session is written to the store, audit log, caches or timings. In the browser, the tab's sessionStorage holds only the session id and flags such as "built from the SYNTHETIC sample", so a reload resumes the brief; it holds no text, and closing the tab forgets it (review W18, 2026-10-31). The inventory of write paths and what private mode does with each is in the design doc.
- Tailoring: private documents become private threads with a larger share of the weight (default proposed, Q13); a deterministic CV parse can unlock career-stage-restricted calls and raise prior sponsors' programmes; a private-only brief needs no public profile.
- Citations: private documents are session-only records the validator accepts in the session; numbers and dates still come from a cited record.
- Models and the CV (S33, rule 5 as amended 2026-11-01): a session's models may read the CV and documents. Contact details (emails, phone numbers, links, ORCID) are blanked in every model prompt view, for every skill. The CV is capped at about 3,500 characters in a prompt, preferring the education, appointment and position, funding, award and skills sections. Skill 4, application points, is the one skill that reads the CV text as such, and only for the one record the user asks about; the eligibility rules still read the CV by code. Nothing from it is retained, and nothing leaves the session except by the user's informed choice (rule 1).
- Leaving the app (decision of 2 Nov 2026): the session is fenced and purged when it ends, so an export gives the full brief and carries a note that it includes text drawn from the user's documents and stays on their computer. The export's only mask is an optional "Mask my ongoing research" box, shown when the session holds a draft proposal, research direction or unpublished work; it masks phrases from those documents and nothing else, and masking cannot hide the research direction. Hand-off drafts keep the default of leaving private-derived text out, with their own mask option for names, identifiers and private phrases.
- Evidence: a canary-token test defines "no logs"; a RePORTER-abstract back-test variant measures the mechanism as an upper bound. Tested only with `data/synthetic/` personas.
- Deployment choice (2026-11-01, Dakshitha): documents go to a hosted provider only when the user chooses it for the session, after an informed warning. The person deploying decides whether Perch is offered fully local, hybrid or cloud-only. If a hosted provider is used, that person also decides whether the API key is a zero-data-retention key, if the provider offers one, and the privacy statement says which. See the architecture section "Deployment choice: local, hybrid or cloud".

## 5. Walkthrough

1. **Find** — name or ORCID; pick the right author from 1–3 candidates; *Build brief*.
2. **Profile** — research profile first (10–20 s); confirm/remove papers; optional constraints; progress bar.
3. **Routes** — two columns; each lead a card: fit score, record fields, cited explanation, Keep/Dismiss.
4. **Compare** — kept leads in one sortable table; evidence panel from any cell.
5. **Hand off** — choose office, edit draft, copy or open in mail; shareable link and PDF. Under the To line a fixed note says Temple routes every grant proposal, and any company agreement that brings Temple funding, through ERA, with a "Find your research administrator" link.
6. **Ask Scout** — plain follow-ups on the brief; "What could my cover letter for the top lead say?" runs `cover_points` (S33) and puts the checked points on the card with Copy.

**Student walkthrough** (S18, S33)

1. **Student** — choose Student on Find; the session opens before any text is sent. Paste or upload the CV; add an interests note and up to five achievements; *Build brief*.
2. **Your options** — two lists, Fellowships (public) and Scholarships and awards (sample), each option with its verdict by rule, Still needed, and a checked fit sentence; Keep the ones worth a closer look.
3. **What Perch read** — the rule read-out of the CV, to check and correct by replacing the CV.
4. **Compare** — kept options in two tables, public and sample apart; pick Scholar Development and Fellowships Advising or Student Financial Services, and a code-written note appears to edit, copy or open in mail.
5. **Ask Scout** — "Which of these close first?" or "What should my application for my top option highlight?": the second runs `cover_points` on the CV, the interests note and the achievements, and the points show on the card with Copy. On a sample scholarship, the card and answer say the points are for an invented sample.

Demo Day runs Find → Routes → Hand off on a precomputed persona in ~75 s, with one stage (fit explanation) executed live, and the student path on a SYNTHETIC persona.

## 6. Architecture

```
Public sources (read only, cached)        Fetchers (deterministic Python)        Records store
OpenAlex · NIH RePORTER · NSF ·    →     rate-limited, retried, normalised, →   Postgres + pgvector + pg_search (Temple)
Grants.gov + NIH Guide · SBIR.gov         provenance on every row                SQLite + LanceDB (demo); embeddings local
                                                                                        ↓
                                                              Retrieval and scoring (deterministic)
                                                              per-thread hybrid search → RRF → eligibility filter → rerank
                                                                                        ↓
                                     Model layer (provider-agnostic: Anthropic · OpenAI-compatible · Ollama/vLLM)
                                     Scout agent (allowlisted tools, budgets, Stop) + four bounded skills:
                                     1 profile summariser · 2 fit explainer/reranker · 3 hand-off drafter · 4 application points (S33)
                                     every output → citation validator (layer 1 deterministic, layer 2 grounding model)
                                                                                        ↓
                                     API (FastAPI, async jobs, audit log) · MCP server (same tools) · Web app (React + Vite)
                                                                                        ↓
                                                                   User: keeps/dismisses, edits and sends hand-off
```

Only the model layer runs a language model, and the agent inside it can call nothing but the deterministic functions. Every arrow into the store carries provenance; every arrow out of the model layer passes the validator.

**Stack:** Python 3.12, httpx, pydantic v2; Postgres 16 + pgvector (+ pg_search) in production, SQLite + LanceDB for the demo, behind one repository interface; embeddings chosen by the block benchmark (default Qwen3-Embedding-0.6B, challenger SPECTER2); provider layer `perch/llm/` with three primitives, chat, embed and decide (§8); own 200-line agent loop; MCP server on the official Python SDK **[verify version]**; FastAPI + job runner; React + Vite; Docker Compose with `make demo`. Reuse from NextTex/NexusQC limited to infrastructure, disclosed in the AI-use log; the approve-every-action pattern borrowed for Scout in S10 was removed in S28 (`docs/design/SCOUT_SPEC.md`).

**API:** `POST /briefs` · `GET /briefs/{id}` (status + partial results) · `POST /briefs/{id}/leads/{lead}/keep` · `POST /briefs/{id}/handoff` · `GET /records/{id}`. Audit log per model call: prompt hash, model, version, tokens, cost, validator result.

## 7. Candidates to benchmark, block by block

One held-out set (10 Temple PIs, date cut-off enforced), one script (`make bench`), one table. Change one block at a time; report the keyword-only baseline on every row.

| Block | Default → challengers | Idea | Deciding metric |
|---|---|---|---|
| Profile build | OpenAlex author/works/topics; recency-weighted vectors → **cluster into 2–4 research threads**, match per thread, merge with RRF | One blurred career vector is why keyword matchers miss | Back-test MRR, threads vs single |
| Embeddings | Qwen3-Embedding-0.6B → Qwen3-4B; SPECTER2; BGE-M3; harrier-oss-v1-0.6B; granite-embedding-english-r2 (CPU floor) | General MTEB leaders may not transfer to science; instruction prefixes allow asymmetric embedding | Recall@50; throughput |
| Retrieval | Hybrid dense (HNSW) + BM25 with RRF → dense-only; BM25-only (baseline); learned sparse | Calls are full of exact tokens dense search blurs | Recall@50; p50 latency |
| Eligibility filter | Deterministic rules on close date, applicant types, award ceiling, activity code, agency; never a model | The trust argument lives here | Zero ineligible leads |
| Rerank | Qwen3-Reranker-0.6B → 4B; BGE-reranker-v2-m3 (baseline); mxbai-rerank-large-v2; jina-reranker-v3 **[verify licence]**; decision models via `decide` (score: fit of opportunity to thread): Clef-flash (local default), Clef (accuracy challenger), Jev (hosted) | Top-50 → top-10, batched, cached | Hit@5/10 with vs without; for decision models, hit@5/hit@10 vs the cross-encoder |
| Fit explanation (skill 2) | Claude Sonnet via API (prompt caching) → Qwen3-8B/14B local; Gemma 4 26B-A4B (thinking off); gpt-oss-20b | Reasoning scratchpad then constrained JSON (XGrammar on vLLM; native structured output on API); parallel across leads | Validator pass rate; human agreement; latency; $/brief |
| Claim validator | Layer 1 deterministic (IDs, numbers, dates) → layer 2 grounding model: LettuceDetect, MiniCheck, HHEM-2.1-Open; decision models via `decide` (judgment: does record R support sentence S?, batched per explanation): Clef-flash and Clef always tested together, plus Jev (hosted) | Layer 1 catches fatal errors; layer 2 catches paraphrased overreach | Agreement with QA log; false-flag rate |
| Scout agent loop | Claude via API → Qwen3-8B/14B local; Gemma 4 26B-A4B; gpt-oss-20b | Benchmark end-to-end tasks, not single tool calls | Completion on 20 scripted follow-ups; wrong-tool rate; restraint |
| Route B signals | 1 company-type institutions publishing in the topics; 2 SBIR/STTR awards in the topics; **3 company-authored works citing the researcher** | Signal 3 is the strongest public evidence of interest and costs nothing | Hand-judged precision |
| Serving (local) | vLLM → SGLang; Ollama/llama.cpp on the laptop | Small models share the GPU; explanations are a batch | tok/s at 10 concurrent; TTFT; VRAM |
| Caching | Nightly embed of open opportunities; cache embeddings, rerank scores and explanations by content/profile hashes | Repeat brief in seconds | Warm-cache brief time |

Decision models are never used for skills 1–4 (profile summary, fit explanation, hand-off draft, application points) or for the eligibility filter. They are challengers only at the two decision points above.

## 8. Scout, and the platforms it runs on

Two layers: the deterministic pipeline (what the back-test measures) and Scout on top.

Scout can: run a brief end to end, each step as soon as the model asks for it; take plain-language follow-ups ("foundations only, under $200k"); monitor (award within 12 months of ending or new opportunity above threshold → refresh and draft a notification; built in S16, shelved in S23 until users have accounts); explain its ranking from its records.
A student brief gets its own allowlist instead (S24, S33): search_options, check_option, explain_verdict, read_cv, compare_options, draft_note, cover_points and get_record. All but cover_points read only rule results and records; cover_points (S33) reads the CV, the interests note and the achievements, with contact details blanked, on the session's models, and returns checked points for a cover letter. Student Scout runs only in a private session; the MCP server keeps the researcher tools.

Scout cannot: call anything outside the allowlist (no web, no shell); state a number or date not in a cited record; send email or change a record; exceed the per-brief budget; read anything about a researcher that is not a public record or a document they added to the session.
Tools: `build_profile · list_awards · search_opportunities(route, filters) · get_org_signals · explain_fit · compare · draft_handoff · cover_points · get_record`, fixed to the brief's researcher (cover_points, S33, is model skill 4: the points a cover letter for one record could make, each citing the record and the CV, a document, a paper or an award); the MCP server adds `resolve_author` and an `author_id` argument, because its client starts without a researcher. Every call logged with args and result hashes; a brief is replayable.
UI (S28, `docs/design/SCOUT_SPEC.md`): each step runs as soon as the model asks for it; a Stop button ends the question between steps. Above the answer, "How Scout read your question" lists each finished step with its filters; the step cards fold under the answer, each saying where it ran: code, a local model or a named Cloud provider. The fit, hand-off and cover-points steps' model spend counts toward the session budget; cover_points runs on the session's hand-off provider, local by default and Cloud only after the documents warning is confirmed.

Provider layer: one interface for chat, tool calling, structured output; adapters for Anthropic, OpenAI-compatible endpoints, Ollama and vLLM; model per role in config; fallback mode (structured prompts + validator) for small local models that tool-call poorly; three models benchmarked on the back-test.

Decide primitive: `decide` sits in `perch/llm/` beside chat and embed. A typed question goes in: a choice among labelled options, a score on a fixed scale, or a yes/no judgment. A typed value plus a confidence comes out. Three adapters:
- **Jev-compatible adapter**, one adapter for three models, because the Clef API is Jev-compatible **[verify]**:
  - **Clef-flash** (Cloudflare; 9.4B, Apache-2.0, GGUF weights) **[verify]**: the default local decision model.
  - **Clef** (Cloudflare; 27B) **[verify]**: the accuracy challenger.
  - **Jev** (TypeSafe AI): the hosted option; no self-hosted weights as of September 2026 **[verify]**.
- **Strands Decider 2B** **[verify]**: CPU-only fallback for machines without a GPU.
- **LLM fallback:** constrains the answer to a single token per option and reads the token logprobs, so `decide` works on any model whose provider returns logprobs **[verify which of the Anthropic, OpenAI-compatible, Ollama and vLLM adapters expose them]**.

How much to trust the published numbers: published decision-model scores are mostly run by the vendors themselves, and none of them measure our judgment, "does record R support sentence S?". Perch's own bench (§7, `make bench`) decides which model is used. For the validator role, full Clef must be tested alongside Clef-flash, because Clef-flash has reported misses on safety-sensitive cases **[verify]**.
MCP server: the same tool set with the same allowlist, validator and budgets, usable from Claude Desktop/Code, Copilot where MCP is supported **[verify]**, or a local agent. Demo moment: a teammate asks a local Ollama agent for a brief through the MCP server and gets the same cited answer.

Validator rule (pipeline and agent alike): an output citing an unknown ID, or containing a dollar amount or date not in cited records, is rejected and regenerated once; on second failure the lead is shown without explanation and flagged. Rejection rate reported per model.

## 9. Data sources

| Source | Used for | Status |
|---|---|---|
| OpenAlex | author resolution, works, abstracts, topics, institution; company publications and citations for Route B | exists; verify rate limits |
| NIH RePORTER v2 | Temple awards, dates, funding-opportunity number (back-test ground truth) | exists; verify field name |
| NSF Award Search | Temple awards, expiration dates | exists; verify fields |
| Grants.gov | open federal opportunities | verify endpoint and terms |
| NIH Guide archive | historical announcements for the back-test | verify structured access |
| SBIR.gov | companies with small-business awards | verify |
| Foundation listings | curated list with URLs | v1.5. Foundation leads will go to Corporate and Foundation Relations, through the school's or college's development team. |
| Temple public pages | office names and pages | verified 2026-11-02; no contacts stored |
| PatentsView | patent signals | v2 (API key) |

Dropped: SEC filings, job postings, press releases.

## 10. Evaluation

- **Back-test (NIH only):** for each of 10 Temple PIs, profile from papers before the award start; retrieve against announcements open at that time; rank of the actual announcement. Report hit@5, hit@10, MRR, and the keyword-only baseline.
- **Citation discipline:** validator rejection rate; share of cited records a human reviewer agrees support the sentence.
- **Cost and latency:** from the audit log, per stage.
- **Human review:** two interviews; three persona runs reviewed claim by claim. Counts, not adjectives.

## 11. Deployment

**Demo Day:** Docker Compose on the lab node; SQLite + LanceDB; API key server-side only; public HTTPS via an outbound tunnel **[check lab network policy]**; fallback 1 laptop + phone hotspot, fallback 2 recorded video; demo personas precomputed with one live stage; anonymous rate limit 10 briefs/hour.

**GPU profiles.** The deployment target is one 32 GB GPU, two at most. The 8-GPU layout is for development and `make bench` only. `PERCH_PROFILE` selects the profile.

- **deploy-1gpu** (default target): everything on GPU 0. One chat model from the Ollama list (default `qwen3:14b`, 8k context), Clef-flash Q4_K_M as the decision model, Qwen3-Embedding-0.6B, Qwen3-Reranker-0.6B and the grounding model. Peak must stay under 28 GB.
- **deploy-2gpu**: chat model on GPU 0, everything else on GPU 1. This profile permits `qwen3.8:27b` as the chat model.
- **dev**: the 8-GPU development layout. Ollama on GPU 0 (port 11434, `qwen3.8:27b` stays resident), Clef-flash on GPU 1 (port 8097), Clef on GPU 2 (port 8098), the embed, rerank and grounding service on GPU 3 (port 8099), GPUs 4 and 5 as the bench pool.

**Deployment mode.** The person deploying also chooses the mode: fully local (every model role self-hosted), hybrid (local by default, Cloud by the user's choice per session, as the demo runs) or cloud-only (every role on a hosted provider). With a hosted provider, that person decides whether the API key is a zero-data-retention key, if the provider offers one, and the privacy statement says which. Documents leave only by the user's informed consent for the session (§4, `PERCH_CLOUD_DOCUMENTS`). See `docs/ARCHITECTURE.md`, "Deployment choice: local, hybrid or cloud", and the checklist in `docs/deploy.md`.

Chat-model candidates are the models already in Ollama on the lab node: `qwen3:8b` (5.2 GB), `qwen3:14b` (9.3 GB), `qwen3:30b` (18 GB, mixture-of-experts: cheap to run, large weights) and `qwen3.8:27b` (17 GB), with `qwen3-coder:30b` also present. Sizes are as `ollama list` reports them. `nomic-embed-text` is a benchmark baseline only; the retrieval embedder is still chosen by `make bench`.

deploy-1gpu VRAM budget. The budget column is an allocation target, not a measurement. The measured column is filled by the S8 single-card validation.

| Component | Weights on disk | Budget | Measured peak (S8) |
|---|---|---|---|
| Chat model, `qwen3:14b`, 8k context | 9.3 GB (`ollama list`) | 13 GB including KV cache | |
| Decision model, Clef-flash Q4_K_M | 6.73 GB (`ggml-org/Clef-Flash-GGUF`); 8.0 GB VRAM idle on its own GPU in dev | 7 GB (over by about 1 GB at default context; S8 to size `-c`) | |
| Embedder, Qwen3-Embedding-0.6B | UNVERIFIED | 1.5 GB | |
| Reranker, Qwen3-Reranker-0.6B | UNVERIFIED | 1.5 GB | |
| Grounding model (validator layer 2) | UNVERIFIED | 2 GB | |
| CUDA contexts and headroom | — | 2 GB | |
| **Total** | | **27 GB, under the 28 GB target** | |

**Temple (proposed):** hosted inside Temple; single sign-on **[verify system]**; Postgres + pgvector; nightly refresh; two model tiers from one codebase — tier 1 hosted API under an enterprise agreement with no training on inputs for public-work briefs; tier 2 local model (vLLM on a Temple GPU node) for anything confidential, never leaving the network. Owners: Research Development (Route A), Technology Commercialization (Route B). Pilot with one college.

## 12. Responsible design

Risks: wrong claims → validator + QA log + numbers only from records; reputational → persona with written permission or synthetic, inference labels, anonymise toggle; over-reliance → brief labelled a starting point, hand-offs go to a human office.
Protected data: public records only by construction; no training on inputs; audit log holds hashes in production; confidential disclosures only on tier 2; department scans opt-in and v2.
People in control: author match confirmed first; keep/dismiss on every lead; nothing sent; offices decide.
Accessibility and feasibility: keyboard-navigable, labelled, contrast-checked, works from a QR code; one node, one command; cost measured.

## 13. Roadmap beyond the ten days

| Phase | Builds | Gate |
|---|---|---|
| 0 Demo Day (6 Nov) | prototype, NIH back-test, Scout, MCP server, local-model demo, public repo | placed or shortlisted by IBIT |
| 1 Hardening (Nov–Jan) | nightly refresh, foundations (leads go to Corporate and Foundation Relations through the school's or college's development team), monitoring, NSF back-test if mappable, accessibility audit, evaluation report, three faculty volunteers | hit rate holds on a held-out set; 2 of 3 volunteers would reuse; pilot proposal accepted by Research Development |
| 2 Pilot, one college (spring 2027) | hosted inside Temple, SSO, tier-2 local model, opt-in department view, hand-offs to named inboxes, outcome tracking | repeat use; ≥1 application or industry conversation traceable to a hand-off; security review passed; cost within budget |
| 3 University service (2027–28) | all colleges, patents for Route B, collaborator discovery, fellowships, student mode on real data (Temple's ScholarshipUniverse feed under its contract, or a licensed scholarship database, replacing the SYNTHETIC sample corpus through the seam in `perch/sources/scholarshipuniverse.py`; proposed owner: Student Financial Services, with SDFA for fellowships, to be agreed with them), MCP to Temple's Copilot, quarterly evaluation | annual review; renewal; decision on offering code to other universities |
| 4 Beyond Temple (optional) | institution, model and offices are config; consortium or open-source maintenance | — |

Post-Demo-Day ownership: the business team owns the pilot proposal, metrics, cost model and office conversations; engineering stays with Dakshitha until a funded developer exists.

## 14. Open items

Grants.gov API and archive access; NIH RePORTER opportunity-number field and NIH Guide archive; SBIR.gov API; lab node tunnel policy; demo persona permission or synthetic; current model names/prices; Temple SSO system; whether Temple's Copilot can attach an MCP server; Pivot/SPIN/Dimensions descriptions quoted from Temple's pages.
