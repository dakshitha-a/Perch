# Perch web app — interaction audit and UI design (S7)

Written before the build, then checked against it in the adversarial review. Screens covered here: Find, Profile, Routes and the evidence panel. Compare and Hand off are S12.

## 1. Who uses it, and in what state

- **Principal investigator (primary).** A busy, expert reader who is not a funding specialist. Often on a phone between meetings, or scanning a QR code at the demo. Reads titles and dates fast; distrusts anything that sounds like marketing; wants to check the claims.
- **Research Development staff (secondary).** Reads the same brief on a laptop to prepare a conversation. Needs the records behind every claim.
- **What that means for the UI.** One decision per screen. Records look like records. Model text is always marked as model text. Nothing is hidden behind hover. Every action is a 44 px target that a thumb can reach.

## 2. Interaction audit

### Find

| | |
|---|---|
| Goes in | Name (searched among Temple University authors only), an ORCID iD, or an OpenAlex author id. Optional: minimum award size; model explanations on or off. |
| API | `GET /authors/resolve?q=` returns up to 3 candidates. `POST /briefs` starts the job. |
| Comes out | Candidate cards: name, last known institution, works count, citations, top OpenAlex topics, ORCID. |
| Must be said | The user confirms the match before anything runs (SPEC §12). Name search covers Temple University only. Nothing is sent anywhere. |
| Empty | No match: say what was searched and suggest an ORCID iD or OpenAlex id. |
| Failed | OpenAlex unreachable: say so, keep the typed text, offer to try again. |
| Progress | Searching takes 1 to 3 s; the button shows it is busy. |

### Building (progress)

| | |
|---|---|
| API | Poll `GET /briefs/{id}` every 1.5 s until `done` or `failed`. |
| Stages | researcher, works, awards, profile, route_a, summary, explanations. Shown in plain words, with the stage `detail` copied underneath. A skipped stage means "already on file", never "skipped". |
| Timing | Measured live: profile in about 6 s, leads in about 9 s, explanations 6 to 9 s each, about 95 s in all. Show elapsed time; never promise a finish time. |
| Partial results | The profile shows as soon as the profile stage is done. Lead cards show as soon as route_a is done, with record fields; explanations fill in one by one and the count says "4 of 10 explained". |
| Failed | The failed stage is marked; the error text is shown as the API returns it; offer "Build again". |

### Profile

| | |
|---|---|
| Comes out | Summary and topic labels (model output, validated); research threads (keyword labels, share of recent work, paper count); the most recent papers in each thread; public awards with dates; the public award horizon. |
| Must be said | The summary is written by a model and checked against the papers it cites. The horizon is the end date of the last public federal award found; nothing about lab finances is inferred. If no award is found, say that, not "no funding". |
| Withheld | If the summary failed validation twice, say it was withheld and show the threads alone. |

### Routes (Route A)

| | |
|---|---|
| Comes out per lead | Agency, activity code, title, opportunity number, closing date, award ceiling and floor, matching eligibility rows, fit estimate, explanation, inference, keep or dismiss. |
| Copied from records | Every date, amount, code and eligibility row. A missing amount reads "not stated in the record". Days until closing are computed by code from the record date and shown beside it. |
| Model output | Fit estimate (0 to 100) shown as a band with the number, labelled as a model estimate, never as a probability. Opportunity sentence and per-paper findings, with each id shown as a chip naming the record. The link sentence is labelled as an inference on every card. |
| Flags | `flagged`: the explanation was withheld after failing checks twice; the record fields still show. `unsupported`: the statement that could not be matched to its source is listed with a warning. |
| Order | Pipeline order by default (the order the back-test measures). Also: closing soonest, fit estimate. |
| Actions | Keep, Dismiss (dismissed leads fold into a section with Restore), Evidence. |
| Must be said | Grants.gov notice wherever Grants.gov data shows. "A starting point, not advice." |

### Evidence panel

| | |
|---|---|
| Opens from | Any chip, the "Evidence" button on a card, any paper or award row. |
| API | `GET /records/{id}`, which accepts long ids, short OpenAlex ids and opportunity numbers. |
| Shows | Record type, the fields as stored, source name, a link to the exact record at the source, when it was fetched. Opportunities add the eligibility list and description; works add venue, DOI and abstract. |
| Form | A bottom sheet on phones; a side panel on wide screens. Escape and a close button dismiss it; focus returns to what opened it. |

## 3. Design

### Concept: a perch at dusk

An owl sits on a branch and watches the forest; Perch reads a body of work and looks for routes. The interface is quiet and evergreen. One element carries the personality: **the owl, Scout**, who lives on the branch in the app bar and rides along the progress branch while a brief is built. Scout is the face of the agent layer that S10 adds.

### Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| ink | #1F2B2D | #E4EAE6 | Text |
| paper | #F3F5F1 | #111A1B | Page background |
| leaf | #FFFFFF | #182325 | Cards and sheets |
| moss | #2E6A54 | #74C3A0 | Actions, links, fit bands |
| ember | #D99A2B | #F0B54A | Scout's eyes, the moment something lands, "closing soon" |
| brick | #A3413A | #E88A80 | Errors and withheld statements |
| line | #D8DED7 | #2B3A3B | Rules and borders |

