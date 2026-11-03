# REUSE_MAP.md — Perch v1 rebuild, Phase 1 task 4

This map is the brief for Phases 5 to 8 of `docs/REBUILD_PLAN.md`. It covers `perch/private/`, `perch/api.py`, `perch/request_models.py`, `perch/scout/`, `perch/brief.py`, `perch/egress.py`, `perch/privacy.py`, `perch/jobs.py`, `perch/store/`, `perch/model_server.py`, `perch/remote_models.py` and `web/`. It also names the neighbouring files that the pairs touch: `perch/service.py`, `perch/export.py`, `perch/compare.py`, `perch/student.py`, `perch/offices.py`, `perch/mcp_server.py` and `perch/cli.py`.

## How to read this

- **Verdicts:** KEEP means the code stays as it is. MOVE means the code stays but changes file or package. MERGE means it folds into a shared function that serves both audiences. REWRITE means the job stays but the body is new. DELETE means the behaviour is gone.
- **Line ranges:** each range runs from a function's first line to the line before the next one, so the counts are exact for the range and approximate for how much of a function is really touched.
- **Phase column:** the phase of `docs/REBUILD_PLAN.md` that owns the change. Phase 2 and 3 items appear because later phases depend on them.
- **Shared names used below:** `audience` is `researcher` or `student`. `UserData` is the encrypted per-user store of CV and entries from Phase 5. `Lead` is the existing lead record.

## Module tables

### perch/private/

| Item | Lines | Verdict | Phase | Target and reason |
|---|---|---|---|---|
| `__init__.py` | 1-2 | DELETE | 6 | Package goes away. |
| `cv.py` CVFacts, sections, parse_cv, sponsor_match | 1-132 | MOVE | 5 | To `perch/user/cv.py`. Deterministic parse is kept as the plan says. Contact blanking is called before any model sees the text. |
| `inputs.py` header, InputError, PrivateDoc | 1-54 | MOVE | 5 | PrivateDoc becomes `UserDoc`. The `private:` id prefix is dropped. |
| `inputs.py` make_doc, clean, parse_bytes, docx_text, pdf_text, Upload | 55-145 | MOVE | 5 | To `perch/user/inputs.py`. Docx and PDF bomb guards are kept. |
| `threads.py` chunks, kind_of, add_threads, label | 1-80 | MOVE | 5 | To `perch/threads.py`. Used by the researcher brief for added direction text. |
| `student.py` achievements, achievement_docs | 1-60 | MOVE | 6 | Becomes part of the student profile source. |
| `student.py` record_text, as_opportunity, short_id, Scored | 61-92 | MERGE | 6 | Into one `RecordView` adapter, see pair 4. |
| `student.py` student_profile | 93-108 | MERGE | 6 | Into `profile_for(audience, ...)`, see pair 2. |
| `student.py` rank, choose, to_leads | 109-147 | MERGE | 6 | Into `build_leads`, see pair 1. |
| `student.py` judge_for, nih_records, samples | 148-171 | MOVE | 6 | To `perch/student.py`, where the eligibility rules live. Samples stay a separate list per rule 11. |
| `store.py` OverlayRepository, is_public | 1-107 | DELETE | 6 | The write overlay is private mode. Accounts write to Postgres. |
| `store.py` ReadOnlyCacheEmbedder | 108-150 | DELETE | 6 | Existed to keep private text out of the embed cache. Query vectors for user text are not cached in v1. |
| `warm.py` all | 1-131 | DELETE | 6 | Warm briefs are replaced by the nightly pre-cache job from Phase 3. |
| `session.py` header | 1-67 | DELETE | 6 | Imports and private constants. |
| `session.py` public_thread | 68-72 | MOVE | 5 | Goes with `perch/threads.py`. |
| `session.py` PrivateModels | 73-110 | DELETE | 6 | Local or Cloud model switching is gone. One provider config. |
| `session.py` PrivateSession fields | 111-137 | DELETE | 6 | In-memory session state is replaced by the account row and Redis session. |
| `session.py` PrivateSession cv, doc_refs | 138-144 | MOVE | 5 | To `UserData.cv()` and `UserData.refs()`. |
| `session.py` cloud_allowed, cloud_docs, chars, end, clear | 145-175 | DELETE | 6 | Consent is one account flag. End and clear become delete-my-data. |
| `session.py` make_masker, research_texts, make_research_masker, unmask | 176-201 | DELETE | 6 | Masks are removed. |
| `session.py` PrivateService create_private | 202-251 | MERGE | 6 | Into `BriefService.create(audience, ...)`. |
| `session.py` cancelled, _alone | 252-261 | DELETE | 6 | Replaced by job cancel in `PostgresRunner`. |
| `session.py` _run_researcher to _run_route_b, _works | 262-358 | MERGE | 6 | Near copy of `service.py:274-385`. One stage method per stage, reading the profile from `profile_for`. |
| `session.py` create_student, _student_docs | 359-385 | MERGE | 6 | Into `BriefService.create`. |
| `session.py` _run_student_profile, _student_route, _run_fellowships, _run_scholarships, _run_student_explanations | 386-481 | MERGE | 6 | Into the shared stage list, see pair 1. |
| `session.py` private_records | 482-485 | DELETE | 6 | Records come from `UserData`. |
| `session.py` TooManyFromAddress, PrivateSessions | 486-554 | DELETE | 6 | Per-address slots are replaced by per-account quotas. |
| `session.py` doc_ref, add_document | 555-573 | MOVE | 5 | To `UserData.add_doc`. |
| `routes.py` setup and constants | 1-80 | DELETE | 6 | Private flags and imports. |
| `routes.py` DocumentRequest | 81-87 | MOVE | 5 | To account routes. |
| `routes.py` PrivateBriefRequest, PrivateHandoffRequest | 88-92, 102-105 | MERGE | 6 | Into `BriefRequest` and `HandoffRequest` with `audience`. The mask field is dropped. |
| `routes.py` CloudRequest, TextRequest | 93-101, 106-109 | DELETE | 6 | Cloud switch and unmask request. |
| `routes.py` doc_json, private_record_json | 110-120 | MOVE | 5 | To account routes. |
| `routes.py` session_records | 121-134 | REWRITE | 5 | Reads from `UserData`. |
| `routes.py` docs_phrase, _read | 135-142 | DELETE | 6 | Cloud warning text and file reads. |
| `routes.py` _researcher_sample, _student_sample, sample | 143-163, 264-270 | MOVE | 5 | Guest sample. Guest mode stores nothing. |
| `routes.py` student_offices | 164-169 | MERGE | 6 | Into `offices.py`, see pair 13. |
| `routes.py` per_hour | 170-174 | DELETE | 5 | Quotas move to Redis. |
| `routes.py` submit | 189-215 | REWRITE | 5 | Becomes enqueue of a brief job. |
| `routes.py` cloud_info, take_cloud, private_info | 216-263 | DELETE | 6 | Cloud caps and private status. |
| `routes.py` session, open_session, get_session, end | 271-318 | DELETE | 5 | Replaced by `AuthProvider` login, logout and the session cookie. |
| `routes.py` set_cloud | 319-348 | DELETE | 6 | Local or Cloud choice. |
| `routes.py` add_doc, remove_doc | 349-381 | MOVE | 5 | To account routes: add, list and delete a CV or entry. |
| `routes.py` start_brief, start_student | 382-445 | MERGE | 6 | Into `POST /briefs` with `audience`. |
| `routes.py` throttle, brief_id | 446-457 | DELETE | 5 | Per-address throttle and session brief id. |
| `routes.py` get_brief, brief_json, set_status, get_record, compare | 458-525 | MERGE | 6 | Into the stored-brief routes in `api.py`. |
| `routes.py` student_note | 502-517 | MERGE | 6 | Into the shared hand-off route, see pair 7. |
| `routes.py` masker_for, export_masker_for, unmask | 526-547, 601-609 | DELETE | 6 | Masks are removed. |
| `routes.py` handoff | 548-574 | MERGE | 6 | Into the shared hand-off route. |
| `routes.py` export_j, export_md, export_html | 575-600 | MERGE | 6 | Into the stored-brief export routes. |
| `routes.py` hub, ask_allowed, scout_start, scout_get, scout_act | 610-671 | MERGE | 8 | Into the stored-brief Scout routes. |

