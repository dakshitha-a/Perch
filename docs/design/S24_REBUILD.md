# S24 — UI rebuild from the redesign canvas

Dakshitha redesigned the web app with Perch-dev on a design canvas on 2026-10-30 and asked for it to be built, filling any gaps in the same design language. The canvas sources are in `docs/design/redesign/` (one `.dc.html` file per screen; open the markup for exact sizes and colours). The canvas link is in `CLAUDE.local.md`. This file is the build spec.

## What to build

| Screen | Canvas file | Replaces in `web/` |
|---|---|---|
| Landing | `Main.dc.html` | Find (`renderFind`, the two doors) |
| Researcher 2: pick the person, then optional context | `ResearcherPick.dc.html` | candidate list, Options, Your documents for researchers |
| Researcher 3: the brief (Routes, Profile, Compare, Ask Scout) | `ResearcherBrief.dc.html` | brief header, progress, tabs, lead cards, evidence panel, keep bar, compare, hand-off, Scout |
| Student 2: add your CV | `StudentStart.dc.html` | `renderStudentStart` |
| Student 3: your options (What Perch read, Your options, Compare, Ask Scout) | `StudentBrief.dc.html` | student brief tabs and cards |

Archived options B and C (`ShowResult.png`, `Guided.png`) are not built.

## Design language

- **Type:** Newsreader (serif, 500/600) for the wordmark, page titles, card titles and record titles; Inter (400/500/600) for everything else. Load both from Google Fonts with a system fallback (`Georgia, serif`; `system-ui, sans-serif`), so the app still works offline.
- **Colour tokens (dark / light):** bg `#0F1715` / `#F7F8F4`; surface `#17221F` / `#FFFFFF`; line `#273631` / `#DCE3DE`; chip `#22302B` / `#EBF0EC`; ink `#E9EFEC` / `#16201C`; ink-2 `#B3C1BC` / `#45524D`; ink-3 `#93A39D` / `#5C6964`; accent `#7CCBA8` / `#23664F`; on-accent `#0B1F17` / `#FFFFFF`; ember `#F0B54A` / `#8F5A08` (text) and `#D99A2B` (fills, light); branch `#9C8466` / `#7A5E44`. Verdicts: eligible `#1E3B30`/`#9BE0BE` and `#E2F2E9`/`#1D5A40`; may be eligible `#3A2E16`/`#F0C978` and `#FBF0DC`/`#7A4B05`; not eligible `#3A2226`/`#F2A9B4` and `#FBE6E9`/`#8E2B3B`. The owl keeps its own tokens from `web/styles.css`. Recheck contrast with the walk; 4.5:1 for text.
- **Shapes:** cards radius 14 px with a 1 px line border; buttons and inputs radius 10 to 12 px; chips radius 999 px; segmented controls are a 4 px padded pill holding two buttons, the chosen one filled with accent.
- **Sizes:** touch targets 44 px or more (primary buttons 48 to 56 px); body 15 to 16 px; hints 13 to 14 px in ink-3.
- **Layout:** header bar with the wordmark left; right: a status chip, End session when a session is open, Help, the theme button. Content column max 1080 px for forms, 1180 px for briefs, 680 px for the landing. Briefs use a two-column row on a laptop: the list (`flex: 999 1 560px`) and a right rail (`flex: 1 1 320px`, sticky) that holds the shortlist card above the evidence panel; under 900 px the rail stacks and a floating keep bar appears instead of the shortlist card.
- **Back:** every screen after the landing has a Back link at the top left (chevron icon, ink-2, 44 px). After a pick on the researcher screen it reads "Back to the matches".
- **Motion:** fade-in (0.4 s, 6 to 8 px rise) for anything that appears; shimmer placeholders while waiting; the owl bobs while a build runs. All of it off under `prefers-reduced-motion`.
- **Words:** short, plain, one idea per line. "Nothing about you is stored." "Local models." Records are "copied"; models "write" and are "checked". Never imply odds of funding.
- **Sample data:** dashed amber border on the card, an amber dashed "Sample data" badge, and a banner wherever samples appear (tab, compare, note, export), as now.

## Screens and behaviour

