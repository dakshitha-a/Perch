# What a real deployment at Temple needs

Every line below is taken from the repository's own record. Where the record does not settle a point, the line says UNVERIFIED. Nothing here is a promise, a price or a date.

## 1. Hardware and hosting

- **What runs today:** the test deploy runs a web process, a worker, Postgres with pgvector and Redis on one lab node.
- **The worker:** it loads the embedder, the reranker and MiniCheck on one GPU. Text models are not run there.
- **The text models:** the profile summary, fit reasons, hand-off drafts, cover-letter points, the scope gate and Scout call a cloud provider.
- **Public access:** the test deploy is reached through a public tunnel from the lab node. A real deployment would need a TLS reverse proxy in front of the web process.
- **Where it would run:** the record does not name a Temple host, so where Perch would run is UNVERIFIED.
- **A GPU host:** a worker host needs one NVIDIA GPU and the container toolkit, or a native worker as on the lab node. Reranking 100 candidates takes about 0.8 s on the GPU.
- **The no-GPU option:** the cloud-cpu profile runs with no GPU. Reranking 100 candidates takes about 53 s on 16 CPU cores, so that profile reranks 14 candidates instead.
- **Cost of the hosting:** the record holds no hosting or GPU running cost, so it is UNVERIFIED.
- **Backups:** a backup service dumps the data database and the key database each day and keeps 35 days. A restore test script exists. Whether a full restore was run end to end on the demo node is UNVERIFIED.
- **Monitoring:** there is a readiness check, a metrics endpoint that answers only on the local machine, and optional JSON logs. There is no alerting.
- **A failed daily job:** a failed purge shows only as a failed row in the job table. Nobody is notified.
- **Many hosts:** managed Postgres and Redis, several web processes and several workers are described in the runbook. A multi-host deployment has not been run, so every step of it is UNVERIFIED.
- **Load test:** the test used one GPU and a fake provider that sleeps for real call times. The worker drained 38 to 40 briefs a minute with 24 in flight and none failed.
- **The user target:** one web process met the 250-user target, with browse p95 between 132 and 190 ms. The 1,000-user target was not met and was dropped.
- **What the load test left out:** it made no real model calls. How many web processes would serve 1,000 users is UNVERIFIED.
- **Provider limits:** at the start tier the provider's output limit is above the worker's rate. Input-token limits and Temple's actual account tier are UNVERIFIED.

## 2. Sign-in

- **Today:** accounts use OpenID Connect with the authorisation code flow and PKCE. A Keycloak realm is the stand-in identity server.
- **The plan:** Temple single sign-on would replace the stand-in through the same OIDC interface. That swap has not been tried.
- **What Temple's public page says:** the IT help portal lists single sign-on over SAML, OIDC and CAS. It says support covers Shibboleth and Keycloak integrations.
- **Whether Temple will provide it:** UNVERIFIED. The registration form sits behind a request button and was not read.
- **Which office owns it:** the page names no owning office, so that is UNVERIFIED.
- **An OIDC client:** Temple IT would register Perch as a client. The code sends a client secret when one is set.
- **The issuer:** Perch needs the issuer address, which must start with https in production. It reads the provider's discovery document and its signing keys from there.
- **The redirect address:** Temple IT would register one redirect URI under Perch's public address. A post-logout redirect is used when the provider offers an end-session address.
- **Scopes:** the default is openid and profile. The scope list can be changed in the deployment settings.
- **Signing algorithms:** ID tokens must be signed with RS256 or ES256. Any other algorithm is refused.
- **Claims used:** the code requires the issuer, the audience, the expiry, the issued-at time, the nonce and a subject. It shows a display name taken from the name claim or else from the preferred username claim.
- **Claims not used:** no school, role, affiliation or student-or-faculty claim is read. The plan does not depend on one.
- **Open questions for Temple IT:** which protocol is preferred for a new web app, which attributes are released, whether a student and faculty flag exists, and how long approval takes.
- **Untested:** sign-in against any Temple provider, and the lead time and approval steps. All are UNVERIFIED.

## 3. Data access and API keys