### perch/api.py, request_models.py, jobs.py

| Item | Lines | Verdict | Phase | Target and reason |
|---|---|---|---|---|
| `api.py` header, draft_json | 1-94 | KEEP | 6 | Draft JSON is shared. |
| `api.py` BriefRequest | 95-99 | REWRITE | 6 | Adds `audience`. Replaces the private twin. |
| `api.py` WebFiles | 100-109 | KEEP | 7 | Static files. |
| `api.py` record_json | 110-113 | KEEP | 6 | Shared card JSON. |
| `api.py` lead_json, student_json, route_b_json, paper_json | 114-169 | MERGE | 6 | Into one `lead_json(lead, record)` keyed by `record.kind`, see pair 11. |
| `api.py` RateLimiter | 170-192 | REWRITE | 5 | Redis counters per account. The daily budget is shown to the user. |
| `api.py` BodyLimit, SecurityHeaders, Crashed | 193-312 | KEEP | 5 | Plan keeps CSP and body limits. Crashed must not log user text. |
| `api.py` client_key | 313-329 | REWRITE | 5 | Keyed by account id, with the address only for guests. |
| `api.py` dependencies, up | 330-352 | KEEP | 10 | Health checks. |
| `api.py` create_app, stored_only, invalid, health | 353-400 | REWRITE | 5 | Adds auth dependency, CSRF check and the job queue. |
| `api.py` resolve | 401-428 | KEEP | 5 | Author lookup, used to link an account to an OpenAlex id. |
| `api.py` create_brief, load, get_brief, brief_view | 429-483 | MERGE | 6 | The only brief routes after Phase 6. `brief_view` serves both audiences. |
| `api.py` set_status, keep, dismiss, restore | 484-501 | KEEP | 6 | Saved items per account. |
| `api.py` export, export_json, export_blocks, export_md, export_html | 502-605 | MERGE | 6 | Into `brief_blocks(audience, ...)`, see pair 10. |
| `api.py` compare_view | 606-614 | MERGE | 6 | Into `compare_rows`, see pair 9. |
| `api.py` handoff | 615-629 | MERGE | 6 | Into `draft_handoff`, see pair 7. |
| `api.py` get_record | 630-645 | KEEP | 6 | Gains the user's own rows via `UserData`. |
| `api.py` ask_allowed, scout_start, entry, scout_get, scout_act | 646-696 | REWRITE | 8 | Scout turns become jobs with a daily account budget. |
| `request_models.py` ScoutRequest, HandoffRequest | 1-21 | KEEP | 6 | Mask field dropped. |
| `request_models.py` BriefOptions | 22-40 | REWRITE | 6 | Adds `audience`. The `context` dict stops carrying private fields. |
| `jobs.py` JobRunner interface | 1-24 | REWRITE | 2 | `submit(job_id, fn)` takes a closure, which a worker in another process cannot receive. New shape is `submit(job_id, kind, payload)`. |
| `jobs.py` InProcessRunner | 25-47 | KEEP | 2 | Kept for dev and tests, behind the new shape. |
| `jobs.py` InlineRunner | 48-52 | KEEP | 2 | Tests. |

