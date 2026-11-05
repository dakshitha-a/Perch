// Help: a short visual guide to using Perch (docs/design/UI.md §7). Each step is one or two
// plain lines beside a small animated figure built from the app's own parts. The figures are
// decorative (aria-hidden) because the step text says the same thing; they animate with CSS
// keyframes only, and the reduced-motion block in styles.css stops them on their final state.
// One inline SVG shows the demo path as built, in two layouts (a grid on wide screens, a
// column on phones); the layout not shown is display:none, so only one reaches a screen
// reader, with a text list beside it. The technical detail lives in docs/SPEC.md, not here.
// Every claim below describes code in this repo.

import { h, icon } from "./dom.js";
import { owl } from "./owl.js";
import { verdictChip } from "./student.js";

// Fixed notes, word for word as perch/offices.py writes them (tests/test_web.py compares).
const SUBMISSION_URL = "https://research.temple.edu/researchadministration/contact-us/find-your-res-administrator";
const COVER_HELP = "On a lead card, Cover-letter points asks a model to pair what the record asks for with what your CV, entries and papers show, each line cited. It needs an account, it is model text to put in your own words, and it is never sent or added to an export. When today’s allowance is used, one note above the list says so, with the time it comes back.";
const SUBMISSION_NOTE = "Before anything goes to a sponsor, Temple routes it through ERA for institutional review and approval. That covers every grant proposal and any company agreement that brings Temple funding. Your assigned research administrator supports that step.";
const FOUNDATION_NOTE = "Foundations are not covered yet. When they are, foundation leads will go to Temple's Office of Corporate and Foundation Relations, through your school's or college's development team, as that office's page asks.";
const RESEARCH_SECURITY = "Companies outside the United States may need a research-security review before any contact; the office makes that check.";

const ph = (w, extra = "") => h("span", { class: `ph w${w} ${extra}`.trim() });
const row = (...kids) => h("div", { class: "pic-row" }, ...kids);
const card = (...kids) => h("div", { class: "pic-card" }, ...kids);
const btn = (text, extra = "", ic = null) => h("span", { class: `pic-btn ${extra}`.trim() }, ic ? icon(ic) : null, h("span", { text }));
const fig = (...kids) => h("figure", { class: "fig", "aria-hidden": "true" }, h("div", { class: "fx" }, ...kids));

// ----- the figures -----

function figFind() {
  return fig(
    h("div", { class: "pic-field" }, h("span", { class: "typed n10", text: "A. Example" })),
    btn("Find", "press1", "search"));
}

function figBuild() {
  return fig(
    card(
      row(icon("person"), ph(40), h("span", { class: "tag moss", text: "Temple University" })),
      btn("This is the one", "press1")),
    h("div", { class: "pic-branch" },
      h("div", { class: "branch-line" }), h("div", { class: "branch-fill" }),
      h("div", { class: "rider" }, owl("work", "owl-rider"))));
}

function figRoutes() {
  const keep = h("span", { class: "pic-btn togg keep-btn" },
    h("span", { class: "k-off" }, icon("keep"), h("span", { text: "Keep" })),
    h("span", { class: "k-on" }, icon("keep"), h("span", { text: "Kept" })));
  return fig(
    card(
      h("div", { class: "pic-row between" },
        h("span", { class: "fit strong" }, h("span", { class: "fit-k", text: "Match" }), h("b", { text: "86" })),
        h("span", { class: "pic-row" }, keep, btn("Dismiss", "ghost", "dismiss"))),
      ph(80, "tall"), ph(50)),
    h("div", { class: "pic-card dim-later" },
      h("div", { class: "pic-row between" }, ph(30), btn("Dismiss", "ghost press2", "dismiss")), ph(70)),
    h("div", { class: "pic-row between" },
      h("b", { text: "Your shortlist" }),
      h("span", { class: "count" }, h("span", { class: "c0", text: "0" }), h("span", { class: "c1", text: "1" }))));
}

function figHandoff(student) {
  return fig(
    card(h("div", { class: "pic-row between in1" }, ph(40), ph(20), ph(20)),
      h("div", { class: "pic-row between in1" }, ph(30), ph(20), ph(20))),
    h("span", { class: "chip in2", text: student ? "Temple office" : "Research Development" }),
    card(
      h("div", { class: "pic-row in3" }, h("b", { text: "Dear team," }),
        student ? null : h("span", { class: "tag model", text: "Model text" })),
      ph(90, "grow3"), ph(70, "grow4")),
    h("div", { class: "pic-row in4" }, btn("Copy the draft"), btn("Open in my mail app", "ghost", "mail")));
}

