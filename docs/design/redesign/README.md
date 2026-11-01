# Redesign canvas sources

These are the files of the hosted design canvas for Perch, copied into the repo. The app in `web/` was built from them, and they are kept in step with it before each freeze (last brought in line after S31).

## The files

- `Main.dc.html`: the landing page.
- `ResearcherPick.dc.html`: picking the researcher, with the folded "Tell Perch more" panel and the one Build button.
- `ResearcherBrief.dc.html`: the researcher's brief (Routes, Profile, Compare, Ask Scout).
- `StudentStart.dc.html`: the student's document page.
- `StudentBrief.dc.html`: the student's brief (Your options, What Perch read, Compare, Ask Scout).
- `ScoutProposed.dc.html`: the Scout mock-up from `docs/design/SCOUT_SPEC.md`. Its removable filter chips and inline Keep lists sit behind the `later` prop, which is off: they are phase 2 and not built.
- `Guided.png` and `ShowResult.png`: reference images.

All text in the pages is placeholder text in square brackets, or invented and labelled SYNTHETIC. The canvas uses its own visual language and class names, so it is not a copy of `web/styles.css`.

## Running them

Each page loads `./support.js`. That runtime belongs to the hosted canvas and is not in this repo, so a page opened from disk shows nothing without it. The pages declare their props (`dark`, `cloud`, `student`, `later`) in the `data-props` attribute of the `data-dc-script` block.

To look at a page locally, write a small stand-in for `support.js` outside the repo. It needs to do only what the pages use:

- Define `DCLogic`, a base class with `props`, `state` and a `setState` that merges and re-renders.
- Move the `<helmet>` contents (styles and fonts) into the document head.
- Evaluate the `data-dc-script` block, create `Component`, and call `renderVals()` on every render.
- Expand the template: `<sc-if value="{{x}}">`, `<sc-for list="{{xs}}" as="item">`, `{{path}}` in text and attributes, and `onClick`, `onChange`, `onSubmit` bound to functions.

Two details matter when the template is parsed by a browser:

- Rewrite `<sc-if>` and `<sc-for>` to `<template>` elements first. Inside a table or a select the HTML parser otherwise moves unknown tags out of place.
- Create SVG children in the SVG namespace, or the owl and icons do not draw.

Then drive each page by calling its methods and `setState`, for example `ask(...)` on the Scout pages. Render with Playwright at 1280 px and 390 px and check for console errors and sideways scroll.