### perch/scout/

| Item | Lines | Verdict | Phase | Target and reason |
|---|---|---|---|---|
| `__init__.py` make_scout, brief_note | 1-114 | MERGE | 8 | `brief_note` here and `student_brief_note` in `student_tools.py:512` become one `brief_note(audience, ...)`. |
| `hub.py` Entry, ScoutHub, Busy | 1-88 | REWRITE | 8 | Sessions held in memory become job rows. A restart no longer forgets them. |
| `hub.py` view, draft_of, points_of, record_ids | 89-138 | KEEP | 8 | View shaping is audience-neutral. |
| `log.py` all | 1-75 | MOVE | 8 | The JSONL log moves to the Postgres audit table. It logs digests, never user text. |
| `loop.py` header, prompt constants | 1-94 | REWRITE | 8 | New system prompt states the scope and the grounding contract. |
| `loop.py` regex steering: NUDGE to TOP_Q_RE, question_scope | 95-223 | DELETE | 8 | Fixed questions move to code. The scope gate replaces `question_scope`. |
| `loop.py` ScoutBudget | 224-230 | REWRITE | 8 | Per-account daily budget. |
| `loop.py` Card, Session | 231-282 | KEEP | 8 | The visible tool-call card stays. |
| `loop.py` cited, strip_tool_cites, stated_numbers, scrub | 283-307, 316-375 | KEEP | 8 | Layer 1 helpers, rule 3. |
| `loop.py` mask_labels | 308-315 | DELETE | 6 | Mask labels. |
| `loop.py` Scout init, start, open, ask, _start_over, stop, advance | 376-515 | REWRITE | 8 | Native provider tool use instead of the structured step schema. |
| `loop.py` _next, _structured | 516-546 | REWRITE | 8 | Native tool use. |
| `loop.py` _nudge, _with_facts, _named, _answer_repeat, _not_run | 547-647 | DELETE | 8 | Steering for the old fixed set. |
| `loop.py` _execute | 648-701 | KEEP | 8 | Allowlisted tool run. |
| `loop.py` _steer, _this_question, _reply_with_results | 702-749 | DELETE | 8 | Steering. |
| `loop.py` _over_budget | 750-759 | REWRITE | 8 | Account quota. |
| `loop.py` _stop, _drafted, _step_ids, _validate, _finish, _log_tool, _log_answer | 760-879 | KEEP | 8 | Citation validator path, regenerate once, flag. |
| `loop.py` stray_text, floor_as_ceiling, floor_only_largest, expiry_as_deadline, crossed_rows, further_first, brief_claims | 880-1087 | MOVE | 8 | To `perch/scout/checks.py`. They check answers against record fields. They must be re-pointed at the new read-tool result shapes. |
| `loop.py` carry_filters, _iso, undated, month_dates, months_line, list_ids, last_list_line | 1088-1166 | DELETE | 8 | Filter steering for the old fixed set. |
| `loop.py` compact | 1167-1207 | REWRITE | 8 | Context compaction against native tool messages. |
| `loop.py` _brief_of, _canonical, render | 1208-1231 | KEEP | 8 | Helpers. |
| `loop.py` structured_answer | 1232-1238 | DELETE | 8 | Only the structured step used it. |
| `loop.py` points_line, summarise | 1239-1299 | REWRITE | 8 | Tool result summaries for the new tools. |
| `tools.py` imports, ToolError, short_id | 1-57 | KEEP | 8 | |
| `tools.py` ScoutContext | 58-92 | REWRITE | 8 | Holds the account, audience and `UserData`. No private flag. |
| `tools.py` _private, _session_docs | 93-103 | DELETE | 8 | Private mode. |
| `tools.py` _researcher, _profile | 104-142 | MERGE | 8 | Into `profile_for(audience, ...)`, see pair 2. |
| `tools.py` fit_sentence, second_person | 143-185 | MOVE | 6 | To `perch/present.py`. Pair 10 has the four copies of the "you" rewrite. |
| `tools.py` _brief_leads | 186-194 | MERGE | 8 | Into `read_brief`. |
| `tools.py` resolve_author, build_profile, list_awards | 195-258 | MERGE | 8 | Into `read_brief` (profile part). |
| `tools.py` search_opportunities, _lead_row, _sort, _reasons, _search_brief, _route_b_leads | 259-438 | MERGE | 8 | Into `search_records`, see pair 5. |
| `tools.py` _stage_done, get_org_signals | 439-486 | MERGE | 8 | Into `read_brief` (industry signals), researcher only. |
| `tools.py` explain_fit, _opportunity, get_record | 487-553 | MERGE | 8 | Into `read_record`. |
| `tools.py` _items, _why, _evidence, compare | 554-663 | MOVE | 8 | Fixed question. Becomes the shared `compare_rows` button, see pair 9. |
| `tools.py` draft_handoff, _target | 664-735 | MOVE | 8 | Fixed action. Becomes the shared `draft_handoff`, see pair 7. |
| `tools.py` _awards, split_docs, source_title, cover_result, cover_points | 736-823 | MOVE | 8 | To `perch/cover.py`, see pair 8. Becomes a button. Scout may call it as a read-only helper only if it writes nothing. |
| `tools.py` _obj, TOOLS registry, _fixed | 824-948 | REWRITE | 8 | Five broad read tools. |
| `tools.py` check_arguments | 949-969 | KEEP | 8 | Argument checks on the allowlist. |
| `student_tools.py` imports, _brief, _record, record_of, facts_of, _row, _find | 1-111 | MERGE | 8 | Into the shared lead row, see pair 5. |
| `student_tools.py` search_options | 112-202 | MERGE | 8 | Into `search_records`. |
| `student_tools.py` search_words, apart, is_sample_id, mixed_lists | 203-277 | MOVE | 8 | To `perch/scout/checks.py`. Rule 11 needs the sample and public lists kept apart. |
| `student_tools.py` _facts, check_option, explain_verdict | 278-310 | MERGE | 8 | Into `read_record`, which returns the verdict beside the fields. |
| `student_tools.py` read_cv | 311-320 | MERGE | 8 | Into `read_user`. |
| `student_tools.py` compare_options | 321-333 | MOVE | 8 | Same code-written button as compare. |
| `student_tools.py` draft_note, mine, _due, write_note | 334-391 | MERGE | 8 | Into `draft_handoff`, see pair 7. |
| `student_tools.py` cover_points | 392-440 | MERGE | 8 | Into `perch/cover.py`, see pair 8. |
| `student_tools.py` registry and student_brief_note | 441-531 | REWRITE | 8 | Registry dissolves into the five tools. `student_brief_note` merges with `brief_note`. |