function figScout() {
  return fig(
    // S45 fix round 3: Scout v2 runs read steps and cites records; it shows no filters or scores.
    h("div", { class: "pic-field" }, h("span", { class: "typed n29", text: "what does my top lead ask for" })),
    h("div", { class: "pic-row" },
      h("span", { class: "chip in2", text: "Read the brief" }),
      h("span", { class: "chip in3", text: "Read a record" })),
    card(h("div", { class: "pic-row in4" }, h("span", { class: "tag model", text: "Model text" }), ph(40)),
      h("div", { class: "pic-row in4" }, ph(60), h("span", { class: "chip", text: "Record" }))));
}

function figWho() {
  return fig(
    h("div", { class: "seg" },
      h("span", { class: "seg-b seg-off", text: "Researcher" }),
      h("span", { class: "seg-b seg-on", text: "Student" })),
    h("span", { class: "pic-btn big in2" }, h("span", { text: "Browse Temple awards" })));
}

function figDocs() {
  return fig(
    card(h("b", { text: "Sample student" }), ph(90), ph(60)),
    h("span", { class: "pic-btn in4" }, h("span", { text: "Try a sample student" })));
}

function figTags() {
  return fig(
    h("div", { class: "pic-row in1" }, h("span", { class: "chip", text: "All" }), h("span", { class: "chip", text: "All Temple" }), h("span", { class: "chip", text: "A school" })),
    card(h("div", { class: "pic-row in2" }, ph(50), h("span", { class: "tag moss", text: "School" })), ph(70)),
    card(h("div", { class: "pic-row in3" }, ph(40), h("span", { class: "tag", text: "Open across Temple" })), ph(60)));
}

function figVerdicts() {
  return fig(
    card(h("div", { class: "pic-row between in1" }, ph(50), verdictChip("eligible")),
      h("div", { class: "pic-row in2" }, h("b", { text: "Still needed:" }), ph(40))),
    card(h("div", { class: "pic-row between in3" }, ph(40), verdictChip("may be eligible")),
      h("div", { class: "pic-row in4" }, h("b", { text: "Still needed:" }), ph(50))));
}

// ----- the lead card, with numbered callouts -----

function anatomy() {
  const n = (i) => h("span", { class: "callout", text: String(i) });
  const art = h("figure", { class: "fig anat", "aria-hidden": "true" },
    card(
      h("div", { class: "pic-row" }, n(1), h("span", { class: "anat-title", text: "Opportunity title" })),
      h("div", { class: "pic-row between" },
        h("span", { class: "pic-row" }, n(2), h("span", { class: "fit strong" }, h("span", { class: "fit-k", text: "Match" }), h("b", { text: "86" }))),
        h("span", { class: "pic-row" }, n(3), btn("Keep", "ghost", "keep"), btn("Dismiss", "ghost", "dismiss"))),
      h("dl", { class: "facts" },
        h("div", { class: "fact" }, h("dt", { text: "Closes" }), h("dd", {}, n(4), ph(60))),
        h("div", { class: "fact" }, h("dt", { text: "Amount" }), h("dd", {}, ph(50)))),
      h("div", { class: "pic-row" }, n(5), h("span", { class: "tag model", text: "Model text" }), ph(50)),
      h("div", { class: "pic-row" }, h("b", { text: "Why it fits" }), icon("back"))));
  const items = [
    ["The title", " comes first, then the agency and code. The title opens the full record."],
    ["Match", " is how closely the listing’s text matches the papers, from 0 to 100: strong is 80 or more, good 60 to 79, partial 40 to 59, weak below 40."],
    ["Keep or Dismiss", ": keep what is worth a closer look and dismiss the rest. A dismissed lead can be restored."],
    ["Closes and Amount", " are always shown. Not stated means the record leaves it blank. The page says means the date is in the page’s words, not a date field."],
    ["Model text", " marks a model’s sentence, checked against the records it cites. When a sentence fails that check twice, the card says so in one line and keeps only the fields copied from the record."],
  ];
  return h("div", { class: "anatomy" }, art,
    h("ol", { class: "callouts" }, items.map(([b, t]) => h("li", {}, h("span", {}, h("b", { text: b }), t)))));
}

