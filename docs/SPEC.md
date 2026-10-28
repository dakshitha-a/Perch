# Perch — technical specification v1.4

*See every route to fund your work.*

Temple AI Build Challenge, Fall 2026. Owner: Dakshitha. Public data only. Items marked **[verify]** are believed true and must be checked against the source before Demo Day. The published HTML version of this spec is the canonical one; this Markdown copy is for Claude Code.

## 1. Users, working backwards

The question nobody at Temple can answer quickly today: *if this lab's federal line ends or is cut, what else fits this specific body of work, and what is the evidence?* Pivot-RP and SPIN answer "which calls match these keywords?". Perch answers the question above, from the researcher's own papers, with a measured hit rate.

| User | Role in v1 | Job |
|---|---|---|
| Principal investigator | primary | See realistic alternatives for *my* work, ranked, with reasons I can check; decide which office to talk to. Keeps/dismisses leads, edits and sends the hand-off. |
| Research Development staff (Office of the VP for Research) | secondary | Receive a hand-off that already contains the evidence. |
| Technology Commercialization staff | receives (v1), uses (v2) | Receive industry-route hand-offs. Leads are labelled inferences; the app never says "should partner". |

Out of scope for v1: graduate students and postdocs (fellowships); department-wide batch scans (opt-in, v2); anything built from real unpublished or confidential text.

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
- Nothing else in the public prototype. The private-context input (§4) is demonstrated only with synthetic data on a local model.

**Out — the resourcing brief**
- Research profile: 3–6 topic labels, 5–10 key papers (title, year, venue, DOI link), public federal awards with start/end dates, and the **public award horizon** (end date of the last public award). Nothing about lab finances is inferred.
- Route A, grants and foundations: up to 10 open opportunities; sponsor, title, deadline, award size and eligibility *copied from the record*; 2–3 sentence fit explanation citing 1–3 of the researcher's papers; fit score.
- Route B, industry leads: up to 5 organisations; the public signals found; suggested relationship type; fit explanation; confidence label; always "inferred from public signals; not verified".
- Comparison: money, time to decision, effort, IP implications, evidence strength. Likelihood only for Route A, only as the back-tested hit rate for that opportunity type.
- Hand-off draft: editable email to Research Development or Technology Commercialization. Never sent by the app.
- Evidence panel: every claim links to its record. A claim with no record is not shown.
- Export: PDF and Markdown; JSON of records.

## 4. Private context: CV and unpublished directions

Adds eligibility (years since degree, rank, prior sponsors), direction (a two-sentence "where this is going" as one extra, up-weighted thread), and history (previously awarded programmes raise the sponsor prior).

Privacy rules: runs only on the local-model tier (refused on the hosted tier); held in memory for the session; never written to store, audit log, cache or evaluation; CV parsing is deterministic for dates, degree, rank, sponsors and discards everything else; every lead it influences still cites only public records (the note is a query, never a citation).

Ten-day version: build the input and the tier gate; demo with a synthetic persona and an invented in-prep paragraph on Ollama on the laptop, with the UI stating "this never leaves this machine". Presented as a mechanism, not a measured gain.

## 5. Walkthrough

1. **Find** — name or ORCID; pick the right author from 1–3 candidates; *Build brief*.
2. **Profile** — research profile first (10–20 s); confirm/remove papers; optional constraints; progress bar.
3. **Routes** — two columns; each lead a card: fit score, record fields, cited explanation, Keep/Dismiss.
4. **Compare** — kept leads in one sortable table; evidence panel from any cell.
5. **Hand off** — choose office, edit draft, copy or open in mail; shareable link and PDF.

Demo Day runs Find → Routes → Hand off on a precomputed persona in ~75 s, with one stage (fit explanation) executed live.

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
                                     Scout agent (allowlisted tools, approve mode, budgets) + three bounded skills:
                                     1 profile summariser · 2 fit explainer/reranker · 3 hand-off drafter
                                     every output → citation validator (layer 1 deterministic, layer 2 grounding model)
                                                                                        ↓
                                     API (FastAPI, async jobs, audit log) · MCP server (same tools) · Web app (React + Vite)
                                                                                        ↓
                                                                   User: keeps/dismisses, edits and sends hand-off