### perch/brief.py, egress.py, privacy.py, store/, model_server.py, remote_models.py

| Item | Lines | Verdict | Phase | Target and reason |
|---|---|---|---|---|
| `brief.py` RouteABrief, route_a | 1-84 | KEEP | 6 | The researcher half of `build_leads`. Takes the index and reranker as arguments, so it already fits pgvector and the CPU reranker. |
| `egress.py` header, constants | 1-48 | DELETE | 6 | |
| `egress.py` blank_contacts | 49-56 | MOVE | 5 | To `perch/llm/contacts.py`. Plan keeps contact blanking, called inside the provider wrapper. |
| `egress.py` is_private_id, is_private, public_only, uses_private | 57-72 | DELETE | 6 | The `private:` id scheme is gone. |
| `egress.py` Masker, ResearchMasker | 73-198 | DELETE | 6 | Masks removed. |
| `egress.py` release_cv_line, release_model, release_thread, release | 199-238 | DELETE | 6 | Egress filter removed. The release rules for CV lines become the single rule "blank contacts, then send". |
| `privacy.py` PrivateSettings and its checks | 1-121 | DELETE | 6 | |
| `privacy.py` consent_warning | 122-144 | REWRITE | 5 | One consent at sign-up naming the provider. |
| `privacy.py` http_urls, refuse_if_not_local, refuse_endpoints, harden_process | 145-186 | DELETE | 6 | Local-only enforcement is gone. Rule 6 still keeps vendor SDKs inside `perch/llm/`. |
| `store/base.py` Repository, VectorIndex | 1-68 | KEEP | 2 | Gains list filters for Temple-only and school, and user-scoped reads. |
| `store/sqlite.py` | 1-79 | KEEP | 2 | Test store behind the same interface. |
| `store/lance.py` | 1-66 | DELETE | 2 | Replaced by pgvector. |
| `store/__init__.py` | 0 | KEEP | 2 | Empty. |
| `model_server.py` | 1-102 | DELETE | 3 | Workers load CPU models directly. |
| `remote_models.py` | 1-60 | DELETE | 3 | Same. |