// ----- steps -----

function steps(id, title, items) {
  return h("section", { class: "help-block", "aria-labelledby": id },
    h("h2", { id, class: "section-title", text: title }),
    h("ol", { class: "g-steps" }, items.map(([t, text, figure], i) => h("li", { class: "g-step" },
      figure,
      h("div", { class: "g-t" },
        h("span", { class: "g-n", "aria-hidden": "true", text: String(i + 1) }),
        h("h3", { text: t }),
        h("p", { text }))))));
}

function researcher() {
  return steps("h-researcher", "If you are a researcher", [
    ["Find the researcher", "Type a name, an ORCID iD or an OpenAlex ID, then press Find. Names are searched among Temple authors. Browse funding lists open funding with no search.", figFind()],
    ["Confirm and build", "Check the institution and the papers, press This is the one, then Build brief. The owl rides the branch as each step finishes.", figBuild()],
    ["Read the routes and decide", "Grants and Industry are separate lists. Keep the leads worth a closer look and dismiss the rest. Kept leads gather in Your shortlist.", figRoutes()],
    ["Compare and hand off", "Compare puts your kept leads side by side. Pick an office and Perch drafts an email for you to edit and send. Drafting needs an account.", figHandoff(false)],
    ["Ask Scout", "Ask in plain words, such as “what does my top lead ask for that my CV does not show yet?”. Scout reads your brief, the records and your CV, and cites each claim about a record or about you; general advice is marked as uncited. Its buttons, such as Deadlines, are answered by code. Scout needs an account.", figScout()],
  ]);
}

function student() {
  return steps("h-student", "If you are a student", [
    ["Browse Temple awards", "Choose Student, then press Browse Temple awards. You need no account to look through the list. Every card links to the page it came from.", figWho()],
    ["Narrow the list", "Pick a school tag to see that school’s awards first, then the awards open across Temple. The search box and the level menu narrow it further.", figTags()],
    ["Check my fit", "Sign in, save your CV and press Find awards that fit. With no account, press Try a sample student: it is an invented SYNTHETIC student, labelled as sample data.", figDocs()],
    ["Read the verdicts", "Each option shows a rule check: Eligible, May be eligible or Not eligible. Still needed lists what the record asks for and your CV does not show.", figVerdicts()],
    ["Compare and send the note", "Keep options, then Compare them and pick the Temple office. Code writes a short note for you to copy or open in your mail app. A guest can keep and compare; the note needs an account.", figHandoff(true)],
  ]);
}

function keeping() {
  const items = [
    ["Keep from the lists.", " On Temple awards and Research funding, Keep saves a record to your account. Kept and saved records collect on My Perch with their dates. Sample records cannot be kept."],
    ["Sort and closed calls.", " Sort a list A to Z, by the soonest date or by the largest amount. Records that state no date or amount come last. Research funding hides calls whose close date has passed; turn on Show closed calls to see them."],
    ["A past date on an award.", " Many Temple awards recur each year. When an award’s page shows a date that has passed, the card says Past date on the page, and a check of your fit says may be eligible, with the date from the page. Check the page for this year’s date."],
    ["My Perch is your home.", " When you are signed in, Perch opens on My Perch: what you kept and saved, sorted by date, your briefs, and your documents. Start a new search from there."],
    ["Change details and run again.", " It opens the start screen with your details filled in. Running it makes a new brief; the old one stays on My Perch."],
    ["A researcher CV.", " A researcher may add a CV before building a brief. It is optional. Perch uses it for cover-letter points and Scout, stores it encrypted, and blanks contact details before a model reads it."],
  ];
  return h("section", { class: "help-block", "aria-labelledby": "h-keep" },
    h("h2", { id: "h-keep", class: "section-title", text: "Keeping and My Perch" }),
    h("ul", { class: "plain-list" }, items.map(([b, t]) => h("li", {}, h("b", { text: b }), h("span", { text: t })))));
}

function leadCard() {
  return h("section", { class: "help-block", "aria-labelledby": "h-card" },
    h("h2", { id: "h-card", class: "section-title", text: "Reading a lead card" }), anatomy(),
    h("p", { class: "hint", "data-key": "help-cover", text: COVER_HELP }));
}

// ----- the architecture diagram -----

const SVG_NS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    if (k === "style") el.style.cssText = v; // CSSOM: the CSP blocks style attributes
    else el.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return el;
}