- **OpenAlex:** the API meters usage in dollars a day. Without a key all callers on one address share a small daily amount. A free key gives a larger amount. A key is held for the test deploy. Which plan a production deployment needs is UNVERIFIED.
- **OpenAlex cursor paging:** it needs a key, so Perch pages by number instead. The data licence is CC0.
- **NIH RePORTER:** no key is needed. The page asks for no more than one request a second and large jobs outside working hours. Perch spaces requests one second apart.
- **NSF Award Search:** no key or rate limit is stated. Perch spaces requests one second apart on its own. Responses contain contact details, which the parser never reads.
- **Grants.gov:** no key is needed. Its terms say an app must display a not-endorsed notice. No numeric limit is published.
- **Grants.gov applicant category:** whether Temple applies as a public or a private institution was not verified. Eligibility accepts either, so a listing is not wrongly dropped.
- **SBIR.gov:** the API returned a forbidden response for every request, and its page says the APIs are under maintenance. Perch does not use it. Industry signals read NIH SBIR and STTR awards from RePORTER, so they cover NIH only.
- **SBIR.gov bulk file:** a monthly download exists, and its page states no terms of use. A table of Temple's STTR partners was built from it and is old.
- **NIH Guide:** no structured access was found, so Perch does not scrape it.
- **Temple pages:** 142 of 461 inventoried pages were read once, offline, one request a second, inside robots.txt. 316 more rows are listed from sitemaps only and have no page read.
- **Temple terms of use:** the record lists the terms of use of each school page as UNVERIFIED.
- **Temple permission:** whether Temple's offices agree to Perch showing their award pages is not recorded, so it is UNVERIFIED.
- **A student feed:** Temple's scholarship matching service has no public API or export that the record found. A Temple feed would need an agreement with its owning office, which is UNVERIFIED.
- **What is verified live:** the OpenAlex, NIH RePORTER, NSF and Grants.gov endpoints were each checked against a live response, with one saved fixture per source.
- **What is not verified live:** the SBIR.gov API, the NIH Guide and Temple's registration steps.
- **Refresh today:** only Grants.gov is refreshed on the deploy, by a script run on demand. Other sources are as of their last fetch.
- **The last refresh:** it found 26 new records, 59 changed and 1,412 unchanged. 47 posted records had closed.
- **A refresh plan:** the record has a nightly precache and daily purges, but no schedule for refetching public sources. A recurring data refresh is not built.
- **Temple dataset:** its error rate in the current version is not measured, so it is UNVERIFIED.

## 4. Models and cost

- **The provider:** model calls go to one cloud provider, through a provider layer that can use other providers. No vendor SDK is imported outside it.
- **The contract:** the standing rules call for a contracted provider. No Temple contract is recorded, so who signs it and its terms are UNVERIFIED.
- **Consent:** a user is asked once, at sign-up. The text says the CV and entries may go to the cloud model provider, that contact details are blanked first and that consent can be withdrawn.
- **Guests:** a guest never sends a CV. A guest brief runs on a public researcher id or on an invented sample student.
- **Budgets today:** by default a guest session has 0.10 USD a day, one address 0.30 USD and all guests 3.00 USD. A signed-in account has 0.50 USD. These are placeholders, not measured.
- **Demo Day settings:** the test deploy raises the limits for the event. Those values live in the deploy's own settings file.
- **The site cap:** a spend cap applies to the whole deployment, set by an environment variable, with a default of 100 USD. It is a development value.
- **Measured cost:** a researcher brief cost a mean of 0.0833 USD over five briefs on the current setup. Hand-offs and cover points are not in that number.
- **Student briefs:** the cost of a student brief on the current stack is not measured, so it is UNVERIFIED.
- **Rate tier:** the provider places an account on a tier from its usage. New accounts may start lower. The numbers for that start are UNVERIFIED.
- **What a production budget must decide:** who pays, a daily limit for each account, a limit for guests, a monthly cap for the site and what happens when a cap is reached.
- **When a cap is reached:** the list, dates, amounts and rule results still show, and only the written reasons pause.
- **Provider choice:** whether to use the same provider or another one is open. A different provider needs its own price table and a re-run of the grounding checks.

## 5. Privacy, security and compliance