### web/

| Item | Lines | Verdict | Phase | Target and reason |
|---|---|---|---|---|
| `api.js` call, liveApi | 1-45 | KEEP | 7 | Adds the CSRF header. |
| `api.js` replayApi | 46-169 | KEEP | 7 | Static replay for the fallback and guest demo. Replay data must carry the new fields. |
| `api.js` tabStore, privateApi | 170-265 | DELETE | 6 | Session token in browser tab storage. Replaced by cookie sign-in and an `accountApi`. |
| `app.js` state, constants, announce, screen | 1-88 | REWRITE | 7 | State `S` gains account, side and filters. |
| `app.js` route, go, goReplace, keepFocus, seg | 89-187 | REWRITE | 7 | Student-first routes and a side switch. |
| `app.js` renderFind, heroArt | 188-231, 272-293 | REWRITE | 7 | Student-first landing. |
| `app.js` startStudent, pasted, nudgeBox | 232-271 | DELETE | 6 | The paste nudge opened a private session. |
| `app.js` search, CTX_FIELDS to AID_OK, atTemple | 294-358 | KEEP | 7 | Author lookup. |
| `app.js` renderPick, once, candidateCard | 359-437 | KEEP | 7 | Researcher identity step. |
| `app.js` contextPanel | 438-497 | REWRITE | 7 | Becomes the stored CV and entries panel for both sides. |
| `app.js` sampleStatus, drawSampleStatus, fillResearcherSample, pickFile | 498-539 | REWRITE | 7 | Guest sample and file add on the account page. |
| `app.js` build | 540-587 | REWRITE | 7 | One build call with `audience`. |
| `app.js` cloudInfo, docsChanged, dialog, openModels | 588-606, 625-702 | DELETE | 6 | Local or Cloud dialog. |
| `app.js` drawSwitch | 607-624 | REWRITE | 7 | Becomes the researcher or student side switch. |
| `app.js` showError | 703-710 | KEEP | 7 | |
| `app.js` SIDES, sideGuard, sessionEnded, endSession, sessionExpired, resetSession, setCloud | 711-801 | DELETE | 6 | One side per session is replaced by one account, either side. |
| `app.js` stopPolling, openBrief, poll, renderMissing, helpers | 802-853 | KEEP | 7 | |
| `app.js` renderBrief, holdsDocs, exportMenu, tabs, updateBrief | 854-962 | KEEP | 7 | `holdsDocs` is dropped. |
| `app.js` renderProgress to renderPanel | 963-1089 | REWRITE | 7 | New stage names and streaming text. |
| `app.js` warnings, KIND_SHORT, leadTitle, drawRail, emptyRail, railFade, switchRoute | 1090-1199 | KEEP | 7 | |
| `app.js` renderStudentPanel | 1200-1218 | MERGE | 7 | Into `renderRoutes`, see pair 13. |
| `app.js` keptIds, drawCompare, drawScout, recordLabel | 1219-1263 | KEEP | 7 | |
| `app.js` renderProfile and sections | 1264-1471 | KEEP | 7 | `youSaidSection` and `threadsNote` are reworded. |
| `app.js` skeleton, sortedLeads, routeSwitch, SORTS, sortSwitch, updateSwitch, panelFocus | 1472-1526 | MERGE | 7 | Duplicate sort switch in `student.js:219`. One shared control. |
| `app.js` renderRoutes | 1527-1610 | MERGE | 7 | With `studentRoutes`. Adds the Temple-only toggle and school tags. |
| `app.js` constants, passes, drawFilters | 1611-1645 | REWRITE | 7 | Filter bar gains toggle and tags. |
| `app.js` renderIndustry, sigRec, orgCard, otherNames | 1646-1773 | KEEP | 7 | Researcher only, no student twin. |
| `app.js` syncList, cssId, isPending | 1774-1804 | KEEP | 7 | |
| `app.js` leadCard, cardHead, leadNotes | 1805-1887 | MERGE | 7 | With `student.js` card, see pair 13. |
| `app.js` explanationBlock | 1888-1925 | MERGE | 7 | With `fitReason`/`plainExplanation` in `student.js`. |
| `app.js` docsOnly, modelTag, modelWord | 1926-1941 | DELETE | 6 | Local or Cloud tags. |
| `app.js` ownIds, inferenceBox, eligibilityRows, renderSegs, paperRef, cite | 1942-2010 | KEEP | 7 | |
| `app.js` sampleSteered, farClose, today, setLead, wait | 2011-2063 | KEEP | 7 | |
| `app.js` swapRecord to recordView, fetched | 2064-2431 | KEEP | 7 | Evidence panel. Adds the school and Temple-funded rows. |
| `compare.js` | 1-131 | KEEP | 7 | The shared compare view. `studentCompare` merges into it, see pair 9. |
| `dom.js` | 1-89 | KEEP | 7 | |
| `format.js` | 1-264 | KEEP | 7 | `docId` and the `private:` token pattern at 139 and 180 are cleaned. |
| `handoff.js` | 1-138 | KEEP | 7 | The shared hand-off screen. The student note renders through it, see pair 7. |
| `help.js` | 1-316 | REWRITE | 7 | The privacy and Local or Cloud text is wrong in v1. Every claim is rechecked against code. |
| `mode.js` | 1-86 | DELETE | 6 | Private session state, `crossesSide`, the paste detector. |
| `owl.js` | 1-99 | KEEP | 7 | |
| `private.js` renderPrivate | 44-177 | REWRITE | 7 | The document add screen becomes the account's CV and entries page. |
| `private.js` the rest | 1-43, 178-244 | DELETE | 6 | Status bar, mask toggle, lock label, statement. |
| `scout.js` TOOLS, CAN_USE, ARGS, SCOPES, STATUS, EXAMPLES, ROUTES, SORTS, argList, card | 1-48, 201-248 | REWRITE | 8 | Tool names and argument chips change with the five tools. |
| `scout.js` renderScout, welcome, fitChat, pinChat, reset, exchange, readAs | 49-200 | KEEP | 8 | `welcome` gets the fixed-question buttons. |
| `scout.js` draftBlock, pointsBlock, pointsText, pointCite | 249-330 | MOVE | 7 | To the hand-off and cover screens, since drafts and cover points become buttons. |
| `scout.js` answer, newConversation, withCites, inline, citeBtn, leadLabel, askForm, send, stop, poll | 331-510 | KEEP | 8 | Adds the daily budget line and the "General advice" label. |
| `student.js` constants, verdictChip, resetStudent, keptWords, isStudent | 1-53 | KEEP | 7 | Verdict chip becomes shared. |
| `student.js` renderStudentStart | 54-191 | MERGE | 7 | Into the one onboarding flow, see pair 13. |
| `student.js` studentProfile | 192-218 | MERGE | 7 | With `renderProfile`. |
| `student.js` SORT, sortLeads, sortSwitch | 219-237 | MERGE | 7 | With `app.js` sort switch. |
| `student.js` studentRoutes | 238-285 | MERGE | 7 | With `renderRoutes`. |
| `student.js` matchPill to card, fitReason, you, plainExplanation, amountText | 286-409 | MERGE | 7 | With `leadCard` and `explanationBlock`. |
| `student.js` studentCompare, note | 410-506 | MERGE | 7 | Into `compare.js` and `handoff.js`. |

