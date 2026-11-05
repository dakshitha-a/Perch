# Architecture (v1, the deployed build)

> **This page describes the v1 build.** The earlier fallback build, with local models and SQLite, is kept as the record in [ARCHITECTURE.md](ARCHITECTURE.md). The full design contract, with numbered sections that the code cites, is [ARCHITECTURE_V1.md](ARCHITECTURE_V1.md). Where the contract and the code differ, the code is right, and the top of the contract says so.

Perch reads a Temple researcher's public papers, or a student's CV, and lays out the routes to fund that work. Every claim is cited to a public record. This page shows how the parts fit, what is plain code, what is a model, and what Perch never does. Each model name and number below was checked against the code on 5 November 2026.

## Perch in one picture

![Perch in one picture, for a general audience. You give Perch your papers or your CV. Perch reads public records. Plain code ranks them and checks the rules. A cloud model explains the fit, and every sentence is checked against the record it cites. You get every route with its source, and Perch sends nothing.](architecture/v1-simple.svg)

## How Perch fits together


![The v1 build, top to bottom. A browser reaches a stateless web app. Sign-in goes through an OpenID Connect server and guests need no account. The web app reads Postgres, keeps sessions and counters in Redis, and puts jobs on a queue table. One worker with one GPU takes the jobs and runs a plain-code pipeline: retrieve, eligibility rules, rerank, student and citizenship rules. Cloud models write text. Every output passes the citation validator, whose second layer is a small local model. Perch sends nothing.](architecture/v1.svg)

- **Browser and web app:** the browser talks to a web app that holds no state and never loads a model. It checks every request and hands slow work to a queue.
- **One GPU node:** Perch runs on one GPU node. It is served through a public HTTPS tunnel on port 443, with the sign-in server on its own port. Nothing else is exposed.
- **Postgres with pgvector:** one database holds the public records, their search vectors, the job table and each user's encrypted rows. Separate database roles for the web app, the worker and the owner see different tables, and row-level security guards the user tables.
- **Redis:** it holds sessions, rate limits, spend counters and the short-lived results of guest briefs. If Redis is flushed, everyone is signed out and guest briefs are lost. Nothing else is lost.
- **The queue and the worker:** a brief, a hand-off, a set of application points and a Scout question are each a job. A job carries ids only, never user text. The worker claims jobs from the Postgres table and loads the embedder, the reranker and the grounder once.
- **Public sources:** OpenAlex, NIH RePORTER, NSF Award Search, Grants.gov and Temple's own public award pages are fetched by plain code. Each stored row carries its source, its link and its fetch time. Temple's pages were read once, offline, into a reviewed dataset.

## Sign-in and guests

- **Sign-in:** Perch uses OpenID Connect with the authorisation code flow and PKCE. The sign-in server holds the passwords. Perch checks the ID token, its signing algorithm and its claims before it opens a session.
- **The stand-in:** the build ships with a Keycloak realm as the stand-in identity server. The code talks to a generic OIDC interface, so Temple's own single sign-on can replace it. That swap has not been tried, so it is UNVERIFIED.
- **The session:** the browser holds one cookie with the host prefix, and every write carries a CSRF token. The session itself lives in Redis.
- **Guests:** a visitor can browse, build a brief for a public OpenAlex author, or build one for a built-in sample student, then compare and export. A guest cannot upload a CV, use Scout, draft a hand-off or save anything.
- **Guest storage:** no user row is created. A guest brief is sealed in Redis under a key held for that guest session, and it expires after an hour.
- **Consent:** a signed-in user gives one consent at sign-up. It covers storing their CV and entries encrypted and sending text to the deployment's cloud model provider.

## Encrypted user data

- **What is stored:** a signed-in user's rows live in one `user_data` table. Each row has a kind. The kinds are `cv`, `entry`, `doc`, `brief`, `saved_item`, `handoff`, `cover_points`, `scout_session` and `profile`. The user's linked OpenAlex id is stored encrypted in the users table.
- **The profile row:** it holds two optional picks, a citizenship status and a state of residence, one row per user and side. Blank picks keep no row. The picks never reach a model and are never logged.
- **The cipher:** each field is encrypted with AES-256-GCM under a random data key made for that user. The row, the table, the column and the kind are bound into the blob, so a blob moved to another row fails to open.
- **The keys:** data keys are stored only wrapped by a master key, in a separate keys database with its own role. The master key comes from the environment in the test deploy. The code also supports a key service.
- **Deleting:** when a user asks, their key is destroyed and a tombstone is left, so the rows and any backup copy can never be read again. An account with no activity for 12 months is deleted the same way by a daily job in the worker.
- **No plain text:** user text is never written to a log, a cache, the audit log or a job payload. Contact details are blanked before any text reaches a model.

## The deterministic pipeline

This part runs the same way every time. It is what the back-test measures. No model writes a number, a date or an amount here.

