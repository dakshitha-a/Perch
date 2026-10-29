<div align="center">

<img src="web/favicon.svg" width="72" alt="">

# Perch

**See every route to fund your work.**

Perch reads a researcher's public papers and lays out the ways to fund that work:
open federal grants and industry leads. Every claim is cited to a public record.
Then it drafts a hand-off to the right Temple office, which you send yourself.

![python](https://img.shields.io/badge/python-3.12-3f8f72)
![models](https://img.shields.io/badge/models-self--hosted%20or%20API-d9a441)
![built for](https://img.shields.io/badge/built%20for-Temple%20AI%20Build%20Challenge-8a1e41)
[![license](https://img.shields.io/badge/license-MIT-6b7280)](LICENSE)

**[Quick start](#quick-start)** · **[Tour](#a-quick-tour)** · **[How it works](#how-it-works)** · **[How well it works](#how-well-it-works)** · **[Docs](#learn-more)**

<img src="docs/tour/hero.webp" alt="Finding a researcher by OpenAlex ID, building their brief, then opening the top grant's reasons and the paper it cites in the evidence panel." width="880">

<sub>Find a researcher, build the brief, and open the record behind any claim.</sub>

</div>

<table>
<tr>
<td align="center" width="33%"><img src="docs/tour/icon-record.svg" width="32" alt=""><br><b>Every claim has a record</b><br><sub>Dates and amounts are copied, never generated.</sub></td>
<td align="center" width="33%"><img src="docs/tour/icon-lock.svg" width="32" alt=""><br><b>Runs on your own models</b><br><sub>Private mode keeps drafts in memory only.</sub></td>
<td align="center" width="33%"><img src="docs/tour/icon-draft.svg" width="32" alt=""><br><b>Nothing is sent</b><br><sub>Hand-offs are drafts for you to edit.</sub></td>
</tr>
</table>

## Quick start

Perch needs [uv](https://docs.astral.sh/uv/) and `make`. uv installs Python 3.12 and every pinned dependency on first run.

```bash
git clone https://github.com/dakshitha-a/Perch && cd Perch
make test                              # lint and 210 tests; no network or GPU
uv run perch serve --models fake       # the whole app at http://127.0.0.1:8100, with fake models
```

With real models, a brief needs Ollama for the chat model and a GPU for the embedder and reranker:

```bash
uv sync --extra ml
uv run perch brief A5026494099 --explain      # an OpenAlex author id
```

Every command is in [docs/running.md](docs/running.md), and the two-GPU demo is in [docs/deploy.md](docs/deploy.md).

## A quick tour

> Researchers appear by alias in these clips. Paper titles and funding records are public and are shown as they are.

<table>
<tr>
<td width="50%"><img src="docs/tour/hero.webp" alt="A brief opening on its Routes tab, with the top grant's reasons and its cited paper." width="420"></td>
<td width="50%">

### Grants that fit, with the reasons

Perch groups a researcher's papers into research threads, and searches open
Grants.gov announcements by meaning and by shared words. Rules drop anything a
university cannot apply to. A small local model puts the closest first.

Each lead says what the call funds and which papers fit it. A citation check
holds every sentence to the record it cites.

</td>
</tr>
<tr>
<td>

### Industry leads from public signals

Perch looks for three kinds of signal: company papers that cite the
researcher's, NIH small-business awards in their topics, and company papers in
those topics. A company needs two kinds to be listed. No model writes these:
plain code counts the signals and shows the records behind each.

Every industry lead is labelled as inferred, not as verified interest.

</td>
<td><img src="docs/tour/industry.webp" alt="Switching Routes to Industry, then a company lead's signals and records." width="420"></td>
</tr>
<tr>
<td><img src="docs/tour/handoff.webp" alt="Keeping two grants, comparing them side by side, and drafting an email to Research Development." width="420"></td>
<td>

### Compare, then hand off

Keep the leads worth a closer look, and compare them side by side: money, close
date, activity code and evidence, each copied from its record.

Then draft an email to the Temple office for that route. A model writes only a
short opening. Code writes the list of leads, dates and amounts. You edit it and
send it yourself.

</td>
</tr>
<tr>
<td>

### Ask Scout a follow-up

"Why does the top lead fit?" or "only R21s that close by March". Scout, the
agent, answers by calling Perch's own nine tools, each shown as a card. It asks before every
step unless you let it run. It cannot browse, send anything or change a record.

Other agents can use the same tools through Perch's [MCP server](docs/mcp.md),
Claude Code included.

</td>
<td><img src="docs/tour/scout.webp" alt="Asking Scout why the top lead fits; its tool runs as a card and the answer cites the opportunity and the papers." width="420"></td>
</tr>
<tr>
<td><img src="docs/tour/private.webp" alt="Starting a private session, adding a CV, a draft proposal and unpublished work, and a brief whose explanations cite the private documents with a lock." width="420"></td>
<td>

### Private mode, for work not yet public

Add a CV, a draft proposal, a research direction or unpublished work. These
steer the search, and explanations can cite them. Every model runs on the
server, and the session lives in memory only. Exports leave private text out,
or mask it.

A canary test checks that no trace is left in files, logs or requests.
[More on private mode →](docs/private-mode.md)

</td>
</tr>
</table>

<sub>The private-mode clip uses an invented persona, labelled SYNTHETIC.</sub>

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/overview-dark.svg">
  <img alt="The whole system, top to bottom. Public sources feed plain-code fetchers and the store. A brief runs two routes: grants, with two small local models and eligibility rules, and industry leads, in plain code. A chat model writes the summary, the fit explanations and the hand-off draft, and Scout calls only Perch's own tools. Every model output passes the validator before the web app shows it. Private mode and the MCP server are other ways in." src="docs/architecture/overview-light.svg" width="720">
</picture>

- **Public records only:** OpenAlex, NIH RePORTER, NSF Award Search and Grants.gov. Each record is stored with its source, link and fetch time.
- **The pipeline is code:** fetching, eligibility, retrieval and ranking run the same way every time. The back-test measures this pipeline.
- **Models are bounded:** a model writes the profile summary, the fit explanations and the hand-off opening. Scout can call only allowlisted tools.
- **Every model output is checked:**
  - **Code check:** every id must be real, and every date or number must be in a cited record.
  - **Grounding check:** a second model checks each sentence against its source.
  - **On failure:** an output that fails is rewritten once, then withheld.
- **Any provider:** Ollama, any OpenAI-compatible server, or the Anthropic API, chosen per role in `.env`.

The brief step by step and the two-GPU layout are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## How well it works

Every number here was measured. Each is copied from [bench/results](bench/results/SUMMARY.md), with the keyword-only baseline beside the back-test.

| What | Result |
|---|---|
| **Back-test:** for 48 Temple NIH awards, did the announcement each was funded under rank in the top 10? Only papers from before the award count. | 7 of 48 with Perch's default setup, against 1 of 48 for keyword search alone |
| **Citation and grounding checks,** on 30 leads | Gemma 4 26B-A4B passed both on 28; Claude Sonnet on 24 |
| **Scout,** 20 scripted follow-ups | Claude Sonnet completed 20, with no wrong-tool calls; Gemma 4 26B-A4B completed 18 |
| **Cost of a 10-lead brief** | about $0.09 on Claude Sonnet; $0 on local models |
| **Private mode, live canary** | no trace in files, logs or model-server journals after full private briefs |

- **An upper bound, not an estimate:** each award's own funded abstract was added as a stand-in "draft proposal". It lifted the back-test from 7 to 16 of 48 in the top 10. A real draft is further from the award than its funded abstract.
- **General calls are hard:** for awards made under broad parent announcements, Perch puts 1 of 78 in the top 10.
- **Industry leads, judged once:** the agent that built Perch judged 14 leads: 8 good, 6 thin and 0 wrong. A person has not checked them yet.

## Learn more

| | |
|---|---|
| [Running Perch](docs/running.md) | Setup, the command line, keys and data sources |
| [Deploying the demo](docs/deploy.md) | Two GPUs, one `make demo`, the public URL and the fallback |
| [Private mode](docs/private-mode.md) | Turning it on, using it, and what it promises |
| [MCP server](docs/mcp.md) | Perch's tools in Claude Code or any MCP client |
| [Architecture](docs/ARCHITECTURE.md) | The system, a brief step by step, and the GPU layout |
| [Bench results](bench/results/SUMMARY.md) | The back-test, the checks, Scout and cost |
| [Sources](docs/SOURCES.md) | Every endpoint, field, limit and term, verified live |
| [Specification](docs/SPEC.md) and [plan](docs/PLAN.md) | The design, and how it was built session by session |
| [AI use](docs/AI_USE_LOG.md) | Every AI tool used to build Perch |

## About

Perch was built by Dakshitha (Temple University) for the Temple AI Build Challenge, Fall 2026,
with Claude Code as the coding agent. The README clips were filmed with the recording pipeline
from Dakshitha's [NextTex](https://github.com/dakshitha-a/NextTex).

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of
Health and Human Services. MIT licence; see [LICENSE](LICENSE).