## Researcher/student pairs

Each pair is two code paths that do the same job. For all of them the only legitimate differences are the record type, the eligibility rules, the profile source and the receiving offices.

### Pair 1: the brief pipeline

- **Paths:** `perch/service.py` stages `_run_researcher` to `_run_explanations` (274-435) with `perch/brief.py:41`, against `perch/private/session.py` lines 262-481 and `perch/private/student.py` rank, choose, to_leads.
- **What differs:** the profile source and the record type. The stage names also differ, so `service.py:222` carries a student special case.
- **Shared function:** `build_leads(audience, profile, repo, index, embedder, reranker, rules, as_of, top) -> list[Lead]`. The stage runner becomes `BriefService.run(brief_id)` with a stage list picked by `audience`.
- **Note:** the researcher stage `_run_route_a` stays inside `build_leads` as the grant strategy. Industry leads (route B) have no student twin and stay researcher only.

### Pair 2: the profile source

- **Paths:** `service._run_profile` (319), `tools._profile` (122) and `tools._researcher` (104), against `student.student_profile` (93) and `session._run_student_profile` (386).
- **What differs:** OpenAlex works for a researcher, CV plus achievements for a student.
- **Shared function:** `profile_for(audience, account, repo, user_data) -> Profile`. It also covers a graduate student who has both.

### Pair 3: the eligibility verdict

- **Paths:** `perch/eligibility.py` for opportunities, against `perch/student.py` (309 lines) and `student.judge_for` (148).
- **What differs:** the rules.
- **Shared function:** one interface `Rule.check(facts, record, as_of) -> Verdict`, two rule sets. `Verdict` is one type. The card, export and compare read the same verdict.

### Pair 4: the record adapter

- **Paths:** `student.as_opportunity` (71) and `record_text` (62) turn a `Scholarship` into an `Opportunity` so the researcher pipeline can rank it.
- **Shared function:** `RecordView(record) -> text, title, dates, amount, link, source`, so rank code never branches on the type.

