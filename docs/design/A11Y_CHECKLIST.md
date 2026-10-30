# Accessibility checklist (S21; rerun in S25, before the freeze)

The release checklist for the Perch web app. S21 ran it on the live demo; S25 reruns it before the freeze. The runner is `scripts/ux_walk.py`, with axe-core 4.10.2 (`axe.min.js` from cdnjs, passed with `--axe`). Results go to `build/ux/report-<groups>.json`.

Target: WCAG 2.2 AA, plus the app's own rule of 44 px touch targets (`docs/design/UI.md` §1).

| # | Item | How it is checked | Pass when |
|---|---|---|---|
| 1 | No axe violation of impact serious or critical | `ux_walk.py --axe`: rule sets wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa and best-practice, at every captured state | 0 serious or critical on every state |
| 2 | Text contrast in light and dark | axe `color-contrast` on the PI flow in both schemes and the PhD persona in dark | 0 hits |
| 3 | Keyboard path through Find | `focus.find` in the report: Tab 30 times from the top | Every control reached once, in reading order; no control reached twice |
| 4 | Keyboard path through a brief | `focus.routes` and `focus.<persona>-compare` | Tabs, route switch, cards and actions reachable; no hidden element focused |
| 5 | Focus always visible | `visible` on every focus step | `true` on every step |
| 6 | Nothing focusable inside `aria-hidden` | axe `aria-hidden-focus` | 0 hits |
| 7 | Screen-reader names | axe `button-name`, `link-name`, `label`, `aria-*` rules; manual: tab counts and the private switch read aloud with a name and state | 0 hits; switch reads "Private mode, switch, on/off" |
| 8 | Motion | Manual: `prefers-reduced-motion: reduce` stops the shimmer, landing and owl animations (`styles.css` media query); `focus.reduced-motion-animations` counts looping animations at rest | 0 looping animations with reduced motion |
| 9 | Touch targets | `small` in each state: controls under 44 px (the app's rule) and under 24 px (WCAG 2.5.8), inline text links excepted | No control under 24 px; any under 44 px listed with a reason |
| 10 | No sideways scroll | `overflow` in each state at 390 px and 1280 px | 0 on every state |
| 11 | Private mode visible at a glance | `private` in each state: the switch's `aria-checked`, the frame line, the `private-on` body class | All three on in every private and student state, all off after the session ends |
| 12 | Sample data never unbadged | Manual: every scholarship card, the evidence panel on a sample record, Compare and exports carry the Sample data badge or banner | Badge on every sample record |
| 13 | Zoom to 200% | Manual: laptop at 200% browser zoom, Find, Routes and Compare | No clipped or overlapping text |

## S25 results (2026-10-30, the S24 redesign after the S25 review fixes)

Walks: the demo (119 states, researcher and three SYNTHETIC students) and the dev server (103 states plus a student and persona-1 rerun), phone and laptop, light and dark. The switch in item 7 and item 11 is now the status chip and the Local or Cloud dialog (S24).

| # | Result |
|---|---|
| 1 | Pass: 0 axe violations in the last runs. The S25 runs found and fixed: a Sample badge's contrast in the chosen pill, the evidence rail not focusable, the keep pill covering the Scout box, and phone labels that picked up an older grey text rule. |
| 2 | Pass: 0 `color-contrast` hits in light and dark after those fixes. |
| 3 | Pass: every landing control reached in order. Tabbing 30 times wraps round the short landing page, so controls repeat after the last one. |
| 4 | Pass: tabs, the route pill, cards, actions, the shortlist and the evidence rail are reachable. |
| 5 | Pass: focus visible on every step (0 steps without an outline). |
| 6 | Pass: 0 `aria-hidden-focus` hits. |
| 7 | Pass: 0 name hits. Phone tabs and pills show short words; each carries its full name in `aria-label`. The status chip reads "Privacy: nothing stored, local models. Change models". |
| 8 | Pass: 0 looping animations with reduced motion. |
| 9 | Pass: nothing under 24 px except the inline ORCID link and a hidden file input. Under 44 px with a reason: lead titles are text links inside headings; segmented pills are 40 px on a laptop and 44 px with a touch pointer. |
| 10 | Pass: 0 sideways scroll at 390 px and 1280 px. Compare tables stack into cards under 600 px. |
| 11 | Pass: the chip is visible in every state; "Local only" once a document is added; amber edge with Cloud on. |
| 12 | Pass (manual, from the screenshots and QA row 21): badge on every sample card, tab, compare row, note and export. |
| 13 | Not rerun at 200% zoom. The phone runs at 390 px cover the same reflow. |