```

Only the model layer runs a language model, and the agent inside it can call nothing but the deterministic functions. Every arrow into the store carries provenance; every arrow out of the model layer passes the validator.

**Stack:** Python 3.12, httpx, pydantic v2; Postgres 16 + pgvector (+ pg_search) in production, SQLite + LanceDB for the demo, behind one repository interface; embeddings chosen by the block benchmark (default Qwen3-Embedding-0.6B, challenger SPECTER2); provider layer `perch/llm/` with three primitives, chat, embed and decide (§8); own 200-line agent loop; MCP server on the official Python SDK **[verify version]**; FastAPI + job runner; React + Vite; Docker Compose with `make demo`. Reuse from NextTex/NexusQC limited to infrastructure and the approve-every-action pattern, disclosed in the AI-use log.

**API:** `POST /briefs` · `GET /briefs/{id}` (status + partial results) · `POST /briefs/{id}/leads/{lead}/keep` · `POST /briefs/{id}/handoff` · `GET /records/{id}`. Audit log per model call: prompt hash, model, version, tokens, cost, validator result.

## 7. Candidates to benchmark, block by block

One held-out set (10 Temple PIs, date cut-off enforced), one script (`make bench`), one table. Change one block at a time; report the keyword-only baseline on every row.

| Block | Default → challengers | Idea | Deciding metric |
|---|---|---|---|
| Profile build | OpenAlex author/works/topics; recency-weighted vectors → **cluster into 2–4 research threads**, match per thread, merge with RRF | One blurred career vector is why keyword matchers miss | Back-test MRR, threads vs single |
| Embeddings | Qwen3-Embedding-0.6B → Qwen3-4B; SPECTER2; BGE-M3; harrier-oss-v1-0.6B; granite-embedding-english-r2 (CPU floor) | General MTEB leaders may not transfer to science; instruction prefixes allow asymmetric embedding | Recall@50; throughput |
| Retrieval | Hybrid dense (HNSW) + BM25 with RRF → dense-only; BM25-only (baseline); learned sparse | Calls are full of exact tokens dense search blurs | Recall@50; p50 latency |
| Eligibility filter | Deterministic rules on close date, applicant types, award ceiling, activity code, agency; never a model | The trust argument lives here | Zero ineligible leads |
| Rerank | Qwen3-Reranker-0.6B → 4B; BGE-reranker-v2-m3 (baseline); mxbai-rerank-large-v2; jina-reranker-v3 **[verify licence]**; decision models Jev, Laya via `decide` (score: fit of opportunity to thread) | Top-50 → top-10, batched, cached | Hit@5/10 with vs without; for decision models, hit@5/hit@10 vs the cross-encoder |
| Fit explanation (skill 2) | Claude Sonnet via API (prompt caching) → Qwen3-8B/14B local; Gemma 4 26B-A4B (thinking off); gpt-oss-20b | Reasoning scratchpad then constrained JSON (XGrammar on vLLM; native structured output on API); parallel across leads | Validator pass rate; human agreement; latency; $/brief |
| Claim validator | Layer 1 deterministic (IDs, numbers, dates) → layer 2 grounding model: LettuceDetect, MiniCheck, HHEM-2.1-Open; decision models Jev, Laya via `decide` (judgment: does record R support sentence S?, batched per explanation) | Layer 1 catches fatal errors; layer 2 catches paraphrased overreach | Agreement with QA log; false-flag rate |
| Scout agent loop | Claude via API → Qwen3-8B/14B local; Gemma 4 26B-A4B; gpt-oss-20b | Benchmark end-to-end tasks, not single tool calls | Completion on 20 scripted follow-ups; wrong-tool rate; restraint |
| Route B signals | 1 company-type institutions publishing in the topics; 2 SBIR/STTR awards in the topics; **3 company-authored works citing the researcher** | Signal 3 is the strongest public evidence of interest and costs nothing | Hand-judged precision |
| Serving (local) | vLLM → SGLang; Ollama/llama.cpp on the laptop | Small models share the GPU; explanations are a batch | tok/s at 10 concurrent; TTFT; VRAM |
| Caching | Nightly embed of open opportunities; cache embeddings, rerank scores and explanations by content/profile hashes | Repeat brief in seconds | Warm-cache brief time |

Decision models are never used for skills 1–3 (profile summary, fit explanation, hand-off draft) or for the eligibility filter. They are challengers only at the two decision points above.

## 8. Scout, and the platforms it runs on

Two layers: the deterministic pipeline (what the back-test measures) and Scout on top.

Scout can: run a brief end to end or one approved step at a time; take plain-language follow-ups ("foundations only, under $200k"); monitor (award within 12 months of ending or new opportunity above threshold → refresh and draft a notification); explain its ranking from its records.
Scout cannot: call anything outside the allowlist (no web, no shell); state a number or date not in a cited record; send email or change a record; exceed the per-brief budget; read anything about a researcher that is not a public record.
Tools: `resolve_author · build_profile · list_awards · search_opportunities(route, filters) · get_org_signals · explain_fit · compare · draft_handoff · get_record`. Every call logged with args and result hashes; a brief is replayable.
UI: each tool call is a card; modes *ask before every step* (default) and *run and show me*.

Provider layer: one interface for chat, tool calling, structured output; adapters for Anthropic, OpenAI-compatible endpoints, Ollama and vLLM; model per role in config; fallback mode (structured prompts + validator) for small local models that tool-call poorly; three models benchmarked on the back-test.

Decide primitive: `decide` sits in `perch/llm/` beside chat and embed. A typed question goes in: a choice among labelled options, a score on a fixed scale, or a yes/no judgment. A typed value plus a confidence comes out. Three adapters:
- **Jev** (TypeSafe AI): hosted API; no self-hosted weights as of September 2026 **[verify]**.
- **Laya** (Convai Innovations): open source, runs locally; reportedly needs fine-tuning before use **[verify]**.
- **LLM fallback:** constrains the answer to a single token per option and reads the token logprobs, so `decide` works on any model whose provider returns logprobs **[verify which of the Anthropic, OpenAI-compatible, Ollama and vLLM adapters expose them]**.
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
| Foundation listings | curated list with URLs | v1.5 |
| Temple public pages | office names and contacts | verified |
| PatentsView | patent signals | v2 (API key) |

Dropped: SEC filings, job postings, press releases.

## 10. Evaluation

- **Back-test (NIH only):** for each of 10 Temple PIs, profile from papers before the award start; retrieve against announcements open at that time; rank of the actual announcement. Report hit@5, hit@10, MRR, and the keyword-only baseline.
- **Citation discipline:** validator rejection rate; share of cited records a human reviewer agrees support the sentence.
- **Cost and latency:** from the audit log, per stage.
- **Human review:** two interviews; three persona runs reviewed claim by claim. Counts, not adjectives.

## 11. Deployment

**Demo Day:** Docker Compose on the lab node; SQLite + LanceDB; API key server-side only; public HTTPS via an outbound tunnel **[check lab network policy]**; fallback 1 laptop + phone hotspot, fallback 2 recorded video; demo personas precomputed with one live stage; anonymous rate limit 10 briefs/hour.

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
| 1 Hardening (Nov–Jan) | nightly refresh, foundations, monitoring, NSF back-test if mappable, accessibility audit, evaluation report, three faculty volunteers | hit rate holds on a held-out set; 2 of 3 volunteers would reuse; pilot proposal accepted by Research Development |
| 2 Pilot, one college (spring 2027) | hosted inside Temple, SSO, tier-2 local model, opt-in department view, hand-offs to named inboxes, outcome tracking | repeat use; ≥1 application or industry conversation traceable to a hand-off; security review passed; cost within budget |
| 3 University service (2027–28) | all colleges, patents for Route B, collaborator discovery, fellowships, MCP to Temple's Copilot, quarterly evaluation | annual review; renewal; decision on offering code to other universities |
| 4 Beyond Temple (optional) | institution, model and offices are config; consortium or open-source maintenance | — |

Post-Demo-Day ownership: the business team owns the pilot proposal, metrics, cost model and office conversations; engineering stays with Dakshitha until a funded developer exists.

## 14. Open items

Grants.gov API and archive access; NIH RePORTER opportunity-number field and NIH Guide archive; SBIR.gov API; lab node tunnel policy; demo persona permission or synthetic; current model names/prices; Temple SSO system; whether Temple's Copilot can attach an MCP server; Pivot/SPIN/Dimensions descriptions quoted from Temple's pages.