### Pair 5: Scout tools

- **Paths:** `scout/tools.py` (ten tools) against `scout/student_tools.py` (eight tools).
- **What differs:** record type and the extra industry tools.
- **Shared functions:** `search_records(ctx, kind, query, filters) -> rows`, `read_record(ctx, id) -> record, verdict, evidence`, `read_brief(ctx) -> profile, leads, stage state`, `read_user(ctx, part) -> CV or entry parts`, `read_saved(ctx) -> kept and dismissed`. The `kind` argument picks `Opportunity` or `Scholarship`.

### Pair 6: Scout context and brief note

- **Paths:** `scout/__init__.brief_note` (71) against `student_tools.student_brief_note` (512).
- **Shared function:** `brief_note(ctx, brief, leads) -> str`.

### Pair 7: hand-offs

- **Paths:** `service.handoff` (164) with `skills/handoff.py` and `scout/tools.draft_handoff` (664), against `student_tools.write_note` (369) with `routes.student_note` (502).
- **What differs:** the receiving offices, and today the researcher opening is model text while the student note is code only.
- **Shared function:** `draft_handoff(audience, brief, office_key, leads, user_data, provider=None) -> Draft`. Code writes the body from record fields for both. The model opening is optional and goes through the same validator.
- **Offices:** one table in `perch/offices.py`, keyed by audience. `routes.student_offices` (164) and `compare.js compareOffices` (129) read it.

### Pair 8: cover points

- **Paths:** `tools.cover_points` (798) and `cover_result` (771), against `student_tools.cover_points` (392).
- **Shared function:** `cover_points(ctx, record_id) -> CoverPoints`, in `perch/cover.py`, with the skill in `perch/skills/cover.py` unchanged.

### Pair 9: compare

- **Paths:** `perch/compare.py` (rows for route A and B only), `tools.compare` (604), `student_tools.compare_options` (321) and `web/student.js studentCompare` (412), against `web/compare.js`.
- **What differs:** the columns.
- **Shared function:** `compare_rows(audience, leads, repo, as_of) -> Rows` on the server, rendered by `compare.js`. The student comparison stops living in the browser.

### Pair 10: exports and the "you" rewrite

- **Paths:** `export.blocks` (232) against `export.student_blocks` (400) with `_student_option` (510).
- **Shared function:** `brief_blocks(audience, brief, leads, records, user_data) -> list[Block]`. The markdown and HTML renderers are already shared.
- **Four copies of one rewrite:** `export.you` (503), `tools.second_person` (163), `web/student.js you` (385) and `web/format.js secondPerson` (162). They become one Python function, `perch/present.second_person`, and one JS function.

### Pair 11: API JSON

- **Paths:** `api.lead_json` (114), `student_json` (119), `route_b_json` (139).
- **Shared function:** `lead_json(lead, repo) -> dict`, dispatching on `record.kind`.

### Pair 12: routes

- **Paths:** `api.py` stored-brief routes against `private/routes.py` session routes.
- **Shared function:** one set of routes under `/briefs`, with the account taken from the session cookie.

### Pair 13: web screens

- **Paths:** `student.js` against `app.js`: start flow with `renderFind`, `renderPick` and `build`; `studentRoutes` with `renderRoutes`; `card` with `leadCard`; `studentProfile` with `renderProfile`; `sortSwitch` twice.
- **Shared functions:** `renderStart(audience)`, `renderRoutes(audience)`, `leadCard(lead, audience)`, `renderProfile(audience)`, `sortSwitch()`.

### Pair 14: the brief service classes

- **Paths:** `BriefService` (`service.py:111`) against `PrivateService(BriefService)` (`session.py:202`), which overrides almost every stage.
- **Shared function:** one `BriefService` that reads from a `UserData` scope. The subclass is deleted.

### Pair 15: Scout UI

- **Paths:** `scout.js` `EXAMPLES` (50) against `STUDENT_EXAMPLES` (32), and a tool-name table per audience.
- **Shared function:** `examples(audience)` and one tool table.

## Tests affected

Line counts are from the working tree. "Priv" is the count of lines that mention private, egress, overlay, warm, mask, session, canary or similar, so it is a hint and not an exact measure.

### Drop (they test deleted behaviour)

| File | Lines | Priv | Note |
|---|---|---|---|
| `tests/test_egress.py` | 117 | 42 | Port only the contact-blanking cases to a test of `perch/llm/contacts.py`. |
| `tests/test_privacy.py` | 70 | 14 | |
| `tests/test_model_server.py` | 61 | 2 | |
| `tests/test_lance.py` | 41 | 4 | Replaced by a pgvector index test. |
| `tests/test_private.py` | 1155 | 342 | Mostly drop. Port the cases listed below. |

### Port (they test kept behaviour that moves)