const ARCH_LABEL = "How Perch works, in order. Public sources are fetched by code into a store. Models search and rank. A chat model explains and summarises. Code and a grounding model check the writing. You get your brief, then keep, compare, ask Scout and send the hand-off draft yourself.";
// kind: record, code, model, brief or you; the lines are what the node says under its title.
const NODES = [
  ["record", "Public sources", ["OpenAlex, NIH RePORTER,", "NSF, Grants.gov,", "Temple fellowship list"]],
  ["code", "Fetch", ["Plain code. Every record", "keeps its source, link", "and fetch date"]],
  ["code", "Store", ["Public records and the", "search index."]],
  ["model", "Search and rank", ["Embedding and ranking", "models find and order", "the matches."]],
  ["model", "Explain", ["A chat model writes the", "profile summary and", "why each lead fits."]],
  ["code", "Check", ["Code checks each cited", "record, then a model", "checks each statement."]],
  ["brief", "Your brief", ["Routes, Compare and", "Ask Scout, every claim", "linked to its record."]],
  ["you", "You", ["Keep, compare, ask", "Scout, and send the", "hand-off draft."]],
];
const SR_LIST = [
  "Public sources: OpenAlex, NIH RePORTER, NSF, Grants.gov, Temple's public scholarship and award pages and the Temple fellowship list.",
  "Fetch: plain code; every record keeps its source, link and fetch date.",
  "Store: public records and the search index.",
  "Search and rank: embedding and ranking models find and order matches.",
  "Explain: a chat model writes the profile summary and why each lead fits.",
  "Check: code checks each cited record, then a grounding model checks each statement.",
  "Your brief: Routes, Compare and Ask Scout, every claim linked to its record.",
  "You: keep, compare, ask Scout and send the hand-off draft yourself.",
];

function archSvg(vertical) {
  const W = vertical ? 340 : 800, NW = vertical ? 340 : 170, NH = vertical ? 66 : 100, GAP = vertical ? 16 : 40, RG = 52;
  const pos = (i) => {  // top-left of node i
    if (vertical) return [0, i * (NH + GAP)];
    const r = i < 4 ? 0 : 1, c = r ? 7 - i : i;
    return [c * (NW + GAP), r * (NH + RG)];
  };
  const kids = [];
  const mid = NODES.map((_, i) => { const [x, y] = pos(i); return [x + NW / 2, y + NH / 2]; });
  // rail and dot first, so the nodes cover them and they show in the gaps only
  let d = `M${mid[0][0]} ${mid[0][1]}`;
  if (vertical) d += ` V${mid[7][1]}`; else d += ` H${mid[3][0]} V${mid[4][1]} H${mid[7][0]}`;
  kids.push(s("path", { d, class: "arch-rail" }), s("circle", { r: 5, class: "arch-dot", style: `offset-path: path("${d}")` }));
  const rewrap = (lines) => {  // the column is wide enough for two lines a node
    const words = lines.join(" ").split(" "), out = [""];
    for (const w of words) {
      if ((out[out.length - 1] + " " + w).trim().length > 46) out.push(w);
      else out[out.length - 1] = (out[out.length - 1] + " " + w).trim();
    }
    return out;
  };
  NODES.forEach(([kind, title, lines0], i) => {
    const lines = vertical ? rewrap(lines0) : lines0;
    const [x, y] = pos(i);
    kids.push(s("g", { class: `arch-n ${kind}` },
      s("rect", { x, y, width: NW, height: NH, rx: 12 }),
      s("circle", { cx: x + 17, cy: y + 19, r: 10, class: "arch-num" }),
      s("text", { x: x + 17, y: y + 19, class: "arch-numt" }, String(i + 1)),
      s("text", { x: x + 34, y: y + 24, class: "arch-t" }, title),
      lines.map((l, j) => s("text", { x: x + 14, y: y + (vertical ? 42 : 50) + j * (vertical ? 15 : 18), class: "arch-s" }, l))));
    if (i === 7) return;
    // an arrowhead in the gap after node i
    const [x2, y2] = pos(i + 1);
    let pts;
    if (vertical) pts = `${x + NW / 2 - 6},${y + NH + GAP - 12} ${x + NW / 2},${y + NH + GAP - 1} ${x + NW / 2 + 6},${y + NH + GAP - 12}`;
    else if (i === 3) pts = `${x + NW / 2 - 6},${y2 - 12} ${x + NW / 2},${y2 - 1} ${x + NW / 2 + 6},${y2 - 12}`;
    else if (i < 3) pts = `${x + NW + GAP - 12},${y + NH / 2 - 6} ${x + NW + GAP - 1},${y + NH / 2} ${x + NW + GAP - 12},${y + NH / 2 + 6}`;
    else pts = `${x2 + NW + 12},${y + NH / 2 - 6} ${x2 + NW + 1},${y + NH / 2} ${x2 + NW + 12},${y + NH / 2 + 6}`;
    kids.push(s("polygon", { points: pts, class: "arch-head" }));
  });
  const H = vertical ? 8 * NH + 7 * GAP : 2 * NH + RG;
  return s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": ARCH_LABEL, class: `arch ${vertical ? "arch-v" : "arch-w"}` }, kids);
}