### Landing
- Owl on a branch with moon, stars and leaves (the real owl SVG from `web/owl.js`); tapping it plays the eight random reactions and the heart after five quick taps, as now.
- Headline "Find funding that fits." and one line under it.
- A Researcher | Student segmented control. Researcher: one search field with a Find button and a hint line with "More options" (the context fields move to screen 2). Student: one button, "Start with your CV or résumé".
- Footer row of three promises: every claim cites a public record; nothing about you is stored; hand-offs are drafts, nothing is sent.
- Header chip "Local · nothing stored" with a coloured dot; pressing it opens the Local / Cloud choice (S23 behaviour: confirm naming the provider; amber edge while Cloud is on). The separate frame line under the bar goes; the chip replaces it.
- The paste nudge (S18) stays: CV-like text pasted into the search offers to move it to the documents.

### Researcher 2
- The search stays at the top with "Search again". Heading "Which one is the right person?" and a count.
- Candidate cards: name, Temple tag, department, works, citations, IDs, three topics, and "This is the one". The best match has an accent border.
- After a pick: the others leave, the card shows "Selected", the heading becomes "Ready to build the brief.", a Build brief button appears top right, and "Tell Perch more (optional)" fades in with four boxes in two columns: where your research is going; keywords to search for and to leave out; your CV (Local only, with upload); ongoing research or draft proposal (Local only, with upload). "Fill with a sample" fills them from SYNTHETIC persona-1 (with the Sample data badge); "Clear" empties them. Build brief also sits at the bottom.
- Mapping: direction and keywords go in the session brief request as now; CV and proposal are session documents (`/private/documents`), so Cloud is refused while they are present (S23 rule); career stage and the smallest award move into this panel too.

### Researcher 3 and Student 3 (the briefs)
- Title row: name or "Your options", meta line, Export button (the menu holds the three exports and the mask option from the current private bar).
- Progress card: owl, step name, step count, a thin bar in the branch colour, "Replay the build" only in the replay preview. Stages are the real ones from the API.
- Tabs with a bottom bar on the chosen one: researcher Routes, Profile, Compare (count), Ask Scout; student What Perch read, Your options, Compare (count), Ask Scout.
- Routes: Grants | Industry control with counts, a sort select, one line explaining the order; lead cards (tags, title as a button that opens the evidence, close date and ceiling, fit estimate, folded "Why it fits" with paper chips, Keep, Dismiss, Evidence); shimmer cards until leads arrive; industry cards tagged Inferred, Not verified.
- Your options: Fellowships (public) | Scholarships and awards (sample); verdict chips with a mark and a word (✓ Eligible, ? May be eligible, ✕ Not eligible), facts or "This listing states no deadline or amount.", the reason line, Still needed.
- Profile (researcher): summary (model-written, checked), research threads with weight bars, award horizon, public awards, key papers; each fills in as its stage finishes.
- What Perch read (student): the rule fields read from the CV; "What steers the search" with the interests note and achievements.
- Compare: table of kept items across both kinds; then the hand-off or note: office cards as radios, Draft, the draft with an empty To line, Copy and Open in mail. Empty state points back to the list.
- Ask Scout (both): suggested questions, Ask before each step | Run and show me, tool cards with Approve and Skip, answers with record chips, the rules line, and a right rail listing the tools with a steps counter. Student Scout is new (Q27 revised 2026-10-30): its tools are search options, check one option against the CV by rule, explain a verdict, compare, draft a note; local models only; samples stay marked.

### Student 2
- Back, heading "Tell Perch about you.", the privacy line; a dashed row with "Fill with a sample" (SYNTHETIC persona-ug) and "Clear"; the CV box on the left (upload), interests and achievements on the right; "Find fellowships and scholarships" with the rule beside it.

## Gaps to fill in the same language
Help page, the Local / Cloud dialog (a real dialog, not `window.confirm`), the evidence sheet on a phone, error and empty states, the export menu, the replay preview, and phone layouts of every screen (the canvas is laptop-first; follow its stacking rules).

## Added by Dakshitha's answers (2026-10-30)
- **Draft review in Scout (Q32):** evaluate first (PLAN S24 task 7); build the canvas panel into both Scout tabs only if the numbers are good.
- **Documents on Cloud (Q30):** a second, stronger warning before documents go to the cloud provider; held behind the standing rule 1 change in Q33.
- **Warm demo briefs (Q31):** demo researchers' briefs are built at server start and held in memory; a visitor gets a fresh copy at once.

## Done when
Every screen above is live on the public URL for both paths, light and dark, phone and laptop; `scripts/ux_walk.py` is updated and reports 0 axe violations and no sideways scroll; the canary passes; Help is updated; `make test` is green.