- **Threads:** the researcher's papers are grouped into research threads, with topic names from OpenAlex. A student's CV is read by rule into facts such as level, class year and school.
- **Retrieval:** the embedder, Qwen3-Embedding-0.6B, searches the stored vectors by meaning and keeps the top 200 per brief. Retrieval is dense only. The keyword search is kept for the keyword-only baseline.
- **Eligibility rules:** plain code drops what the person cannot apply to. The rules read record fields only. They cover applicant type, open dates and notices that are not funding calls. Each drop keeps its reason.
- **Rerank:** the reranker, Qwen3-Reranker-0.6B, scores the best 100 eligible records, and a researcher brief keeps 10. Scores are cached, so a repeat brief does not rerun the model.
- **Temple internal group:** Temple's own faculty funding pages pass their own rules and show as a separate group of three. They never appear in the federal list.
- **Student rules:** every student lead carries one line per rule that the code ran or could not run. The rules cover level, class year, school, citizenship, residency, deadline and more. A line quotes the listing's own sentence.
- **Citizenship matcher:** it compares the optional picks with a listing only when the listing states a rule in one of a few closed phrases. A listing the user does not meet moves lower in the same list, with a quoted note. It is never dropped and never called ineligible. A sentence that states only a preference is not a rule.
- **Industry leads:** for a researcher, code counts public signals per company from OpenAlex and NIH records. A company needs at least two kinds of signal. Every lead says it is an inference.
- **Sample data:** SYNTHETIC sample records have their own screen. They never mix with public records in any list or number.

## Bounded model jobs

Models do a short list of jobs. Each goes through the provider layer in `perch/llm/`, which is the only place that imports a model SDK. The table gives the defaults of the `cloud-gpu` profile, which is the default profile. An environment variable can override a role. The Demo Day deploy sets none, so it runs these defaults (checked 5 Nov 2026, S54).

| Role | Job | Model |
|---|---|---|
| `gate` | sorts a Scout question as in scope, out of scope or distress | Claude Haiku 5.5 |
| `profile_summary` | writes the profile summary | Claude Haiku 5.5 |
| `extract` | suggests fields from Temple pages, offline | Claude Haiku 5.5 |
| `fit_explainer` | writes the fit explanation for a lead | Claude Sonnet 5.5 |
| `handoff` | writes the opening paragraph of a hand-off draft | Claude Sonnet 5.5 |
| `cover_points` | writes application points for one record | Claude Sonnet 5.5 |
| `scout` | answers a Scout question | Claude Sonnet 5.5 |
| grounder | checks each sentence against its cited record | MiniCheck RoBERTa Large, on the worker's GPU |
| embedder and reranker | search and rank | Qwen3 0.6B models, on the worker's GPU |

- **What a model never does:** it never writes a number, a date or an amount into a record. Code writes the hand-off greeting, the lead list and the sign-off. The model writes one opening paragraph.
- **Contact details:** the provider wrapper blanks emails, phone numbers and links in every prompt, every message and every tool result.
- **Where models run:** the embedder, the reranker and the grounder run on the worker. The fallback build also ran its text models locally. The v1 build does not.

## The citation validator and grounding

- **Layer 1, code:** a model output passes when every cited id is one it was given, every date equals a date in a cited record, every other number appears in a cited record, and every link is in a cited record.
- **Layer 2, MiniCheck:** a small grounding model reads each factual sentence beside the record it cites. It flags a sentence the record does not support. It flags and does not regenerate.
- **Where each layer runs:** fit explanations, application points and Scout answers get both layers. The profile summary and the hand-off opening get layer 1 only.
- **A failure:** a failed output is regenerated once with the errors fed back. A second failure is shown without the failing text and flagged. A refusal by the provider ends only that one output.
- **Honest limit:** MiniCheck cannot confirm a judgment such as "aligns with". The link sentence of a fit explanation is therefore checked by layer 1 only and labelled as an inference.

## Scout

- **What it is:** Scout is the assistant on the brief page. It answers questions about funding, the user's own brief, CV and entries, and how to use Perch.
- **Read-only tools:** Scout can call six tools and nothing else. They are `search_records`, `read_record`, `read_brief`, `read_cv_part`, `read_entries` and `read_saved`. None writes, sends or changes a row. A call to any other name is refused.
- **Gate first:** a small Haiku call sorts each question. An out-of-scope question gets a fixed refusal. A distress message gets a fixed note that names Temple's own support services. Both are written by code and call no large model.
- **Limits per question:** one question allows at most six model steps and four tool calls in a step. The tool text that reaches the model is capped.
- **Grounding per sentence:** every sentence that states a fact must cite an id that a tool returned in that turn. Layer 1 runs per sentence against the records it cites, and MiniCheck flags what the record does not support.
- **General advice:** content that cites nothing sits below a "General advice" line. It may carry no number, date, link, eligibility rule or award name.
- **Fixed buttons:** top leads, deadlines, compare and the hand-off are answered by code from record fields, with no model and no cost.

## Spend caps and budgets

- **One path:** every paid call goes through a spend meter. It reserves an estimate before the call, settles the true cost after it, and writes one ledger row of ids and numbers.
- **Per account:** a signed-in account has a daily budget in dollars. The default is $0.50 and the deploy can change it.
- **Per guest:** a guest session has a daily budget of $0.10 by default. A site-wide guest ceiling and a per-address limit bound abuse.
- **Whole deployment:** a hard monthly cap applies to the Anthropic key, $100 by default. The adapter warns at 80 percent and refuses at the cap. A price it does not know is charged at the dearest listed model.
- **Rate limits:** Redis counts requests per scope and per address, with limits set by the deploy.

## What Perch never does

- **It sends nothing:** hand-offs are drafts. The app sends no email and writes to no outside system.
- **It stores no unpublished research:** Perch does not accept it.
- **It invents no numbers:** award sizes, deadlines and dates are copied from record fields by code, and the validator checks every model sentence against them.
- **It does not hide doubt:** a sentence the grounder cannot confirm stays in the answer, marked, with a notice to open the record.
- **It claims no gain from a model change:** the Bench tab says what was measured and what was not.