function architecture() {
  const kinds = [["record", "Public records"], ["code", "Code"], ["model", "Models"], ["you", "You"]];
  return h("section", { class: "help-block", "aria-labelledby": "h-how" },
    h("h2", { id: "h-how", class: "section-title", text: "How Perch works" }),
    h("figure", { class: "arch-fig" },
      archSvg(false), archSvg(true),
      h("p", { class: "arch-key", "aria-hidden": "true" },
        kinds.map(([k, t]) => h("span", { class: `kind ${k}`, text: t }))),
      h("ol", { class: "sr-only" }, SR_LIST.map((t) => h("li", { text: t })))));
}

// ----- privacy and good to know -----

function privacy() {
  const items = [
    ["person", "A guest session saves nothing.", " It ends after an hour. Hand-off drafts, notes to an office and Scout need an account."],
    ["lock", "A CV you add is stored encrypted.", " Contact details are blanked before any text goes to the model provider named in the consent."],
    ["close", "You can delete your data.", " Open the account menu, then Account and data, then Delete my data. Perch also deletes it after 12 months without use."],
    ["mail", "Perch sends nothing.", " Hand-offs are drafts. You send them."],
  ];
  return h("section", { class: "help-block", "aria-labelledby": "h-privacy" },
    h("h2", { id: "h-privacy", class: "section-title", text: "Your privacy" }),
    h("ul", { class: "priv" }, items.map(([ic, b, t]) => h("li", {},
      h("span", { class: "priv-ic", "aria-hidden": "true" }, icon(ic)),
      h("p", {}, h("b", { text: b }), t)))));
}

function goodToKnow() {
  return h("section", { class: "help-block", "aria-labelledby": "h-know" },
    h("h2", { id: "h-know", class: "section-title", text: "Good to know" }),
    h("ul", { class: "plain-list" },
      h("li", { text: "A brief is a starting point, not advice. Perch does not confirm your personal eligibility, such as career stage or citizenship. Read each record." }),
      h("li", {}, h("span", { text: "Industry leads are inferences from public signals, not verified interest. " + RESEARCH_SECURITY })),
      h("li", {}, h("span", { text: SUBMISSION_NOTE + " " }),
        h("a", { href: SUBMISSION_URL, target: "_blank", rel: "noopener", text: "Find your research administrator" }),
        h("span", { text: "." })),
      h("li", { text: FOUNDATION_NOTE }),
      h("li", { text: "A Sample data badge marks invented SYNTHETIC records. They are not real, and they live on their own screen, linked at the foot of each list and from a signed-in student's brief. The guest's sample student brief has a marked sample tab of its own. Sample records cannot be kept or saved." })),
    h("p", { class: "help-scout", text: "The full technical description is in the project’s docs." }));
}

export function renderHelp(container, { back }) {
  const hello = owl("idle", "owl-md help-owl", { button: true });
  container.replaceChildren(h("article", { class: "help" },
    h("a", { class: "back", href: back, "data-key": "help-back", onclick: (e) => {
      if (back !== "#/" && history.length > 1) { e.preventDefault(); history.back(); }
    } }, icon("back"), h("span", { text: "Back" })),
    h("header", { class: "help-head" },
      h("div", {},
        h("h1", { class: "who", text: "Help" }),
        h("p", { class: "lede", text: "Perch reads a researcher’s public papers, or a student’s CV, and lays out the funding that fits. Every claim links to its record." })),
      hello),
    researcher(), student(), keeping(), leadCard(), architecture(), privacy(), goodToKnow()));
}
