# Accessibility checklist (S21; rerun in S23)

The release checklist for the Perch web app. S21 ran it on the live demo; S23 reruns it on the frozen build. The runner is `scripts/ux_walk.py`, with axe-core 4.10.2 (`axe.min.js` from cdnjs, passed with `--axe`). Results go to `build/ux/report-<groups>.json`.

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