- **User data at rest:** a user's CV, entries and briefs are encrypted per user with AES-256-GCM. The data keys sit in a separate key database.
- **The master key:** in the test deploy it comes from the environment. The production key service is not chosen, so it is UNVERIFIED.
- **Key rotation:** commands exist to rotate the master key and to re-encrypt a user's data.
- **What is never stored in plain text:** user text is kept out of logs, caches, the audit log and job payloads. A test plants a marker string and looks for it.
- **What leaves the deployment:** only text sent to the contracted model provider, after consent. Contact details are blanked first.
- **Retention:** accounts with no activity for 12 months are deleted by a daily job.
- **Delete my data:** the account page deletes the user's keys first, so rows become unreadable at once, and then clears the rows.
- **Backups after a delete:** the consent text promises that backups clear within 35 days. Backups are kept 35 days. A tombstone stops a restored backup from bringing a deleted key back.
- **The shred ledger:** a third copy of each tombstone is kept outside both databases. Putting it on an object store with object lock is UNVERIFIED and is not built.
- **An honest limit:** the web process and the worker both hold the key database credentials. The separate role guards against a data query bug, not against code inside a process.
- **Hand-offs:** Perch sends nothing. Every hand-off is a draft that a person sends.
- **Who must review it:** a Temple privacy and security review, UNVERIFIED which office, would need the encryption design, the consent text, the provider contract and the retention rules.
- **Student data:** whether education-record rules apply to a student's CV is UNVERIFIED, since the record names no law or office for it.
- **Research ethics:** the record names no research-ethics review. Whether one applies is UNVERIFIED.
- **An outside security test:** none has been done. Reviews so far were run by AI agents.

## 6. Product next steps

- **NIH eligibility parsing:** Perch reads applicant type, dates and a few title cues. Career-stage and limited-competition rules are not parsed, so such calls are shown as may be eligible.
- **Early-stage rule:** the CV rule cannot read clinical training or extensions, which NIH's definition counts.
- **Citizenship and residency:** the optional picks are compared only when a listing states a rule in one of a few closed phrases. Few records do, so most listings are not checked.
- **Researcher picks:** the picks are optional and apply only to a listing that quotes its own rule. A listing a user does not meet moves lower and is never dropped.
- **Industry leads:** they were judged once, by the agent that built them. A person has not checked them, and every lead says it is an inference.
- **Institution-level programs:** some federal leads are programs a centre applies for. Only four NIH activity codes are folded as centre grants.
- **Temple dataset coverage:** 142 of 461 pages were read. Many amounts and deadlines are not on the pages, and Perch shows them as not stated.
- **Name-only Temple listings:** these get no written reason. The card points to the award's page instead.
- **Match is not odds:** the Match number measures text similarity and is not the chance of funding.
- **Scout:** many open answers are flagged by the citation check, and run-to-run variance is large. Scout tuning is open.
- **Two shortlists:** saves on the browse lists and keeps in a brief are separate lists.
- **Same-day repeats:** asking for the same brief again on the same day returns the earlier build.
- **The office note:** it can take up to two minutes to appear.
- **Draft review:** a check of a student's letter against a record was evaluated and not built.

## 7. Evaluation

- **What the back-test measures:** whether a known NIH award's own opportunity appears in the top 10, using only papers published before the award started.
- **The sets:** 48 targeted awards and 78 parent-announcement awards. The keyword-only baseline is on every row.
- **Results:** for the 48 targeted awards the kept setup found 0.250 at rank 10 against 0.000 for keyword-only. For the 78 parent awards it was 0.051 against 0.000.
- **What it does not measure:** funding odds, NSF or other funders, students, industry leads and the quality of written reasons.
- **Tuned on the same data:** the setup was chosen on the 48 awards, so part of the gain is fitted to them.
- **Student results:** they use invented personas and sample scholarships. They show a mechanism and say nothing about real students.
- **Judged by builders:** industry leads and Scout's usefulness were judged by AI agents, and no user study has been done.
- **Grounding:** the check was run on 40 pairs from saved explanations, not human labels.
- **A real pilot:** it should measure whether a researcher or student would act on a lead they did not already know.
- **Pilot measures:** the share of listed leads that are eligible after a person checks them, the share of facts that are correct against the source page, and the time a brief saves.
- **Pilot measures, continued:** how often an office finds a hand-off draft usable, how many flagged sentences a reader finds wrong, and the cost per brief for each kind of user.
- **Pilot honesty:** it should report the keyword-only baseline beside every row and should not present a mechanism as a gain.