| File | Lines | What to port |
|---|---|---|
| `tests/test_private.py` | 1155 | Port to new paths: CV parse, input parse from bytes, docx and PDF bomb and failure cases, threads sharing, exports give the summary and threads in full, hand-offs, the 304 poll test, "a failed step reads in plain words". Replace the canary case with the user-data leakage check. |
| `tests/test_student.py` | 508 | Imports fixtures from `test_private` at line 21. Move the fixtures to `tests/conftest.py`, then port the rule and brief cases. |
| `tests/test_export_full.py` | 234 | Keep full-export cases, drop the masking round trips. Its imports from `test_private` at line 12 must move. |
| `tests/test_export.py` | 253 | Remove the Masker cases around lines 55-57. |
| `tests/test_qa4.py`, `tests/test_qa5.py` | 404, 421 | Edit the private id cases (`private:proposal`) and the student export case at `test_qa4.py:178`. |
| `tests/test_web.py` | 512 | Drop private session tests (149-229). Keep geometry and structure tests. |
| `tests/test_api.py` | 538 | Drop the `/private/*` body-limit cases at 386-391 and the routes import at 443. Port them to the new account routes. |
| `tests/test_scout.py` | 1042 | Rewrite for the new loop. Keep the layer-1 and scope cases. Drop the private Scout cases at 265-274. |
| `tests/test_skills.py` | 389 | Edit the private researcher signature case at 175. |
| `tests/test_store.py` | 31 | Run against both SQLite and Postgres. |
| `tests/test_cli.py`, `tests/test_mcp.py` | 163, 87 | Drop the `--private` flag cases. |
| `tests/test_public_hygiene.py` | 73 | Keep. Award titles are an exception per Phase 0. |

### Keep as is

- **Pipeline and sources:** `test_eligibility.py`, `test_scholarships.py`, `test_score.py`, `test_rerank.py`, `test_retrieve.py`, `test_route_b.py`, `test_route_b_sources.py`, `test_validate.py`, `test_embed.py`, `test_profile.py`, the source tests, `test_compare.py`, `test_backtest.py`, `test_llm.py`, `test_systemone.py`, `test_decide.py`, `test_audit.py`, `test_package.py`, `test_tracker.py`.

## Order of work

### Phase 2 prerequisites (not in 5 to 8)

- **Data and jobs:** `store/` gets the Postgres implementation and `lance.py` is dropped. `jobs.py` gets the serialisable job shape, which changes the signature all callers use today.

### Phase 3

- **CPU models:** delete `model_server.py` and `remote_models.py`. The two edits in `service.default_models` (467-493) go with them.

### Phase 5: sign-in, accounts and user data

- **Move:** `cv.py`, `inputs.py`, `threads.py`, `session.add_document`, `doc_ref`, `public_thread`.
- **Rewrite:** `RateLimiter`, `client_key`, `create_app`, `submit`, `session_records`, `consent_warning`.
- **Move:** `blank_contacts` into `perch/llm/`.
- **Delete:** the session routes, `per_hour`, `throttle`.
- **New:** `AuthProvider`, `UserData`, account routes, delete-my-data.

### Phase 6: remove private mode

- **Merge:** `PrivateService` into `BriefService`, `private/student.py` into the shared `build_leads`, `private/routes.py` into `api.py`, `lead_json` trio, `export.student_blocks` into `brief_blocks`, `compare_rows`, `draft_handoff`.
- **Delete:** `store.py`, `warm.py`, `egress.py`, `privacy.py`, `PrivateModels`, `PrivateSessions`, masks, the cloud dialog code in the web files, `mode.js`, `private.js` outside `renderPrivate`, and the `--private` options in `cli.py` and `mcp_server.py`.
- **New:** the user-data leakage check, which must fail first.

### Phase 7: student-first UI

- **Merge:** `student.js` into `app.js` screens, `compare.js` and `handoff.js`. The sort switch becomes one control.
- **Rewrite:** the landing, filters, progress, `contextPanel`, `help.js`, `private.js renderPrivate`.
- **Keep:** the profile sections, the evidence panel, industry, `dom.js`, `format.js`, `owl.js`.

### Phase 8: Scout

- **Rewrite:** `loop.py`, `hub.py`, the tool registry, `ScoutContext`, `scout.js` tool tables, `api.py` Scout routes.
- **Merge:** the two tool modules into five read tools, and `brief_note`.
- **Move:** answer checks to `checks.py`, `cover_points` and `draft_handoff` to code actions, `log.py` to the audit table.
- **Delete:** the steering regexes and `question_scope`.


## Totals

- **Method:** summed from the Lines column of the module tables above. Single-line ranges count as one line.

| Verdict | Lines |
|---|---|
| KEEP | 3656 |
| MOVE | 1325 |
| MERGE | 2479 |
| REWRITE | 2103 |
| DELETE | 2370 |
| Total | 11933 |

| Phase | Lines touched or kept |
|---|---|
| 10 | 23 |
| 2 | 265 |
| 3 | 162 |
| 5 | 840 |
| 6 | 2902 |
| 7 | 4125 |
| 8 | 3616 |