### Type

- **Interface:** the system UI face, for speed and familiarity.
- **Records:** a book serif (Iowan Old Style, Charter, Georgia) for titles of papers and opportunities. Text from the literature or a record reads in serif; the app's own words read in sans. That split is the at-a-glance cue for what is quoted and what is Perch talking.
- **Numbers:** tabular figures for dates and amounts.

### Layout

```
phone                                   wide (≥ 960 px)
┌──────────────────────┐                ┌──────────────────────────────┬────────────┐
│ owl Perch      [◐]   │  app bar       │ owl Perch                    │            │
│──────────────────────│                │ researcher · as of           │  evidence  │
│ Researcher, as of    │                │ [Profile] [Routes]           │  panel     │
│ [Profile] [Routes]   │  sticky tabs   │ lead cards, 720 px column    │  (sticky)  │
│ progress branch      │                │                              │            │
│ lead card            │                │                              │            │
│ lead card            │                └──────────────────────────────┴────────────┘
│ notice footer        │
└──────────────────────┘
evidence = bottom sheet on phones
```

Left-aligned throughout. One reading column of at most 720 px. Cards only for leads and candidates, which are the things you act on; everything else sits on the page with rules between sections.

### Scout's states (driven by real status, never timers)

| State | When | Motion (none under reduced motion) |
|---|---|---|
| idle | nothing running | blinks now and then |
| look | searching for authors | head turns side to side |
| work | a stage is running | leans in, eyes scan |
| found | an explanation or a stage lands | one small hop |
| done | brief finished | eyes close in a smile |
| worry | a statement is flagged, or nothing was found | head tilts |
| droop | a stage failed | eyes half shut, feathers down |

Scout never speaks. Words beside Scout come from stage details or fixed labels, never a verdict such as "great match".

## 4. Copy rules

- Sentence case, plain verbs. Buttons say what happens: "Find researcher", "Build brief", "Keep", "Dismiss", "Restore", "Open at source".
- Errors say what happened and what to do next.
- Never "should apply", "likely to win" or any measured-sounding claim (standing rule 9). Fit is "fit estimate".
- Missing values say "not stated in the record".

## 5. Replay mode

`web/` can run without the API from a saved brief (`window.PERCH_REPLAY`): the stages play back in about 15 s using the recorded order. It feeds the tracker preview, the screenshots and the Demo Day fallback. Replay files are built by `scripts/export_replay.py` into `build/` (gitignored) with the researcher shown by alias.

## 6. Adversarial review (S7 task 5)

Two independent reviewers, given the code, this document and the screenshots, looked for UX, accessibility, standing-rule and logic failures. They reported 32 findings. Each is fixed or decided below.

- **Fixed: logic.**
  - Keep and Dismiss acted on stale lead objects after a watched build, so the card did not change. Handlers now look the lead up by id.
  - Award rows opened the wrong id, so 11 of 12 had no record. The API now sends each award's `record_id`.
  - The skip link reset the app to Find.
  - Overlapping polls could run twice. A generation counter stops the stale one.
  - The day count used the UTC date instead of the local date.
  - Cards stayed in "Reading" after a failed brief.
  - "Build again" changed the as-of date.
  - Grouped citations such as `[A, B]` left stray brackets.
  - The amount field blocked search on values that are not round thousands.
- **Fixed: standing rules.**
  - Explanations now carry a visible "Model text" tag.
  - The fit pill reads "Fit estimate", and the routes header says it is not the odds of funding.
  - A card no longer cites its own opportunity number.
- **Fixed: layout and accessibility.**
  - Citation chips caused sideways scrolling at 320 px.
  - Action buttons overflowed at 320 px.
  - Light-theme hint and ember text failed contrast. `--ink-3` and `--ember` were darkened.
  - The selected tab was hard to see. It now has a moss underline.
  - The evidence panel is now modal only on phones, with the page behind it inert.
  - Focus is kept through re-renders.
  - Repeated buttons now name their lead.
  - After a dismiss, focus moves to the next card.
  - The visible and spoken names of the theme button and Routes count now match.
  - "Open at source" moved to the top of the evidence panel.
  - The finished progress card is one line.
  - A missing award size no longer takes half the facts row.
  - A failed start no longer clears the candidate list.
  - The sticky tabs sit flush under the bar.
- **Fixed: security.**
  - Embedded replay data escapes every `<`.
  - Cross-origin requests are off unless `PERCH_CORS_ORIGINS` lists an origin. Before, any web page could start briefs that spend the model budget.
- **Kept, by decision.** Scout still blinks now and then while idle; that is the "a bit of personality" the brief asked for. Only the progress owl moves while work runs. The app-bar owl and the small card owls stay still, and reduced motion stops all of it.

Checked by `scripts/screenshots.py`: keep and dismiss take effect after a watched build, and no layout scrolls sideways at 320, 390 or 1280 px in light or dark.
