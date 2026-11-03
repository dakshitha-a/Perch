# Provider and SSO facts (Phase 1, tasks 2 and 3)

Fetched 2026-11-03. Every number below was copied from the page named next to it. Anything not found is marked UNVERIFIED.

## Part A. Model provider (Anthropic)

Sources:
- Models: https://platform.claude.com/docs/en/models/overview (docs.claude.com redirects here)
- Pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Rate limits: https://platform.claude.com/docs/en/api/rate-limits
- Prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching

### Models and prices, USD per million tokens

| Model id | Input | 5m cache write | 1h cache write | Cache read | Output |
|---|---|---|---|---|---|
| claude-haiku-5-5, prompts up to 100,000 tokens | 0.10 | 0.125 | 0.20 | 0.01 | 0.50 |
| claude-haiku-5-5, prompts over 100,000 tokens | 0.50 | 0.625 | 1 | 0.05 | 2.50 |
| claude-sonnet-5-5 | 2 | 2.50 | 4 | 0.10 | 10 |
| claude-opus-5-5 | 4 | 5 | 8 | 0.20 | 20 |
| claude-fable-5-1 | 10 | 12.50 | 20 | 0.25 | 50 |

- **Batch:** The pricing page lists Batch API requests at 50 percent off.
- **Context:** All four models list a 1M token context window and 128K max output.
- **Retirement:** The overview says not sooner than 28 September 2027 for Sonnet 5.5 and 7 October 2027 for Haiku 5.5.
- **Thinking:** Sonnet 5.5 and Haiku 5.5 use adaptive thinking. The overview says the Models API reports that Sonnet 5.5 rejects thinking disabled. Test this for the gate job.
- **Cache minimum:** Sonnet 5.5, Opus 5.5 and Haiku 5.5 cache prompts of 512 tokens or more.
- **Cache lifetime:** The default is 5 minutes and it refreshes free on each use. One hour costs more.
- **Rate-limit effect:** Cache reads do not count toward input tokens per minute on these models, so a cached system prompt raises real throughput.

### Rate limits by tier

| Tier | Model | Requests per min | Input tokens per min | Output tokens per min |
|---|---|---|---|---|
| Start | Haiku 5.5 | 4,000 | 2,000,000 | 400,000 |
| Start | Sonnet 5.5 | 4,000 | 2,000,000 | 400,000 |
| Start | Opus 5.5 | 4,000 | 2,000,000 | 400,000 |
| Build | Haiku 5.5 | 10,000 | 5,000,000 | 1,000,000 |
| Build | Sonnet 5.5 | 10,000 | 5,000,000 | 1,000,000 |
| Scale | Haiku 5.5 | 13,000 | 10,000,000 | 2,000,000 |
| Scale | Sonnet 5.5 | 13,000 | 10,000,000 | 2,000,000 |

| Tier | Monthly spend cap |
|---|---|
| Start | 500 USD |
| Build | 1,000 USD |
| Scale | 200,000 USD |

### How a tier is reached

- **Automatic placement:** The page says organizations are placed on a tier automatically from usage history and account standing.
- **New accounts:** New organizations may start in an Evaluation tier with limits below the standard ones. The page gives no numbers for it, so they are UNVERIFIED.
- **Deposit amounts:** The page states no deposit thresholds for moving tiers. UNVERIFIED.
- **Asking for more:** Use Request tier increase on the Console rate-limits page, or contact support.
- **Where to look:** The Console page platform.claude.com/usage/limits shows the organization's tier.
- **Spend cap behavior:** At the cap, calls return HTTP 429 with no retry-after header until the 1st of the next month, 00:00 UTC.
- **Own limit:** An organization can set a lower spend limit on the Billing page. Hitting it returns HTTP 400.

### Recommended default per job

The choice is a starting point. Phase 3 measurement confirms or changes it.

| Job | Default model | Input / output per MTok | Reason |
|---|---|---|---|
| Scope gate | claude-haiku-5-5 | 0.10 / 0.50 | A few output tokens, so the cheapest and fastest model fits. |
| Profile summary | claude-haiku-5-5 | 0.10 / 0.50 | Short summarising task; try Haiku first and move up only if the validator fails often. |
| Fit explanation | claude-sonnet-5-5 | 2 / 10 | About 10 to 20 calls per brief, and the cited wording must pass the validator. |
| Hand-off draft | claude-sonnet-5-5 | 2 / 10 | Written text a person will send on, so quality matters. |
| Cover-letter points | claude-sonnet-5-5 | 2 / 10 | Needs careful use of the CV and papers. |
| Scout agent loop | claude-sonnet-5-5 | 2 / 10 | Tool use over many turns; cache the system prompt and tool list. |

- **Opus and Fable:** Keep them out of the default path. Use them only where Phase 3 shows a measured gap.
- **Current code:** perch/llm/__init__.py carries a rate table for these three models. Its figures match the pricing page above for Sonnet 5.5 and Haiku 5.5 base input, output and cache. The Opus 5.5 cache read in that table is 0.20 and matches the page.
- **Measured spend:** bench/results/cost.csv shows 0.0123 USD per summary call and 0.0792 USD per ten-lead fit step on Sonnet 5.5. These are measured, not from the pricing page.

### An OpenAI-compatible alternative would need

- **Adapter:** perch/llm/openai_compat.py already exists, so a base URL, key and model name would be the main inputs.
- **Prices:** Each alternative needs its own price table in the cost code. None was fetched here, so all are UNVERIFIED.
- **Caching:** Cache behavior and prices differ by provider. UNVERIFIED.
- **Tool use:** The Scout loop needs function calling in that API. Check it per provider.
- **Citations check:** The validator is provider-independent, but regeneration rates may differ, so rerun the Phase 3 measurement.
- **Contract:** The deployment still needs a contracted provider and one consent at sign-up under the standing rules.

## Part B. Temple single sign-on

Sources:
- https://help.temple.edu/TDClient/277/Portal/Requests/ServiceDet?ID=10786 (fetched 2026-11-03)
- https://help.temple.edu/TDClient/277/Portal/Requests/ServiceCatalog/Category/1396/Authentication (fetched 2026-11-03)
- robots.txt at help.temple.edu allows /TDClient/. Requests were spaced one second apart.

### What the public page says

- **Service name:** Single Sign On (SSO), in the service catalog under Accounts and Access, then Authentication.
- **Protocols:** The page says secure login for Temple applications on and off the University network via SAML, OIDC and CAS.
- **Software named:** The page says support covers all integration requests for Shibboleth and Keycloak.
- **Goal:** Let every user with an AccessnetID account use the same credentials across multiple websites.
- **How to register:** The page has a Request Service button in the IT help portal. The form fields are behind that button and were not read. UNVERIFIED.
- **Who to contact:** The service sits in the Temple IT help portal. The page text fetched does not name an owning office. UNVERIFIED. Treat Temple IT Services as the likely route and confirm with Dakshitha.

### Left UNVERIFIED

- **Released attributes:** No public page fetched lists attributes or claims.
- **School, role, affiliation claims:** UNVERIFIED. Do not design around them until Temple IT confirms.
- **Which protocol Temple prefers:** Not stated.
- **Redirect or entity registration fields:** Not stated.
- **Lead time and approval steps:** Not stated.
- **Questions to send with the request:** Which protocol is preferred for a new web app, which attributes are released, whether a student and a faculty flag is available, and how long approval takes.
