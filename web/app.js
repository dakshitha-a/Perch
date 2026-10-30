// Perch web app: Find -> Profile -> Routes, with the evidence panel (docs/design/UI.md).
// Plain DOM, no build step. Every value from a record goes in through textContent.

import { liveApi, privateApi, replayApi } from "./api.js";
import { add, fill, h, icon } from "./dom.js";
import { renderHelp } from "./help.js";
import { compareOffices, loadCompare, renderCompare } from "./compare.js";
import { renderHandoff } from "./handoff.js";
import { renderScout } from "./scout.js";
import * as f from "./format.js";
import { hop, owl, poke, setOwl } from "./owl.js";
import { lockLabel, privateAvailable, privateBar, privateInfo, renderPrivate, setMode } from "./private.js";
import { createMode, looksPersonal } from "./mode.js";
import { isStudent, usedSample, renderStudentStart, studentCompare, studentProfile, studentRoutes, STUDENT_ROUTES } from "./student.js";

const publicApi = window.PERCH_REPLAY ? replayApi(window.PERCH_REPLAY) : liveApi(window.PERCH_API || "");
const privApi = privateApi(window.PERCH_API || "");
let api = publicApi; // privApi while a session brief (#/brief/private) is on screen
// Since S23 every brief runs in a session held in memory (private by default). The
// header switch picks the models: Local (default) or Cloud, after a warning.
const mode = createMode(privApi, { onChange: () => drawSwitch() });
setMode(mode);
const PRIVATE_ID = "private";
const POLL_MS = 1500;
const TABS = ["routes", "profile", "compare", "scout"]; // the order of the tabs (S24)
const SOURCES = { openalex: "OpenAlex", grants_gov: "Grants.gov", nih_reporter: "NIH RePORTER",
  nsf: "NSF Award Search", perch: "Perch", private: "Your private document (this session only)",
  temple_sdfa: "Temple Scholar Development and Fellowships Advising (public list)",
  synthetic: "SYNTHETIC sample corpus (invented, not a real scholarship)" };
const KINDS = { opportunity: "Funding opportunity", work: "Paper", award: "Public award",
  researcher: "Researcher", organisation: "Organisation", lead: "Industry lead",
  private: "Your private document", scholarship: "Scholarship or fellowship" };
const SIGNALS = { citing_works: "They cite your papers", sbir_sttr: "NIH SBIR/STTR awards",
  topic_works: "They publish in your topics" };

const S = {
  find: { q: "", busy: false, error: null, candidates: null, searched: "", explain: true,
    minAmount: "", direction: "", include: "", exclude: "", stage: "", nudge: null,
    picked: null, cv: "", proposal: "", files: {}, sample: false, building: false },
  who: "r", // the landing's Researcher | Student control
  hasDocs: false, // the session holds documents: Cloud stays off
  sampleBrief: false, // the brief on screen was steered by SYNTHETIC sample text
  privateOn: false, // the server offers sessions
  cloud: false, // Cloud on for this session
  brief: null, // last GET /briefs payload
  briefId: null,
  tab: "routes",
  sort: "order",
  route: "A", // Routes tab: "A" grants, "B" industry
  open: new Set(), // lead ids whose "Why it fits" is open
  stepsOpen: false,
  pollTimer: null,
  gen: 0, // bumps whenever the brief on screen changes; stale polls drop out
  failedPolls: 0,
  seen: { explained: 0, stagesDone: 0 },
  startedHere: false,
};

const $ = (sel) => document.querySelector(sel);
const main = () => $("#main");

function announce(msg) {
  const live = $("#live");
  live.textContent = "";
  setTimeout(() => { live.textContent = msg; }, 30);
}

// ---------- routing ----------

function screen(name) {
  document.body.dataset.screen = name;
}

function leaveBrief() {
  stopPolling();
  S.briefId = null;
  S.brief = null;
  api = publicApi;
  closeEvidence();
}

function route() {
  if (location.hash && !location.hash.startsWith("#/")) return; // in-page anchors, e.g. the skip link
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const onHelp = parts[0] === "help";
  if (onHelp) $("#help").setAttribute("aria-current", "page");
  else $("#help").removeAttribute("aria-current");
  document.body.classList.toggle("on-help", onHelp);
  if (onHelp) {
    leaveBrief();
    screen("help");
    document.title = "Help — Perch";
    renderHelp(main(), { back: S.lastHash && S.lastHash !== location.hash ? S.lastHash : "#/" });
    window.scrollTo(0, 0);
    main().focus({ preventScroll: true });
    return;
  }
  S.lastHash = location.hash || "#/";
  if (parts[0] === "private") {
    leaveBrief();
    screen("form");
    renderPrivate(main(), { api: privApi, go, announce, mode });
    return;
  }
  if (parts[0] === "student") {
    leaveBrief();
    screen("form");
    renderStudentStart(main(), { api: privApi, mode, go, announce, info: privateInfo() || {} });
    return;
  }
  if (parts[0] === "find") {
    leaveBrief();
    screen("form");
    renderPick();
    window.scrollTo(0, 0);
    return;
  }
  if (parts[0] === "brief" && parts[1]) {
    const id = decodeURIComponent(parts[1]);
    if (id === PRIVATE_ID && !privApi.open) { go("#/"); return; }
    screen("brief");
    api = id === PRIVATE_ID ? privApi : publicApi;
    S.tab = TABS.includes(parts[2]) ? parts[2] : S.tab;
    if (id !== S.briefId) openBrief(id);
    else renderPanel();
    return;
  }
  leaveBrief();
  screen("landing");
  renderFind();
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function barOwl() { /* the redesign has no owl in the bar (S24) */ }

// ---------- Landing (S24): Scout on the branch, the headline, Researcher | Student ----------

function keepFocus(render) {
  const a = document.activeElement;
  const key = a && (a.id || a.dataset.key);
  render();
  if (!key) return;
  const t = document.getElementById(key) || main().querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (t && t !== document.activeElement) t.focus({ preventScroll: true });
}

// A segmented control: a radiogroup of two buttons, arrow keys move the choice.
function seg(label, value, options, pick) {
  const keys = options.map((o) => o[0]);
  return h("div", { class: "seg", role: "radiogroup", "aria-label": label },
    options.map(([key, text, extra]) => h("button", { type: "button", role: "radio", "data-key": `seg-${key}`,
      "aria-checked": String(value === key), tabindex: value === key ? "0" : "-1",
      onclick: () => pick(key),
      onkeydown: (e) => {
        if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
        e.preventDefault();
        const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : keys.length - 1;
        const next = keys[(keys.indexOf(key) + step) % keys.length];
        pick(next);
        setTimeout(() => { const b = document.querySelector(`[data-key="seg-${next}"]`); if (b) b.focus(); }, 0);
      } }, h("span", { text }), extra || null)));
}

function renderFind() {
  document.title = "Perch";
  const F = S.find;
  const ok = mode.state.available;
  const input = h("input", { id: "q", name: "q", type: "search", autocomplete: "off",
    enterkeyhint: "search", placeholder: "Researcher name, ORCID iD or OpenAlex ID", required: true,
    "aria-describedby": "q-hint", value: F.q,
    oninput: (e) => { F.q = e.target.value; },
    onpaste: (e) => pasted(e, "q", "cv") });
  const researcher = h("form", { role: "search", onsubmit: (e) => { e.preventDefault(); search(); } },
    h("label", { for: "q", class: "sr-only", text: "Find a Temple researcher" }),
    h("div", { class: "searchbox" }, input,
      h("button", { class: "btn primary", type: "submit", disabled: F.busy || Boolean(F.nudge),
        "aria-busy": F.busy ? "true" : null }, h("span", { text: F.busy ? "Searching" : "Find" }))),
    h("div", { class: "hint-row" },
      h("span", { id: "q-hint", text: "Names search Temple authors; an ID finds anyone." }),
      h("details", { class: "more-opts" }, h("summary", { "data-key": "more-opts", text: "More options" }),
        h("p", { text: "After you pick the person, you can tell Perch where your research is going, keywords to search for or leave out, your CV and a draft proposal. All of it is optional and held in memory only." }),
        ok ? h("p", {}, h("a", { href: "#/private", "data-key": "docs-link", text: "No public papers yet? Build a brief from your documents alone." })) : null)));
  const student = h("div", { class: "student-go" },
    h("button", { class: "btn primary", type: "button", disabled: !ok, "aria-describedby": "aud-hint",
      "data-key": "student", onclick: startStudent }, h("span", { text: "Start with your CV or résumé" })),
    h("span", { class: "hint", id: "aud-hint", text: ok ? "Fellowships and sample scholarships, checked against it by rule."
      : `Student mode is not available. ${mode.state.reason || "This server offers no sessions."}` }));
  fill(main(), h("div", { class: "landing" },
    heroArt(),
    h("h1", { text: "Find funding that fits." }),
    h("p", { class: "lede", text: "Perch reads public records and links every claim to its source." }),
    seg("Who is searching", S.who, [["r", "Researcher"], ["s", "Student"]], (k) => { S.who = k; keepFocus(renderFind); }),
    S.who === "s" ? student : researcher,
    nudgeBox(),
    F.error ? h("div", { class: "notice error", role: "alert" }, icon("warn"), h("p", { text: F.error })) : null));
}

async function startStudent() {
  try {
    if (S.cloud) await setCloud(false); // a CV stays on local models
    await mode.enable();
    go("#/student");
  } catch (e) { S.find.error = e.message; renderFind(); }
}

// The paste nudge: a check in this browser only. Long or CV-like text pasted into a
// search field gets an offer to add it as a document instead. Nothing is sent until the
// person chooses; search is held back while the offer is open.
function pasted(e, field, kind) {
  const text = (e.clipboardData || window.clipboardData).getData("text");
  if (!looksPersonal(text) || !mode.state.available) return;
  S.find.nudge = { field, kind };
  setTimeout(() => keepFocus(renderFind), 0);
}

function nudgeBox() {
  const n = S.find.nudge;
  if (!n) return null;
  const F = S.find;
  return h("div", { class: "notice nudge", role: "alert" }, icon("lock"),
    h("div", {}, h("p", { text: "This looks like personal text, such as a CV. Add it as a document instead? Documents stay on local models. Nothing has been sent." }),
      h("div", { class: "doc-actions" },
        h("button", { class: "btn primary", type: "button", onclick: async () => {
          const text = F.q;
          try {
            if (S.cloud) await setCloud(false);
            await mode.move(n.kind, text);
            F.q = "";
            F.nudge = null;
            go("#/student");
          } catch (err) { F.nudge = null; F.error = err.message; renderFind(); }
        } }, icon("lock"), h("span", { text: "Add as a document" })),
        h("button", { class: "btn", type: "button", onclick: () => { F.nudge = null; renderFind(); } },
          h("span", { text: "Keep it here" })))));
}

function heroArt() {
  // A branch at dusk with Scout on it. Decorative; Scout reacts to taps.
  const wrap = h("div", { class: "hero-art", "aria-hidden": "true" });
  wrap.innerHTML = `<svg class="scene" viewBox="0 0 320 150" focusable="false">
    <circle class="moon" cx="262" cy="38" r="18"/>
    <circle class="moon-cut" cx="271" cy="32" r="16"/>
    <circle class="star" cx="214" cy="22" r="1.6"/><circle class="star" cx="300" cy="78" r="1.3"/>
    <circle class="star" cx="236" cy="64" r="1.1"/>
    <path class="branch" d="M0 120 C60 112 120 118 180 110 C220 105 260 108 320 96"/>
    <path class="twig" d="M150 114 C160 100 172 94 186 92"/>
    <path class="leaf" d="M186 92 c8 -10 20 -8 24 -4 c-8 8 -18 9 -24 4z"/>
    <path class="leaf" d="M60 116 c-4 -12 2 -20 8 -22 c4 10 0 18 -8 22z"/>
    <path class="leaf" d="M240 104 c6 -9 16 -9 20 -6 c-6 7 -15 9 -20 6z"/>
  </svg>`;
  const o = owl("idle", "owl-hero", { button: true, copy: true });
  o.setAttribute("aria-label", "Say hello to Scout");
  wrap.removeAttribute("aria-hidden");
  wrap.querySelector("svg").setAttribute("aria-hidden", "true");
  wrap.append(o);
  return wrap;
}

async function search() {
  const F = S.find;
  const q = F.q.trim();
  if (!q) { $("#q").focus(); return; }
  Object.assign(F, { busy: true, error: null, candidates: null, searched: q, picked: null });
  keepFocus(location.hash === "#/find" ? renderPick : renderFind);
  try {
    const r = await api.resolve(q);
    F.candidates = r.candidates || [];
  } catch (e) {
    F.error = e.status === 0 ? e.message
      : `OpenAlex could not be searched: ${e.message} Check the spelling or try an ORCID iD.`;
  }
  F.busy = false;
  const n = (F.candidates || []).length;
  if (F.candidates) announce(n ? `${f.plural(n, "match", "matches")} found.` : "No match found.");
  if (location.hash === "#/find") renderPick(); else go("#/find");
  const t = $("#pick-title");
  if (t) t.focus();
}

// ---------- Researcher 2: pick the person, then optional context ----------

const CTX_FIELDS = ["direction", "include", "exclude", "cv", "proposal"];

function renderPick() {
  const F = S.find;
  if (!F.candidates && !F.error && !F.busy) { go("#/"); return; }
  document.title = "Pick the researcher — Perch";
  const c = F.picked;
  const list = c ? [c] : (F.candidates || []);
  const n = (F.candidates || []).length;
  const title = c ? "Ready to build the brief." : F.busy ? "Searching OpenAlex…"
    : !n ? `No Temple University author matches “${F.searched}”.`
      : n === 1 ? "Is this the right person?" : "Which one is the right person?";
  const sub = c ? "Add anything below to steer it, or build it now."
    : F.busy ? "" : !n ? "Try the name as it appears on papers, or paste an ORCID iD such as 0000-0002-1825-0097."
      : `${f.plural(n, "Temple author", "Temple authors")} in OpenAlex ${n === 1 ? "matches" : "match"}. Nothing runs until you pick one.`;
  const back = c
    ? h("button", { class: "back btn quiet", type: "button", "data-key": "unpick",
      onclick: () => { F.picked = null; renderPick(); const t = $("#pick-title"); if (t) t.focus(); } },
    icon("back"), h("span", { text: "Back to the matches" }))
    : h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" }));
  const again = c ? null : h("form", { role: "search", onsubmit: (e) => { e.preventDefault(); search(); } },
    h("label", { for: "q", class: "sr-only", text: "Find a Temple researcher" }),
    h("div", { class: "searchbox small" },
      h("input", { id: "q", type: "search", value: F.q, autocomplete: "off", oninput: (e) => { F.q = e.target.value; } }),
      h("button", { class: "btn", type: "submit", disabled: F.busy, text: F.busy ? "Searching" : "Search again" })));
  fill(main(), h("div", { class: "screen" },
    back, again,
    h("div", { class: "title-row" },
      h("div", {}, h("h1", { class: "page", id: "pick-title", tabindex: "-1", text: title }),
        sub ? h("p", { class: "page-sub", text: sub }) : null),
      c ? h("button", { class: "btn primary big fade-in", type: "button", "data-key": "build-top", disabled: F.building,
        onclick: () => build(c) }, h("span", { text: F.building ? "Starting" : "Build brief" })) : null),
    F.error ? h("div", { class: "notice error", role: "alert" }, icon("warn"), h("p", { text: F.error })) : null,
    F.busy ? h("div", { class: "shimmer-card" }) : null,
    list.length ? h("ul", { class: "cand-list" }, list.map((x, i) => candidateCard(x, i === 0 && !c && n > 1))) : null,
    c ? contextPanel(c) : null));
}

function candidateCard(c, best) {
  const id = f.shortId(c.id);
  const chosen = S.find.picked === c;
  const temple = (c.institutions || []).some((i) => /temple university/i.test(i));
  const meta = [
    (c.institutions || []).filter((i) => !/temple university/i.test(i)).join(", ") || null,
    c.works_count != null ? `${c.works_count.toLocaleString("en-US")} works` : null,
    c.cited_by_count != null ? `${c.cited_by_count.toLocaleString("en-US")} citations` : null,
    `OpenAlex ${id}`].filter(Boolean);
  return h("li", { class: `cand${chosen ? " chosen fade-in" : best ? " best" : ""}` },
    h("div", { class: "cand-body" },
      h("div", { class: "cand-top" }, h("h2", { text: c.display_name }),
        temple ? h("span", { class: "temple", text: "Temple University" }) : null),
      h("p", { class: "cand-meta2" }, meta.join(" · "),
        c.orcid ? [" · ", h("a", { href: f.safeUrl(c.orcid), target: "_blank", rel: "noopener",
          text: `ORCID ${c.orcid.replace(/^https?:\/\/orcid\.org\//, "")}` })] : null),
      c.topics && c.topics.length ? h("ul", { class: "topics", "aria-label": "OpenAlex topics" },
        c.topics.slice(0, 3).map((t) => h("li", { text: t.display_name }))) : null),
    chosen ? h("span", { class: "picked-mark" }, icon("keep"), h("span", { text: "Selected" }))
      : h("button", { class: "btn outline", type: "button", "data-key": `pick-${id}`,
        onclick: () => { S.find.picked = c; renderPick(); const t = $("#pick-title"); if (t) t.focus(); } },
      h("span", { text: "This is the one" }), h("span", { class: "sr-only", text: `: ${c.display_name}` })));
}

function contextPanel(c) {
  const F = S.find;
  const ok = mode.state.available;
  const set = (k) => (e) => { F[k] = e.target.value; if (F.sample) { F.sample = false; F.sampleEdited = true; drawSampleStatus(); } };
  const docBox = (kind, label, note) => {
    const file = F.files[kind];
    return h("div", { class: "box" },
      h("div", { class: "box-head" }, h("label", { class: "big", for: `ctx-${kind}`, text: label }),
        h("span", { class: "local", text: "Local only" })),
      h("p", { class: "note", id: `ctx-${kind}-note`, text: note }),
      file ? h("p", { class: "added" }, icon("paper"), h("span", { text: `${file.name}, read on this server when you build` }),
        h("button", { class: "btn quiet", type: "button", onclick: () => { delete F.files[kind]; renderPick(); } }, h("span", { text: "Remove" })))
        : h("textarea", { id: `ctx-${kind}`, rows: 6, placeholder: "Paste text here", "aria-describedby": `ctx-${kind}-note`,
          value: F[kind], oninput: set(kind), disabled: !ok }),
      file ? null : h("div", { class: "file-row" },
        h("label", { class: `btn${ok ? "" : " off"}` }, h("span", { text: "Or upload a file" }),
          h("input", { type: "file", class: "sr-only", disabled: !ok, accept: ".txt,.md,.docx,.pdf",
            onchange: (e) => pickFile(kind, e.target.files[0]) })),
        h("span", { class: "hint", text: "Text, Markdown, Word or PDF" })));
  };
  return h("section", { class: "more-panel fade-in", "aria-labelledby": "more-h" },
    h("div", {}, h("h2", { id: "more-h", text: "Tell Perch more (optional)" }),
      h("p", { class: "page-sub", text: "Everything here steers the search and is held in memory for this session only. Your CV and ongoing research stay on local models." })),
    ok ? h("div", { class: "sample-row" },
      h("span", { text: "See what helps most: a sample direction, keywords and draft aims. The sample has no CV, because this is a real researcher." }),
      h("button", { class: "btn outline", type: "button", "data-key": "fill-sample", onclick: fillResearcherSample }, h("span", { text: "Fill with a sample" })),
      h("button", { class: "btn ghost", type: "button", "data-key": "clear-ctx", onclick: () => {
        CTX_FIELDS.forEach((k) => { F[k] = ""; }); F.files = {}; F.sample = false; F.sampleEdited = false; renderPick();
        announce("Cleared.");
      } }, h("span", { text: "Clear" }))) : null,
    h("div", { id: "sample-status" }, sampleStatus()),
    h("div", { class: "box-grid" },
      h("div", { class: "box" },
        h("label", { class: "big", for: "ctx-direction", text: "Where your research is going" }),
        h("textarea", { id: "ctx-direction", rows: 4, maxlength: 1000, placeholder: "A sentence or two", value: F.direction, oninput: set("direction") })),
      h("div", { class: "box" },
        h("label", { class: "big", for: "ctx-include", text: "Keywords to search for" }),
        h("input", { id: "ctx-include", type: "text", placeholder: "Comma-separated", value: F.include, oninput: set("include") }),
        h("label", { class: "big", for: "ctx-exclude", text: "Keywords to leave out" }),
        h("input", { id: "ctx-exclude", type: "text", placeholder: "Comma-separated", value: F.exclude, oninput: set("exclude"),
          "aria-describedby": "exc-hint" }),
        h("p", { class: "note", id: "exc-hint", text: "Opportunities that mention one of these in the title or description are left out." })),
      ok ? docBox("cv", "Your CV", "Checks career-stage rules and past sponsors. It does not steer the search.") : null,
      ok ? docBox("proposal", "Ongoing research or draft proposal", "Draft aims or a summary. This steers the search most.") : null,
      h("div", { class: "box" },
        h("label", { class: "big", for: "ctx-stage", text: "Career stage" }),
        h("select", { id: "ctx-stage", "aria-describedby": "stage-hint", onchange: (e) => { F.stage = e.target.value; } },
          [["", "Not stated"], ["early_stage", "Early-career: early-stage investigator (NIH)"], ["established", "Established investigator"]]
            .map(([v, t]) => h("option", { value: v, selected: F.stage === v, text: t }))),
        h("p", { class: "note", id: "stage-hint", text: "Early-career also shows awards only for early-stage or new investigators. They are marked “You said”, so you can check NIH’s definition." }),
        h("label", { class: "big", for: "ctx-min", text: "Leave out awards smaller than (US dollars)" }),
        h("input", { id: "ctx-min", type: "number", inputmode: "numeric", min: "0", step: "any", placeholder: "Any",
          value: F.minAmount, "aria-describedby": "min-hint", oninput: (e) => { F.minAmount = e.target.value; } }),
        h("p", { class: "note", id: "min-hint", text: "Compared with the award ceiling in each record. Records that state no amount stay in." }),
        h("label", { class: "check" },
          h("input", { type: "checkbox", checked: F.explain, onchange: (e) => { F.explain = e.target.checked; } }),
          h("span", {}, h("b", { text: "Explain each lead" }),
            h("span", { class: "hint", text: " A model writes a short, cited reason for every lead. This is the slow step." }))))),
    h("div", { class: "go-row" },
      h("button", { class: "btn primary big", type: "button", "data-key": "build", disabled: F.building, onclick: () => build(c) },
        h("span", { text: F.building ? "Starting" : "Build brief" })),
      h("span", { class: "hint", text: "Everything above is optional." })));
}

function sampleStatus() {
  if (!S.find.sample) return null;
  return h("p", { class: "sample-status", role: "status" }, h("span", { class: "sample-badge", text: "Sample data" }),
    h("span", { text: "Invented text, labelled SYNTHETIC. Edit it or clear it before you run your own." }));
}

function drawSampleStatus() {
  const box = $("#sample-status");
  if (box) fill(box, sampleStatus());
}

async function fillResearcherSample() {
  const F = S.find;
  try {
    const s = await privApi.sample("researcher");
    Object.assign(F, { direction: s.direction, include: s.include_keywords, exclude: s.exclude_keywords,
      proposal: s.proposal, cv: s.cv, files: {}, sample: true, sampleEdited: false });
    keepFocus(renderPick);
    announce("Filled with a SYNTHETIC sample.");
  } catch (e) { F.error = `The sample could not be loaded: ${e.message}`; renderPick(); }
}

async function pickFile(kind, file) {
  const F = S.find;
  if (!file) return;
  const max = (privateInfo() || {}).max_bytes || 5e6;
  if (file.size > max) { F.error = `That file is larger than ${max / 1e6} MB.`; renderPick(); return; }
  const data = await new Promise((ok, bad) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(",", 2)[1] || "");
    r.onerror = () => bad(new Error("The file could not be read."));
    r.readAsDataURL(file);
  });
  F.files[kind] = { name: file.name, data };
  F[kind] = "";
  renderPick();
  announce(`${file.name} will be read on this server when you build.`);
}

// Order matters (S24): open the session, send the documents, then start the brief. With
// documents in the session the server keeps Cloud off (S23), so Cloud is turned off first.
async function build(c) {
  const F = S.find;
  const req = { author_id: f.shortId(c.id), explain: F.explain };
  const words = (x) => x.split(",").map((w) => w.trim()).filter(Boolean);
  if (F.direction.trim()) req.direction = F.direction.trim();
  if (words(F.include).length) req.include_keywords = words(F.include);
  if (words(F.exclude).length) req.exclude_keywords = words(F.exclude);
  if (F.stage) req.career_stage = F.stage;
  const min = parseFloat(F.minAmount);
  if (Number.isFinite(min) && min > 0) req.min_amount = min;
  const docs = ["cv", "proposal"].map((kind) => (F.files[kind] ? { kind, filename: F.files[kind].name, data: F.files[kind].data }
    : F[kind].trim() ? { kind, text: F[kind].trim() } : null)).filter(Boolean);
  F.building = true; F.error = null;
  keepFocus(renderPick);
  try {
    if (api.mode === "replay") {
      const r = await api.create(req);
      S.startedHere = true;
      S.tab = "routes";
      go(`#/brief/${encodeURIComponent(r.id)}/routes`);
      return;
    }
    await mode.enable(); // every brief is a session (S23); nothing is stored
    if (docs.length && S.cloud && !S.cloudDocs) { await setCloud(false); announce("Cloud is off: documents stay on local models."); }
    const have = (await privApi.session()).documents.map((d) => d.kind);
    for (const kind of ["cv", "proposal"]) if (have.includes(kind)) await privApi.removeDocument(kind);
    for (const d of docs) await privApi.addDocument(d);
    S.hasDocs = docs.length > 0 || have.some((k) => !["cv", "proposal"].includes(k));
    drawSwitch();
    S.sampleBrief = Boolean(F.sample);
    const made = await privApi.create(req);
    S.warm = Boolean(made && made.warm);
    S.startedHere = true;
    S.tab = "routes";
    S.briefId = null; // a new brief in the session: open it fresh
    F.building = false;
    go(`#/brief/${PRIVATE_ID}/routes`);
  } catch (e) {
    F.building = false;
    F.error = `The brief could not start: ${e.message}`;
    renderPick();
    const err = main().querySelector(".notice.error");
    if (err) err.scrollIntoView({ block: "center" });
  }
}

// ----- the status chip and the Local / Cloud dialog (S23 behaviour, S24 design) -----

const cloudInfo = () => (privateInfo() && privateInfo().cloud) || {};

function drawSwitch() {
  const b = $("#status-chip");
  if (!b) return;
  if (!privApi.open) { S.cloud = false; S.hasDocs = false; S.cloudDocs = false; }
  const c = cloudInfo();
  b.querySelector(".chip-word").textContent = S.cloud ? `Cloud: ${c.provider} · nothing stored`
    : S.hasDocs ? "Local only · nothing stored" : "Local · nothing stored";
  b.setAttribute("aria-label", S.cloud ? `Privacy: nothing stored; Cloud on, text goes to ${c.provider}. Change models`
    : "Privacy: nothing stored, local models. Change models");
  document.body.classList.toggle("cloud-on", S.cloud);
  $("#end-session").hidden = !privApi.open;
}

// A real dialog (S24 gap list). resolve(true) on the primary action.
function dialog(build) {
  const d = $("#models-dialog");
  return new Promise((resolve) => {
    const done = (v) => { d.close(); resolve(v); };
    fill(d, build(done));
    d.onclose = () => resolve(false);
    d.oncancel = () => resolve(false);
    d.showModal();
    const first = d.querySelector("[autofocus]") || d.querySelector("input, button");
    if (first) first.focus();
  });
}

async function openModels() {
  const c = cloudInfo();
  if (privApi.open) {
    try { S.hasDocs = (await privApi.session()).documents.length > 0; } catch { S.hasDocs = false; }
  }
  const studentOn = Boolean(S.brief && isStudent(S.brief));
  const docsCloud = S.hasDocs && !studentOn && c.documents; // Q30, behind the server switch
  const blocked = !c.available ? "This server runs local models only."
    : studentOn || (S.hasDocs && !c.documents) ? "Off while this session holds documents: they stay on local models." : "";
  let choice = S.cloud ? "cloud" : "local";
  let understood = false;
  const opener = $("#status-chip");
  const ok = await dialog((done) => {
    const box = h("div", { class: "dialog-in" });
    const draw = () => fill(box,
      h("h2", { id: "models-title", text: "Which models write the text?" }),
      h("p", { class: "hint", text: "Perch stores nothing about you either way. With Cloud on, the provider’s API terms apply to the text it receives. Search, ranking, the rules and Scout always run on this server." }),
      h("div", { role: "radiogroup", "aria-labelledby": "models-title", class: "dialog-opts" },
        h("label", { class: `opt${choice === "local" ? " on" : ""}` },
          h("input", { type: "radio", name: "models", value: "local", checked: choice === "local", autofocus: true,
            onchange: () => { choice = "local"; draw(); } }),
          h("span", {}, h("b", { text: "Local models" }),
            h("span", { text: "Models on this server write the summary, the fit explanations and hand-off openings. Nothing leaves the server." }))),
        h("label", { class: `opt${choice === "cloud" ? " on" : ""}${blocked ? " off" : ""}` },
          h("input", { type: "radio", name: "models", value: "cloud", checked: choice === "cloud", disabled: Boolean(blocked),
            onchange: () => { choice = "cloud"; draw(); } }),
          h("span", {}, h("b", { text: c.provider ? `Cloud: ${c.provider}` : "Cloud" }),
            h("span", { text: blocked || `${c.provider} writes those three texts instead. Faster, but your text leaves this server.` })))),
      choice === "cloud" && !S.cloud ? h("p", { class: "warn-box", role: "note" }, h("b", { text: "Before you turn Cloud on: " }), h("span", { text: c.warning || "" })) : null,
      choice === "cloud" && !S.cloud && docsCloud ? h("div", { class: "warn-box strong", role: "note" },
        h("p", {}, h("b", { text: "Second warning: your documents. " }), h("span", { text: c.documents_warning || "" })),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: understood, "data-key": "docs-understood",
          onchange: (e) => { understood = e.target.checked; draw(); } }),
        h("span", { text: `I understand. Send my documents to ${c.provider}.` }))) : null,
      h("div", { class: "row" },
        h("button", { class: "btn", type: "button", onclick: () => done(false), text: "Cancel" }),
        h("button", { class: "btn primary", type: "button", "data-key": "models-ok", onclick: () => done(true),
          disabled: choice === "cloud" && !S.cloud && docsCloud && !understood,
          text: choice === "cloud" ? (S.cloud ? "Keep Cloud on" : docsCloud ? `Turn Cloud on, with my documents` : "Turn Cloud on") : "Use local models" })));
    draw();
    return box;
  });
  if (opener) opener.focus();
  if (!ok || (choice === "cloud") === S.cloud) return;
  try { await setCloud(choice === "cloud", docsCloud); } catch (e) { announce(e.message); showError(e.message); }
}

function showError(msg) {
  dialog((done) => h("div", { class: "dialog-in", role: "alertdialog", "aria-labelledby": "err-title" },
    h("h2", { id: "err-title", text: "That did not work" }), h("p", { text: msg }),
    h("div", { class: "row" }, h("button", { class: "btn primary", type: "button", autofocus: true, onclick: () => done(true), text: "OK" }))));
}

// Ends the session from any screen, after a dialog that lists what goes.
async function endSession() {
  let docs = [];
  try { docs = (await privApi.session()).documents; } catch { /* already ended */ }
  const list = mode.discards(docs, Boolean(S.briefId === PRIVATE_ID));
  const ok = await mode.disable(() => dialog((done) => h("div", { class: "dialog-in" },
    h("h2", { id: "models-title", text: "End this session?" }),
    h("p", { text: "It discards:" }),
    h("ul", {}, (list.length ? list : ["Nothing yet"]).map((x) => h("li", { text: x }))),
    h("div", { class: "row" },
      h("button", { class: "btn", type: "button", autofocus: true, onclick: () => done(false), text: "Keep working" }),
      h("button", { class: "btn primary", type: "button", "data-key": "end-ok", onclick: () => done(true), text: "End session" })))));
  if (ok) {
    S.cloud = false; S.hasDocs = false; S.sampleBrief = false;
    Object.assign(S.find, { picked: null, files: {}, direction: "", include: "", exclude: "", cv: "", proposal: "", sample: false });
    drawSwitch(); announce("Session ended. Everything in it was discarded."); go("#/");
  }
}

// Cloud on for this session; the dialog above is the warning that names the provider.
async function setCloud(on, withDocs = false) {
  const c = cloudInfo();
  if (on) {
    await mode.enable();
    S.cloudDocs = Boolean((await privApi.cloud(true, c.provider, withDocs ? c.documents_phrase : null)).documents);
  } else {
    S.cloudDocs = false;
    if (privApi.open) await privApi.cloud(false);
  }
  S.cloud = on;
  drawSwitch();
  announce(on ? `Cloud on. ${c.provider} writes the explanations for your next brief.` : "Local models on.");
  return true;
}

// ---------- Brief ----------

function stopPolling() {
  clearTimeout(S.pollTimer);
  S.pollTimer = null;
  S.gen += 1;
}

async function openBrief(id) {
  stopPolling();
  Object.assign(S, { briefId: id, brief: null, open: new Set(), stepsOpen: false,
    failedPolls: 0, seen: { explained: 0, stagesDone: 0 } });
  fill(main(), h("div", { class: "loading" }, owl("work", "owl-md"),
    h("p", { text: "Opening the brief" })));
  await poll();
}

async function poll() {
  const id = S.briefId, gen = S.gen;
  let data;
  try {
    data = await api.brief(id);
  } catch (e) {
    if (gen !== S.gen) return;
    if (e.status === 404) return renderMissing(id, e.message);
    S.failedPolls += 1;
    if (S.failedPolls >= 4 || !S.brief) return renderMissing(id, e.message);
    S.pollTimer = setTimeout(poll, POLL_MS * 2);
    return;
  }
  if (gen !== S.gen) return;
  S.failedPolls = 0;
  const first = !S.brief;
  S.brief = data;
  if (first) renderBrief();
  else updateBrief();
  const st = data.brief.status;
  if (st === "queued" || st === "running") S.pollTimer = setTimeout(poll, POLL_MS);
}

function renderMissing(id, msg) {
  barOwl("worry");
  fill(main(), h("div", { class: "empty" }, owl("worry", "owl-md"),
    h("div", {}, h("p", { class: "lede", text: "This brief could not be opened." }),
      h("p", { class: "hint", text: msg }),
      h("a", { class: "btn", href: "#/" }, icon("back"), h("span", { text: "Find a researcher" })))));
}

const leadsOf = () => (S.brief ? S.brief.leads : []);
const stage = (name) => S.brief.brief.stages.find((s) => s.name === name) || { status: "pending" };
const isDone = (name) => ["done", "skipped"].includes(stage(name).status);
const routeLeads = (r) => leadsOf().filter((l) => (l.route || "A") === r);
const explainedCount = () => routeLeads("A").filter((l) => l.explanation || l.flagged).length;

function renderBrief() {
  const d = S.brief;
  const r = d.researcher || {};
  const student = isStudent(d);
  const name = student ? "Your options" : r.display_name || "Your brief";
  document.title = `${name} — Perch`;
  if (student && !["F", "S"].includes(S.route)) S.route = "F";
  if (!student && !["A", "B"].includes(S.route)) S.route = "A";
  const meta = student ? `Fellowships and sample scholarships, checked against your CV by rule · as of ${f.formatDate(d.brief.options.as_of)}`
    : [...(r.institutions || []), `Brief as of ${f.formatDate(d.brief.options.as_of)}`].join(" · ");
  // Back: a student returns to their documents, a researcher to the matches; the
  // session stays open either way (S22, audit S2).
  const back = student ? h("a", { class: "back", href: "#/student" }, icon("back"), h("span", { text: "Back to your documents" }))
    : h("a", { class: "back", href: S.find.candidates ? "#/find" : "#/" }, icon("back"), h("span", { text: "Back" }));
  const tabs = h("div", { class: `tabs${student ? " student" : ""}`, role: "tablist", "aria-label": "Brief sections" },
    tabButton("routes", student ? "Your options" : "Routes", student ? "Options" : "Routes"),
    tabButton("profile", student ? "What Perch read" : "Profile", student ? "Read" : "Profile"),
    tabButton("compare", "Compare", "Compare"), tabButton("scout", "Ask Scout", "Scout"));
  fill(main(), h("div", { class: "brief screen" }, back,
    h("div", { class: "title-row" },
      h("div", {}, h("h1", { class: "page who", text: name }), h("p", { class: "brief-meta", text: meta })),
      exportMenu()),
    api.mode === "private" && (student ? usedSample() : S.sampleBrief) ? h("p", { class: "notice sample-note", role: "note" },
      h("span", { class: "sample-badge", text: "Sample data" }),
      h("span", { text: student ? " Built from an invented SYNTHETIC student. Nothing here is about you."
        : " This brief was steered by invented SYNTHETIC text. Anything it cites from “your document” is from the sample, not from this researcher." })) : null,
    h("div", { id: "progress" }),
    h("div", { class: "tabs-wrap" }, tabs),
    h("div", { class: "cols" },
      h("div", { class: "main-col" }, h("div", { id: "panel", role: "tabpanel", tabindex: "-1" })),
      h("div", { class: "rail", id: "rail" })),
    h("div", { id: "keep-float" })));
  S.seen.explained = explainedCount();
  S.seen.stagesDone = d.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  S.startedHere = false;
  renderProgress();
  renderTabs();
  renderPanel();
}

// The Export button: a menu with the three exports and, in a session, the mask option.
function exportMenu() {
  let pop;
  if (api.mode === "private") pop = privateBar(api, go);
  else {
    const url = api.exportUrl(S.briefId);
    if (!url) return null;
    pop = h("div", {},
      h("a", { class: "btn quiet", href: api.exportUrl(S.briefId, "html"), target: "_blank", rel: "noopener" },
        icon("paper"), h("span", { text: "Print or save as PDF" })),
      h("a", { class: "btn quiet", href: api.exportUrl(S.briefId, "md"), download: `perch-brief-${S.briefId}.md` },
        icon("download"), h("span", { text: "Markdown" })),
      h("a", { class: "btn quiet", href: url, download: `perch-brief-${S.briefId}.json` },
        icon("download"), h("span", { text: "Records as JSON" })));
  }
  const det = h("details", { class: "export-menu" },
    h("summary", { "data-key": "export" }, icon("download"), h("span", { text: "Export" })),
    h("div", { class: "export-pop" }, pop));
  det.addEventListener("keydown", (e) => { if (e.key === "Escape" && det.open) { det.open = false; det.querySelector("summary").focus(); e.stopPropagation(); } });
  // Only a real click outside closes it: a download clicks a link of its own.
  document.addEventListener("click", (e) => { if (det.open && e.isTrusted && !det.contains(e.target)) det.open = false; });
  return det;
}

function tabButton(key, label, short) {
  return h("button", { role: "tab", id: `tab-${key}`, class: "tab", "aria-controls": "panel", "aria-label": label,
    onclick: () => go(`#/brief/${encodeURIComponent(S.briefId)}/${key}`),
    onkeydown: (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        const tabs = TABS.filter((k) => $(`#tab-${k}`));
        const other = tabs[(tabs.indexOf(key) + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        go(`#/brief/${encodeURIComponent(S.briefId)}/${other}`);
        setTimeout(() => $(`#tab-${other}`).focus(), 0);
      }
    } }, h("span", { class: "tab-label lbl-long", text: label }), h("span", { class: "lbl-short", "aria-hidden": "true", text: short }));
}

function renderTabs() {
  for (const key of TABS) {
    const t = $(`#tab-${key}`);
    if (!t) continue;
    const on = S.tab === key;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
  }
  const kept = leadsOf().filter((l) => l.status === "kept").length;
  const k = $("#tab-compare .tab-label");
  if (k) k.textContent = kept ? `Compare (${kept})` : "Compare";
  const kt = $("#tab-compare");
  if (kt) kt.setAttribute("aria-label", kept ? `Compare, ${kept} kept` : "Compare");
  $("#panel").setAttribute("aria-labelledby", `tab-${S.tab}`);
}

function updateBrief() {
  const ex = explainedCount();
  const done = S.brief.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  const pOwl = $("#progress .owl");
  if (ex > S.seen.explained || done > S.seen.stagesDone) { hop(pOwl); }
  if (done > S.seen.stagesDone) {
    const last = S.brief.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).pop();
    if (last) announce(`${f.STAGES[last.name] || last.name}: done.`);
  }
  S.seen = { explained: ex, stagesDone: done };
  renderProgress();
  renderTabs();
  renderPanel();
}

// ---------- progress: owl, step name, step count, a thin bar in the branch colour ----------

function renderProgress() {
  const b = S.brief.brief;
  const box = $("#progress");
  const stages = b.stages;
  const runningIdx = stages.findIndex((s) => s.status === "running");
  const failedIdx = stages.findIndex((s) => s.status === "failed");
  const doneN = stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  const t0 = Date.parse(stages[0] && stages[0].started_at) || Date.parse(b.created_at);
  const lastEnd = Math.max(...stages.map((s) => Date.parse(s.finished_at) || 0));
  let state = "work", headline, detail, sub = null;
  if (b.status === "failed") {
    state = "droop";
    const s = stages[failedIdx] || {};
    headline = `Stopped at: ${f.STAGES[s.name] || s.name || "a step"}`;
    detail = `${doneN} of ${stages.length} steps`;
    sub = b.error || s.detail || "The server did not say why.";
  } else if (b.status === "done") {
    state = "done";
    headline = "Brief ready";
    detail = S.warm && api.mode === "private" ? `Built when the server started · ${stages.length} of ${stages.length} steps`
      : `Built in ${f.elapsed(lastEnd - t0)} · ${stages.length} of ${stages.length} steps`;
  } else {
    const i = runningIdx >= 0 ? runningIdx : Math.max(stages.findIndex((x) => x.status === "pending"), 0);
    const s = stages[i];
    headline = `${f.STAGES[s.name] || s.name}…`;
    detail = `Step ${i + 1} of ${stages.length}`;
    if (s.name === "explanations" && isDone("route_a")) detail += ` · ${explainedCount()} of ${routeLeads("A").length} explained`;
    if (b.status === "queued") sub = "Waiting for the previous brief to finish.";
  }
  const pct = b.status === "done" ? 100 : (doneN / Math.max(stages.length, 1)) * 100;
  let card = box.querySelector(".pcard");
  if (!card) {
    card = h("section", { class: "pcard", role: "status", "aria-label": "Progress" },
      owl(state, "owl-sm", { button: true, copy: true }),
      h("div", { class: "pcard-main" },
        h("div", { class: "pcard-line" }, h("b", { class: "p-head" }), h("span", { class: "p-detail" })),
        h("div", { class: "pbar", "aria-hidden": "true" }, h("span")),
        h("p", { class: "p-sub hint" })),
      h("div", { class: "p-act" }),
      h("div", { class: "progress-steps" }));
    fill(box, card);
  }
  card.classList.toggle("failed", b.status === "failed");
  setOwl(card.querySelector(".owl"), state);
  card.querySelector(".owl").classList.toggle("bob", b.status === "running" || b.status === "queued");
  card.querySelector(".p-head").textContent = headline;
  card.querySelector(".p-detail").textContent = detail;
  card.querySelector(".pbar > span").style.width = `${pct}%`;
  const subEl = card.querySelector(".p-sub");
  subEl.textContent = sub || "";
  subEl.hidden = !sub;
  fill(card.querySelector(".p-act"),
    b.status === "failed" ? h("button", { class: "btn primary", onclick: rebuild }, h("span", { text: "Build again" })) : null,
    api.mode === "replay" && b.status === "done" ? h("button", { class: "btn link", type: "button", onclick: replayBuild }, h("span", { text: "Replay the build" })) : null);
  const steps = h("details", { class: "steps", open: S.stepsOpen,
    ontoggle: (e) => { S.stepsOpen = e.target.open; } },
  h("summary", { text: `Steps (${doneN} of ${stages.length} done)` }),
  h("ol", {}, stages.map((s) => h("li", { "data-status": s.status },
    h("span", { class: "step-dot", "aria-hidden": "true" }),
    h("span", { class: "step-name" }, h("b", { text: f.STAGES[s.name] || s.name }),
      h("span", { class: "sr-only", text: `, ${stepWord(s.status)}` })),
    h("span", { class: "step-detail", text: stepDetail(s) })))));
  fill(card.querySelector(".progress-steps"), steps);
}

async function replayBuild() {
  const r = await api.create({});
  S.startedHere = true;
  S.briefId = null;
  go(`#/brief/${encodeURIComponent(r.id)}/routes`);
}

function stepWord(st) {
  return { pending: "waiting", running: "in progress", done: "done", skipped: "already on file",
    failed: "failed" }[st] || st;
}

function stepDetail(s) {
  const dur = s.started_at && s.finished_at
    ? ` (${f.elapsed(Date.parse(s.finished_at) - Date.parse(s.started_at))})` : "";
  if (s.status === "skipped") {
    return s.detail === "explanations off" ? "Turned off for this brief"
      : `Already on file: ${s.detail || ""}`;
  }
  if (s.status === "pending") return "Waiting";
  if (s.status === "running") return "In progress";
  return (s.detail || "") + dur;
}

async function rebuild() {
  if (api.mode === "private") { go(isStudent(S.brief) ? "#/student" : S.find.picked ? "#/find" : "#/private"); return; }
  if (api.mode === "replay") replayBuild();
}

// ---------- panels ----------

function renderPanel() {
  if (!S.brief || !$("#panel")) return;
  renderTabs();
  const panel = $("#panel");
  if (panel.dataset.tab !== S.tab) {
    panel.dataset.tab = S.tab;
    panel.dataset.sig = "";
    panel.replaceChildren();
    $("#rail").replaceChildren();
  }
  drawRail();
  if (isStudent(S.brief) && S.tab !== "scout") { renderStudentPanel(panel); return; }
  if (S.tab === "profile") renderProfile(panel);
  else if (S.tab === "compare") drawCompare();
  else if (S.tab === "scout") {
    const sig = `scout:${S.brief.brief.status}`;
    if (panel.dataset.sig !== sig) {  // brief polls do not redraw Scout; Scout redraws itself
      panel.dataset.sig = sig;
      drawScout();
    }
  } else renderRoutes(panel);
}

// The right rail on the list tab: the shortlist card above the evidence panel. Under
// 900 px the rail hides and a floating keep pill takes the shortlist's place.
const KIND_SHORT = { A: "Grant", B: "Industry", F: "Fellowship", S: "Sample" };

function leadTitle(l) {
  return (l.opportunity && l.opportunity.title) || (l.organisation && l.organisation.name)
    || (l.record && (l.record.name || l.record.title)) || l.record_id;
}

function drawRail() {
  const rail = $("#rail");
  if (!rail || !S.brief) return;
  const onList = S.tab === "routes";
  rail.hidden = !onList;
  const kept = leadsOf().filter((l) => l.status === "kept");
  const student = isStudent(S.brief);
  if (onList) {
    let card = rail.querySelector(".shortlist");
    if (!card) {
      card = h("section", { class: "shortlist", "aria-labelledby": "sl-title" });
      const ev = h("aside", { class: "rail-evidence", id: "rail-ev", "aria-label": "Evidence", tabindex: "0" },
        h("p", { class: "ev-kind", text: "Evidence" }),
        h("p", { class: "empty-ev", text: "Pick a title or Evidence on a card to see its record here. Every value is copied from the record." }));
      fill(rail, card, ev);
    }
    const sig = JSON.stringify(kept.map((l) => l.id));
    if (card.dataset.sig !== sig) {
      card.dataset.sig = sig;
      card.classList.toggle("has", kept.length > 0);
      const focusKey = card.contains(document.activeElement) ? "sl-compare" : null;
      fill(card,
        h("div", { class: "shortlist-head" }, h("h2", { id: "sl-title", text: "Your shortlist" }),
          h("span", { text: kept.length ? `${kept.length} kept` : "none yet" })),
        kept.length ? h("ul", {}, kept.map((l) => h("li", { class: "fade-in" },
          h("span", { class: "kind-short", text: KIND_SHORT[l.route || "A"] || "Lead" }),
          h("span", { class: "sl-title", text: leadTitle(l), title: leadTitle(l) }),
          h("button", { class: "x", type: "button", "aria-label": `Remove from shortlist: ${leadTitle(l)}`,
            onclick: () => setLead(l.id, "restore") }, "×"))))
          : h("p", { text: student ? "Keep fellowships or scholarships and they collect here, ready to compare."
            : "Keep grants or industry leads and they collect here, ready to compare and hand off." }),
        h("button", { class: "btn primary", type: "button", "data-key": "sl-compare", disabled: !kept.length,
          onclick: () => go(`#/brief/${encodeURIComponent(S.briefId)}/compare`) },
        h("span", { text: student ? "Compare and draft a note" : "Compare and hand off" })));
      if (focusKey) { const b = card.querySelector(`[data-key="${focusKey}"]`); if (b && !b.disabled) b.focus(); }
    }
  }
  const float = $("#keep-float");
  // Not on Compare (its own place) or Ask Scout, where it would cover the question box.
  const show = kept.length > 0 && (S.tab === "routes" || S.tab === "profile");
  const fsig = show ? String(kept.length) : "";
  if (float.dataset.sig !== fsig) {
    float.dataset.sig = fsig;
    fill(float, show ? h("div", { class: "keep-float fade-in", role: "region", "aria-label": "Kept" },
      h("span", { text: `${kept.length} kept` }),
      h("a", { class: "btn", href: `#/brief/${encodeURIComponent(S.briefId)}/compare`, "data-key": "keep-compare" },
        h("span", { text: "Compare" }))) : null);
  }
}

// ----- Student brief (S18, student.js) -----

function renderStudentPanel(panel) {
  const d = S.brief;
  const sig = JSON.stringify([S.tab, S.route, d.brief.stages.map((s) => s.status),
    d.leads.map((l) => [l.status, Boolean(l.explanation), l.flagged])]);
  if (panel.dataset.sig === sig) return;
  panel.dataset.sig = sig;
  const ctx = { brief: d, route: S.route, papers: d.papers || {}, openEvidence, setLead, announce,
    briefId: S.briefId, setRoute: (r) => { S.route = r; renderPanel(); panelFocus(`route-${r}`); },
    goRoutes: () => go(`#/brief/${encodeURIComponent(S.briefId)}/routes`) };
  if (S.tab === "profile") keepFocus(() => fill(panel, ...studentProfile(d, ctx)));
  else if (S.tab === "compare") studentCompare(panel, ctx);
  else keepFocus(() => studentRoutes(panel, ctx));
}

// ----- Compare -----

const keptIds = () => leadsOf().filter((l) => l.status === "kept").map((l) => l.id).sort();

function drawCompare(focusKey) {
  const panel = $("#panel");
  if (!panel || S.tab !== "compare" || !S.brief) return;
  const kept = keptIds();
  renderCompare(panel, { keptCount: kept.length, openEvidence, redraw: drawCompare, handoff: true,
    goRoutes: () => go(`#/brief/${encodeURIComponent(S.briefId)}/routes`) });
  renderHandoff(panel.querySelector(".handoff-box"), { api, briefId: S.briefId, announce,
    kept: leadsOf().filter((l) => l.status === "kept"), offices: compareOffices(), redraw: drawCompare });
  if (kept.length) loadCompare(api, S.briefId, kept, () => drawCompare());
  if (focusKey) panelFocus(focusKey);
}

function drawScout() {
  const panel = $("#panel");
  if (!panel || S.tab !== "scout" || !S.brief) return;
  renderScout(panel, { api, briefId: S.briefId, done: S.brief.brief.status === "done", student: isStudent(S.brief),
    openEvidence, announce, rerender: drawScout });
}

// ----- Profile -----

function renderProfile(panel) {
  const d = S.brief, b = d.brief;
  const sig = JSON.stringify([b.summary, b.topics, b.threads.length, d.awards.length,
    Object.keys(d.papers || {}).length, b.stages.map((s) => s.status)]);
  if (panel.dataset.sig === sig) return;
  panel.dataset.sig = sig;
  const card = (sec) => { if (sec) sec.classList.add("pblock"); return sec; };
  keepFocus(() => fill(panel, h("div", { class: "prof-cols" },
    h("div", { class: "left" }, card(youSaidSection()), card(summarySection()), card(threadsSection())),
    h("div", { class: "right" }, card(horizonSection()), card(keyPapersSection())))));
}

// The most cited of the researcher's papers in this brief, one row per title.
function keyPapersSection() {
  const d = S.brief;
  if (!isDone("profile")) return h("section", { class: "block" }, h("h2", { class: "section-title", text: "Key papers" }), skeleton(3));
  const all = distinctPapers(Object.values(d.papers || {}).filter((w) => !w.private));
  if (!all.length) return null;
  const top = [...all].sort((a, b) => (b.cited_by_count || 0) - (a.cited_by_count || 0)
    || (b.publication_year || 0) - (a.publication_year || 0)).slice(0, 5);
  return h("section", { class: "block" },
    h("h2", { class: "section-title" }, h("span", { text: "Key papers" }), h("span", { class: "hint", text: `${top.length} of ${all.length}, most cited first` })),
    h("ul", { class: "papers" }, top.map(paperRow)));
}

// Normal-mode context (Q16): what the user typed on Find, shown as theirs, never as a fact.
function youSaidSection() {
  const o = S.brief.brief.options;
  const rows = [
    o.direction ? ["Direction", o.direction] : null,
    o.include_keywords && o.include_keywords.length ? ["Search for", o.include_keywords.join(", ")] : null,
    o.exclude_keywords && o.exclude_keywords.length ? ["Leave out", o.exclude_keywords.join(", ")] : null,
    o.career_stage ? ["Career stage", o.career_stage === "early_stage" ? "Early-stage investigator (NIH)" : "Established investigator"] : null,
  ].filter(Boolean);
  if (!rows.length) return null;
  return h("section", { class: "block you-said" },
    h("h2", { class: "section-title", text: "You said" }),
    h("p", { class: "hint", text: "These steer the search. Perch does not check them, and no explanation cites them." }),
    h("dl", { class: "fields" }, rows.map(([k, v]) => field(k, v))));
}

function summarySection() {
  const b = S.brief.brief;
  const st = stage("summary");
  let body;
  if (b.summary) {
    body = [h("p", { class: "summary" }, renderSegs(citedOnly(f.segments(b.summary)))),
      b.topics.length ? h("ul", { class: "chips", "aria-label": "Topics" },
        b.topics.map((t) => h("li", { class: "chip", text: t }))) : null,
      h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Model text" }),
        h("span", { text: "Written by a model and checked against the papers it cites." }))];
  } else if (st.status === "skipped") {
    body = [h("p", { class: "hint", text: "The model summary is turned off for this brief. The threads below come from the papers alone." }), openAlexTopics()];
  } else if (st.status === "done" || st.status === "failed") {
    body = [h("p", { class: "notice warn" }, icon("warn"), h("span", {
      text: "The summary was withheld because it failed the citation checks twice. The threads below come from the papers alone." })),
    openAlexTopics()];
  } else {
    body = [skeleton(2), h("p", { class: "hint", text: "The summary is written after the search for leads." })];
  }
  return h("section", { class: "block" }, h("h2", { class: "section-title" }, h("span", { text: "Summary" }),
    h("span", { class: "hint", text: "Written by a model, checked against the papers" })), body);
}

// A chip only for a paper in this brief. Any other id is dropped, so the summary never
// shows a bare record id or offers a record that cannot be opened (S22 review, S25 review).
function citedOnly(segs) {
  const papers = S.brief.papers || {};
  return segs.filter((x) => typeof x === "string" || papers[x.cite] || papers[`https://openalex.org/${x.cite}`]);
}

function openAlexTopics() {
  const t = (S.brief.researcher || {}).topics || [];
  return t.length ? [h("ul", { class: "chips", "aria-label": "OpenAlex topics" },
    t.slice(0, 5).map((x) => h("li", { class: "chip", text: x.display_name }))),
  h("p", { class: "provenance" }, h("span", { text: "Topics as OpenAlex lists them." }))] : null;
}

function horizonSection() {
  if (String(S.brief.brief.researcher_id).startsWith("private:")) return null; // no public profile
  const d = S.brief, b = d.brief;
  const title = h("h2", { class: "section-title", text: "Award horizon" });
  if (!isDone("awards")) return h("section", { class: "block" }, title, skeleton(1));
  if (!d.awards.length) {
    return h("section", { class: "block" }, title, h("p", { class: "lede", text:
      "No public NIH or NSF award was found for this researcher." }),
    h("p", { class: "hint", text: "That says nothing about other funding. Perch only reads public federal award records." }));
  }
  const asOf = b.options.as_of;
  const left = b.award_horizon ? f.daysBetween(asOf, b.award_horizon) : null;
  return h("section", { class: "block horizon" }, title,
    h("p", { class: "horizon-date" },
      h("span", { class: "big", text: b.award_horizon ? f.formatDate(b.award_horizon) : "Not stated" }),
      left !== null ? h("span", { class: "hint", text: left < 0 ? "already passed" : f.until(left) }) : null),
    h("p", { class: "hint", text:
      `The end date of the last public federal award found, out of ${f.plural(d.awards.length, "award")}. Nothing about lab finances is inferred.` }),
    h("p", { class: "legend", "aria-hidden": "true" },
      h("span", { class: "key active" }), h("span", { text: "Running at the brief date" }),
      h("span", { class: "key now" }), h("span", { text: "Brief date" })),
    awardTimeline(d.awards, asOf));
}

function awardTimeline(awards, asOf) {
  const rows = [...awards].sort((a, b) => (b.end_date || "").localeCompare(a.end_date || ""));
  const ts = rows.flatMap((a) => [a.start_date, a.end_date]).filter(Boolean).map((x) => f.parseDate(x).getTime());
  const now = f.parseDate(asOf).getTime();
  const lo = Math.min(...ts, now), hi = Math.max(...ts, now);
  const span = Math.max(hi - lo, 1);
  const x = (iso) => ((f.parseDate(iso).getTime() - lo) / span) * 100;
  const yr = (t) => new Date(t).getUTCFullYear();
  const SHOW = 5;
  const item = (a) => {
    const active = a.end_date && a.end_date >= asOf;
    return h("li", { class: `award${active ? " active" : ""}` },
      h("button", { class: "award-btn", "data-key": `award-${a.key}`,
        onclick: (e) => openEvidence(a.record_id || a.key, e.currentTarget) },
        h("span", { class: "award-top" },
          h("span", { class: "award-num", text: `${a.agency} ${a.award_number}` }),
          h("span", { class: "award-dates", text: `${f.formatDate(a.start_date)} to ${f.formatDate(a.end_date)}` })),
        h("span", { class: "award-title", text: a.title }),
        a.matched_by_initial ? h("span", { class: "tag ember award-initial", text: "Matched by initial: check it is yours" }) : null,
        a.start_date && a.end_date ? h("span", { class: "span-bar", "aria-hidden": "true" },
          h("span", { class: "bar-now", style: `left:${x(asOf)}%` }),
          h("span", { class: "bar-fill", style: `left:${x(a.start_date)}%;width:${Math.max(x(a.end_date) - x(a.start_date), 1.5)}%` })) : null));
  };
  return h("div", { class: "timeline" },
    h("p", { class: "axis", "aria-hidden": "true" }, h("span", { text: String(yr(lo)) }),
      h("span", { text: String(yr(hi)) })),
    h("ul", { class: "awards" }, rows.slice(0, SHOW).map(item)),
    rows.length > SHOW ? h("details", { class: "more" },
      h("summary", { text: `Show ${rows.length - SHOW} earlier awards` }),
      h("ul", { class: "awards" }, rows.slice(SHOW).map(item))) : null);
}

function threadsSection() {
  const d = S.brief, b = d.brief;
  const title = h("h2", { class: "section-title", text: "Research threads" });
  if (!isDone("profile")) return h("section", { class: "block" }, title, skeleton(3));
  return h("section", { class: "block" }, title,
    h("p", { class: "hint", text: b.work_ids.length
      ? `${f.plural(b.work_ids.length, "paper")} grouped by what they are about. Labels are the words that set each group apart.`
      : "No public papers: each private document is one thread. Labels are its most frequent words." }),
    h("ol", { class: "threads" }, b.threads.map((t) => {
      const papers = distinctPapers((t.work_ids || []).map((id) => d.papers[id]).filter(Boolean)).slice(0, 5);
      const meter = h("span", { class: "meter", "aria-hidden": "true" },
        h("span", { style: `width:${Math.max(t.weight * 100, 2)}%` }));
      if (t.private || t.said) {
        return h("li", { class: `thread${t.private ? " private" : " said"}` },
          h("div", { class: "thread-head" },
            h("h3", { text: t.label }),
            h("span", { class: "share", text: `${Math.round(t.weight * 100)}% of the search` })),
          meter,
          h("p", { class: "hint", text: t.private ? "From your private document. Used as a search query only."
            : "From what you said. Used as a search query, never as a fact." }),
          h("ul", { class: "papers" }, papers.map(paperRow)));
      }
      return h("li", { class: "thread" },
        h("div", { class: "thread-head" },
          h("h3", { text: t.label }),
          h("span", { class: "share", text: `${Math.round(t.weight * 100)}% of recent work` })),
        meter,
        h("p", { class: "hint", text: `${f.plural(t.work_ids.length, "paper")}. Most recent first:` }),
        h("ul", { class: "papers" }, papers.map(paperRow)));
    })));
}

// One row per paper title: OpenAlex often lists a journal article and its preprints as
// separate works. The journal version wins over an arXiv copy (S22, audit S4).
function distinctPapers(works) {
  const norm = (w) => String(w.title || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  // Short generic titles ("Correction", "Editorial") are different works: never merged.
  const key = (w) => (norm(w).split(" ").length >= 4 ? norm(w) : w.id);
  const preprint = (w) => /arxiv|biorxiv|medrxiv|preprint/i.test(w.venue || "");
  const seen = new Map();
  for (const w of works) {
    const k = key(w);
    if (!seen.has(k)) seen.set(k, w);
    else if (preprint(seen.get(k)) && !preprint(w)) seen.set(k, w);
  }
  return [...seen.values()];
}

function paperRow(w) {
  return h("li", {}, h("button", { class: "paper", "data-key": `paper-${w.id}`, onclick: (e) => openEvidence(w.id, e.currentTarget) },
    w.private ? lockLabel() : null,
    h("span", { class: "paper-title", text: w.title }),
    h("span", { class: "paper-meta", text: [w.publication_year, w.venue].filter(Boolean).join(", ") })));
}

function skeleton(lines) {
  return h("div", { class: "skeleton", "aria-hidden": "true" },
    Array.from({ length: lines }, (_, i) => h("span", { style: `width:${92 - i * 17}%` })));
}

// ----- Routes -----

function sortedLeads() {
  const leads = [...routeLeads(S.route)];
  if (S.route === "B") return leads.sort((a, b) => a.rank - b.rank);
  const close = (l) => (l.opportunity && l.opportunity.close_date) || "9999";
  if (S.sort === "closing") leads.sort((a, b) => close(a).localeCompare(close(b)) || a.rank - b.rank);
  else if (S.sort === "fit") leads.sort((a, b) => (b.fit_score ?? -1) - (a.fit_score ?? -1) || a.rank - b.rank);
  else leads.sort((a, b) => a.rank - b.rank);
  return leads;
}

// Grants and industry leads sit side by side as two equal routes; a switch picks one.
function routeSwitch() {
  const n = (r) => routeLeads(r).filter((l) => l.status !== "dismissed").length;
  const btn = (r, label) => {
    const ready = isDone(r === "A" ? "route_a" : "route_b");
    return h("button", { class: "route-btn", "data-key": `route-${r}`, "aria-pressed": String(S.route === r),
      onclick: () => { S.route = r; renderPanel(); panelFocus(`route-${r}`); } },
    h("span", { text: label }), ready ? h("span", { class: "route-n", text: String(n(r)) }) : null);
  };
  return h("div", { class: "route-switch", role: "group", "aria-label": "Route" },
    btn("A", "Grants"), btn("B", "Industry"));
}

// The sort order as the same segmented pill as Grants | Industry, smaller (S27).
const SORTS = [["order", "Perch’s order"], ["closing", "Closing soon"], ["fit", "Fit estimate"]];

function sortSwitch() {
  return h("div", { class: "route-switch sort-switch", role: "group", "aria-label": "Sort leads by" },
    ...SORTS.map(([v, label]) => h("button", { class: "route-btn", "data-key": `sort-${v}`,
      "aria-pressed": String(S.sort === v),
      onclick: () => { S.sort = v; renderPanel(); panelFocus(`sort-${v}`); } }, label)));
}

function updateSwitch(panel) {
  for (const r of ["A", "B"]) {
    const el = panel.querySelector(`[data-key="route-${r}"] .route-n`);
    if (el) el.textContent = String(routeLeads(r).filter((l) => l.status !== "dismissed").length);
  }
}

function panelFocus(key) {
  const el = document.querySelector(`#panel [data-key="${key}"]`);
  if (el) el.focus();
}

function renderRoutes(panel) {
  if (S.route === "B") { renderIndustry(panel); return; }
  if (!isDone("route_a")) {
    const failed = S.brief.brief.status === "failed";
    const sig = `wait:${failed}`;
    if (panel.dataset.sig === sig) return;
    panel.dataset.sig = sig;
    fill(panel, routeSwitch(), h("div", { class: "empty" }, owl(failed ? "droop" : "look", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: failed ? "The search for leads did not run."
        : "Leads appear here when the search finishes." }),
      h("p", { class: "hint", text: failed ? "See the steps above for what stopped."
        : "The profile tab fills in first." }))), skeleton(3), skeleton(3));
    return;
  }
  const leads = sortedLeads();
  const active = leads.filter((l) => l.status !== "dismissed");
  const dismissed = leads.filter((l) => l.status === "dismissed");
  const kept = leadsOf().filter((l) => l.status === "kept").length;
  const explaining = stage("explanations").status === "running" || stage("explanations").status === "pending";

  const sig = `routes:${isDone("route_b")}`;
  if (panel.dataset.sig !== sig) {
    panel.dataset.sig = sig;
    fill(panel, routeSwitch(),
      h("div", { class: "routes-bar" },
        h("div", {}, h("h2", { class: "section-title", id: "routes-title" }),
          h("p", { class: "hint routes-sub" })),
        sortSwitch()),
      h("ol", { class: "leads", "aria-labelledby": "routes-title" }),
      h("div", { class: "dismissed-box" }),
      h("div", { class: "keep-bar-box" }));
  }
  renderKeepBar(panel.querySelector(".keep-bar-box"), kept);
  updateSwitch(panel);
  for (const b of panel.querySelectorAll(".sort-switch button")) {
    b.setAttribute("aria-pressed", String(b.dataset.key === `sort-${S.sort}`));
  }
  panel.querySelector("#routes-title").textContent = `${f.plural(active.length, "open opportunity", "open opportunities")}`;
  const subBits = [];
  if (kept) subBits.push(`${kept} kept`);
  if (explaining && S.brief.brief.options.explain) subBits.push(`${explainedCount()} of ${routeLeads("A").length} explained so far`);
  // The order is the pipeline's, which the back-test measures; the fit number is a
  // separate model estimate, so the two can disagree (S22, audit M4).
  subBits.push(S.sort === "fit" ? "Sorted by the model’s fit estimate, which is not the odds of funding"
    : S.sort === "closing" ? "Sorted by closing date"
      : "In Perch’s order: how closely each record’s text matches the papers. Fit is a separate model estimate, not the odds of funding, so the two can disagree");
  panel.querySelector(".routes-sub").textContent = `${subBits.join(". ")}.`;

  if (!leads.length) {
    fill(panel.querySelector(".leads"), h("li", { class: "empty" }, owl("worry", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: "No open opportunity passed the eligibility check." }),
        h("p", { class: "hint", text: stage("route_a").detail || "" }))));
    return;
  }
  syncList(panel.querySelector(".leads"), active);
  const box = panel.querySelector(".dismissed-box");
  if (!dismissed.length) { box.replaceChildren(); return; }
  let det = box.querySelector("details");
  if (!det) {
    det = h("details", { class: "dismissed" }, h("summary"), h("ol", { class: "leads" }));
    fill(box, det);
  }
  det.querySelector("summary").textContent = `Dismissed (${dismissed.length})`;
  syncList(det.querySelector("ol"), dismissed);
}

// Route B: companies with two or more kinds of public signal. Every sentence and count
// is written by code from the records; the card says it is an inference.
function renderIndustry(panel) {
  const st = stage("route_b");
  if (!S.brief.brief.stages.some((x) => x.name === "route_b")) {
    if (panel.dataset.sig === "oldB") return;
    panel.dataset.sig = "oldB";
    fill(panel, routeSwitch(), h("div", { class: "empty" }, owl("look", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: "This brief was built before Perch had industry leads." }),
        h("button", { class: "btn primary", onclick: rebuild }, h("span", { text: "Build again" })))));
    return;
  }
  if (!isDone("route_b")) {
    const failed = st.status === "failed" || S.brief.brief.status === "failed";
    const sig = `waitB:${failed}`;
    if (panel.dataset.sig === sig) return;
    panel.dataset.sig = sig;
    fill(panel, routeSwitch(), h("div", { class: "empty" }, owl(failed ? "droop" : "look", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: failed ? "The search for industry leads did not run."
        : "Industry leads appear here when that step finishes." }),
      h("p", { class: "hint", text: failed ? (st.detail || "See the steps above for what stopped.")
        : "Grant leads come first." }))), skeleton(3));
    return;
  }
  const leads = sortedLeads();
  const active = leads.filter((l) => l.status !== "dismissed");
  const dismissed = leads.filter((l) => l.status === "dismissed");
  const kept = leadsOf().filter((l) => l.status === "kept").length;
  if (panel.dataset.sig !== "industry") {
    panel.dataset.sig = "industry";
    fill(panel, routeSwitch(),
      h("div", { class: "routes-bar" }, h("div", {}, h("h2", { class: "section-title", id: "routes-title" }),
        h("p", { class: "notice warn infer-note" }, icon("warn"), h("span", {
          text: "Inferred from public signals; not verified. A company that cites or works near your "
            + "research may have no interest in funding it. SBIR/STTR covers NIH awards only." })))),
      h("ol", { class: "leads", "aria-labelledby": "routes-title" }),
      h("div", { class: "dismissed-box" }),
      h("div", { class: "keep-bar-box" }));
  }
  renderKeepBar(panel.querySelector(".keep-bar-box"), kept);
  updateSwitch(panel);
  panel.querySelector("#routes-title").textContent = f.plural(active.length, "industry lead");
  if (!leads.length) {
    fill(panel.querySelector(".leads"), h("li", { class: "empty" }, owl("worry", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: "No company showed two kinds of public signal." }),
        h("p", { class: "hint", text: st.detail || "" }))));
    return;
  }
  syncList(panel.querySelector(".leads"), active);
  const box = panel.querySelector(".dismissed-box");
  if (!dismissed.length) { box.replaceChildren(); return; }
  let det = box.querySelector("details");
  if (!det) {
    det = h("details", { class: "dismissed" }, h("summary"), h("ol", { class: "leads" }));
    fill(box, det);
  }
  det.querySelector("summary").textContent = `Dismissed (${dismissed.length})`;
  syncList(det.querySelector("ol"), dismissed);
}

function sigRec(r) {
  return h("li", {}, h("button", { class: "paper-ref", "data-key": `rec-${r.id}`, onclick: (e) => openEvidence(r.id, e.currentTarget) },
    h("span", { class: "paper-ref-title", text: r.title || r.id }),
    h("span", { class: "paper-meta", text: [r.date ? f.formatDate(r.date) : null, r.venue].filter(Boolean).join(", ") })));
}

function orgCard(l) {
  const o = l.organisation || {};
  const name = o.name || l.record_id;
  const papers = S.brief.papers || {};
  const head = h("div", { class: "lead-head" },
    h("span", { class: "tags" },
      l.relationship ? h("span", { class: "tag", text: l.relationship }) : null,
      l.status === "kept" ? h("span", { class: "tag moss", text: "Kept" }) : null),
    h("span", { class: `evidence-level ${l.confidence || ""}`, text: l.confidence === "stronger"
      ? "Three kinds of signal" : "Two kinds of signal" }));
  const signals = h("ul", { class: "signals" }, (l.signal_items || []).map((s) => h("li", {},
    h("h4", { class: "mini", text: SIGNALS[s.kind] || s.kind }),
    h("p", { text: s.text }),
    // The newest record shows; the rest fold, so a card fits a phone screen (S22, audit S7).
    s.records.length ? h("ul", { class: "sig-recs" }, sigRec(s.records[0])) : null,
    s.records.length > 1 ? h("details", { class: "sig-more" },
      h("summary", { text: `Show ${s.records.length - 1} more` }),
      h("ul", { class: "sig-recs" }, s.records.slice(1).map(sigRec))) : null,
    s.more ? h("p", { class: "hint", text: `and ${s.more} more in the export` }) : null)));
  const cited = (l.cited_ids || []).filter((c) => c.startsWith("W"));
  const yours = cited.length ? h("details", { class: "why" },
    h("summary", { "data-key": "why" }, h("span", { text: "Your papers they cite" }),
      h("span", { class: "hint", text: ` ${cited.length}` })),
    h("ul", { class: "findings" }, cited.map((c) => h("li", {}, paperRef(c, papers))))) : null;
  const evid = h("button", { class: "btn quiet", "data-key": "evidence",
    onclick: (e) => openEvidence(l.record_id, e.currentTarget) }, icon("evidence"), h("span", { class: "narrow-hide", text: "Evidence" }));
  const actions = l.status === "dismissed"
    ? [h("button", { class: "btn", "data-key": "restore", onclick: () => setLead(l.id, "restore") },
      icon("restore"), h("span", { text: "Restore" })), evid]
    : [h("button", { class: `btn keep${l.status === "kept" ? " on" : ""}`, "data-key": "keep",
      "aria-pressed": String(l.status === "kept"),
      onclick: () => setLead(l.id, l.status === "kept" ? "restore" : "keep") },
    icon("keep"), h("span", { text: l.status === "kept" ? "Kept" : "Keep" })),
    h("button", { class: "btn", "data-key": "dismiss", onclick: () => setLead(l.id, "dismiss") },
      icon("dismiss"), h("span", { text: "Dismiss" })), evid];
  for (const b of actions) b.setAttribute("aria-describedby", `t-${cssId(l.id)}`);
  return h("li", { class: `card lead org${l.status === "kept" ? " kept" : ""}${l.status === "dismissed" ? " gone" : ""}`,
    "data-id": l.id },
  head,
  h("h3", { class: "lead-title" }, h("button", { class: "title-btn", "data-key": "title", id: `t-${cssId(l.id)}`,
    onclick: (e) => openEvidence(l.record_id, e.currentTarget) }, h("span", { text: name }))),
  o.aliases && o.aliases.length > 1 ? h("p", { class: "opp-num", text: `Counts ${o.aliases.length} records under this name` }) : null,
  h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Inference" }),
    h("span", { text: l.inference || "Inferred from public signals; not verified." })),
  signals, yours, h("div", { class: "actions" }, actions));
}

// The old keep bar (S8) became the shortlist rail and the floating pill (S24).
function renderKeepBar() { drawRail(); }

// Keyed update: a card is rebuilt only when its data changed, so focus and open
// sections survive polling.
function syncList(ol, leads) {
  const have = new Map([...ol.children].filter((c) => c.dataset.id).map((c) => [c.dataset.id, c]));
  const want = new Set(leads.map((l) => l.id));
  for (const [id, el] of have) if (!want.has(id)) el.remove();
  leads.forEach((l, i) => {
    const sig = JSON.stringify([l.status, l.fit_score, l.explanation, l.inference, l.flagged,
      l.unsupported, l.cited_ids.length, isPending(l)]);
    let el = have.get(l.id);
    if (!el || el.dataset.sig !== sig) {
      const focusKey = el && el.contains(document.activeElement)
        ? document.activeElement.dataset.key : null;
      const fresh = l.route === "B" ? orgCard(l) : leadCard(l);
      fresh.dataset.sig = sig;
      if (el) el.replaceWith(fresh); else ol.append(fresh);
      if (el && l.explanation && !el.querySelector(".why")) fresh.classList.add("landed");
      el = fresh;
      if (focusKey) { const t = el.querySelector(`[data-key="${focusKey}"]`); if (t) t.focus(); }
    }
    if (ol.children[i] !== el) ol.insertBefore(el, ol.children[i] || null);
  });
}

function cssId(s) {
  return String(s).replace(/[^A-Za-z0-9_-]/g, "_");
}

function isPending(l) {
  return !l.explanation && !l.flagged && Boolean(S.brief.brief.options.explain)
    && !isDone("explanations") && S.brief.brief.status !== "failed";
}

function leadCard(l) {
  const o = l.opportunity || {};
  const days = f.daysBetween(api.mode === "replay" ? S.brief.brief.options.as_of : today(), o.close_date);
  const urg = f.urgency(days);
  const size = f.awardSize(o);
  const band = f.fitBand(l.fit_score);
  const pending = isPending(l);
  const parsed = f.parseExplanation(l.explanation, l.cited_ids);

  let fit;
  if (band) {
    fit = h("span", { class: `fit ${band.key}` },
      h("span", { class: "fit-k", text: "Fit estimate" }),
      h("span", { text: band.word }), h("b", { text: String(Math.round(l.fit_score)) }),
      h("span", { class: "sr-only", text: " out of 100, a model’s estimate, not the odds of funding" }));
  } else if (pending) {
    fit = h("span", { class: "fit pending" }, owl("work", "owl-xs"), h("span", { text: "Reading" }));
  }

  const head = h("div", { class: "lead-head" },
    h("span", { class: "tags" },
      h("span", { class: "tag", text: f.agencyShort(o.agency, o.parent_agency) }),
      o.activity_code ? h("span", { class: "tag", text: o.activity_code }) : null,
      o.status && o.status !== "posted" ? h("span", { class: "tag ember", text: o.status === "forecasted" ? "Forecast" : o.status }) : null,
      l.status === "kept" ? h("span", { class: "tag moss", text: "Kept" }) : null),
    fit);

  const facts = h("dl", { class: `facts${size ? "" : " one"}` },
    h("div", { class: `fact close ${urg}` }, h("dt", { text: "Closes" }),
      h("dd", {}, o.close_date ? h("span", { text: f.formatDate(o.close_date) }) : h("span", { class: "missing", text: "Not stated in the record" }),
        // NSF dates its open-anytime programs decades out; the record's words say so.
        o.close_date_note && days !== null && days > 3650 ? h("span", { class: "rel", text: o.close_date_note })
          : days !== null ? h("span", { class: "rel", text: f.closesIn(days) }) : null)),
    size ? h("div", { class: "fact" }, h("dt", { text: "Award size" }), h("dd", {}, h("span", { text: size }))) : null);
  const noSize = size ? null : h("p", { class: "hint no-size", text: "Award size: not stated in the record." });

  let explain = null;
  if (l.flagged) {
    explain = h("p", { class: "notice warn" }, icon("warn"), h("span", {
      text: "The explanation was withheld because it failed the citation checks twice. The fields above are copied from the record." }));
  } else if (pending) {
    explain = h("div", { class: "writing" }, skeleton(2), h("p", { class: "hint", text: "Writing a cited explanation" }));
  } else if (parsed) {
    explain = explanationBlock(l, parsed, o);
  }

  const evid = h("button", { class: "btn quiet", "data-key": "evidence",
    onclick: (e) => openEvidence(l.record_id, e.currentTarget) }, icon("evidence"), h("span", { class: "narrow-hide", text: "Evidence" }));
  let actions;
  if (l.status === "dismissed") {
    actions = [h("button", { class: "btn", "data-key": "restore", onclick: () => setLead(l.id, "restore") },
      icon("restore"), h("span", { text: "Restore" })), evid];
  } else {
    actions = [
      h("button", { class: `btn keep${l.status === "kept" ? " on" : ""}`, "data-key": "keep",
        "aria-pressed": String(l.status === "kept"),
        onclick: () => setLead(l.id, l.status === "kept" ? "restore" : "keep") },
      icon("keep"), h("span", { text: l.status === "kept" ? "Kept" : "Keep" })),
      h("button", { class: "btn", "data-key": "dismiss", onclick: () => setLead(l.id, "dismiss") },
        icon("dismiss"), h("span", { text: "Dismiss" })),
      evid];
  }

  for (const b of actions) b.setAttribute("aria-describedby", `t-${cssId(l.id)}`);
  return h("li", { class: `card lead${l.status === "kept" ? " kept" : ""}${l.status === "dismissed" ? " gone" : ""}`,
    "data-id": l.id },
  head,
  h("h3", { class: "lead-title" }, h("button", { class: "title-btn", "data-key": "title", id: `t-${cssId(l.id)}`,
    onclick: (e) => openEvidence(l.record_id, e.currentTarget) }, h("span", { text: o.title || l.record_id }))),
  h("p", { class: "opp-num", text: o.opportunity_number || "" }),
  facts, noSize, leadNotes(l), explain, h("div", { class: "actions" }, actions));
}

// Rule notes written by code: a career-stage unlock, a past sponsor, what the user said.
function leadNotes(l) {
  if (!l.notes || !l.notes.length) return null;
  return h("ul", { class: "lead-notes" }, l.notes.map((n) => h("li", {},
    /\(private\)/.test(n) ? lockLabel("Private") : h("span", { class: "tag", text: "Rule" }),
    h("span", { text: ` ${n}` }))));
}

function explanationBlock(l, parsed, o) {
  const papers = S.brief.papers || {};
  if (parsed.raw) {
    return h("div", { class: "explain" }, modelTag(),
      h("p", { class: "what" }, renderSegs(parsed.raw, ownIds(o))), inferenceBox(l, o));
  }
  const open = S.open.has(l.id);
  const why = h("details", { class: "why", open,
    ontoggle: (e) => { if (e.target.open) S.open.add(l.id); else S.open.delete(l.id); } },
  h("summary", { "data-key": "why" }, h("span", { text: (l.fit_score ?? 100) < 30 ? "How it relates" : "Why it fits" }),
    h("span", { class: "hint", text: ` cites ${f.plural(parsed.findings.length, "paper")} by the researcher` })),
  h("h4", { class: "mini", text: "From the researcher’s papers" }),
  h("ul", { class: "findings" }, parsed.findings.map((x) => h("li", {},
    paperRef(x.paper, papers), h("p", { text: `${x.text}.` })))),
  inferenceBox(l, o),
  l.unsupported && l.unsupported.length ? h("div", { class: "notice warn" }, icon("warn"),
    h("div", {}, h("p", { text: "This statement could not be matched to its source:" }),
      h("ul", {}, l.unsupported.map((u) => h("li", { text: u }))))) : null,
  eligibilityRows(o));
  return h("div", { class: "explain" }, modelTag(),
    h("p", { class: "what" }, renderSegs(parsed.opportunity, ownIds(o))), why);
}

function modelTag() {
  return h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Model text" }),
    h("span", { text: "Checked against the records it cites." }));
}

function ownIds(o) {
  return new Set([o.opportunity_number].filter(Boolean));
}

function inferenceBox(l, o = {}) {
  if (!l.inference) return null;
  return h("div", { class: "inference" },
    h("p", { class: "inference-label" }, h("span", { class: "tag model", text: "Inference" }),
      h("span", { text: "A model’s reading of the fit, not a fact from a record." })),
    h("p", {}, renderSegs(f.segments(l.inference, new Set(l.cited_ids)), ownIds(o))));
}

function eligibilityRows(o) {
  const rows = f.higherEdRows(o.eligible_applicants);
  if (!rows.length) return null;
  return h("div", { class: "elig" }, h("h4", { class: "mini", text: "Eligible applicants include" }),
    h("ul", {}, rows.map((r) => h("li", { text: r }))));
}

// Citation chips stay on one line with the punctuation after them. A card's citation
// of its own opportunity is dropped: the card is that record.
function renderSegs(segs, skip = new Set()) {
  const papers = S.brief.papers || {};
  const out = [];
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    if (typeof s === "string") { out.push(s); continue; }
    if (skip.has(s.cite)) {
      if (typeof out[out.length - 1] === "string") out[out.length - 1] = out[out.length - 1].replace(/\s+$/, "");
      continue;
    }
    const next = segs[i + 1];
    const m = typeof next === "string" ? next.match(/^[.,;:)]+/) : null;
    if (m) segs[i + 1] = next.slice(m[0].length);
    out.push(cite(s.cite, papers), m ? m[0] : null);
  }
  return out;
}

function paperRef(id, papers) {
  const w = papers[`https://openalex.org/${id}`] || papers[id];
  return h("button", { class: `paper-ref${w && w.private ? " private" : ""}`, "data-key": `cite-${id}`,
    onclick: (e) => openEvidence(id, e.currentTarget) },
  w && w.private ? lockLabel() : null,
  h("span", { class: "paper-ref-title", text: w ? w.title : id }),
  w && w.publication_year ? h("span", { class: "paper-meta", text: [w.publication_year, w.venue].filter(Boolean).join(", ") }) : null);
}

function cite(id, papers) {
  const w = papers[`https://openalex.org/${id}`] || papers[id];
  let label = id;
  if (w && w.private) {
    return h("button", { class: "cite private", "data-key": `cite-${id}`,
      "aria-label": `Evidence: ${w.title}, from your private document`,
      onclick: (e) => openEvidence(id, e.currentTarget) }, icon("lock"), h("span", { text: w.title }));
  }
  if (w) {
    const t = w.title.length > 34 ? `${w.title.slice(0, 32).trimEnd()}…` : w.title;
    label = `${t}${w.publication_year ? `, ${w.publication_year}` : ""}`;
  }
  return h("button", { class: `cite${w ? " paper-cite" : ""}`, "data-key": `cite-${id}`,
    "aria-label": `Evidence: ${w ? w.title : id}`,
    onclick: (e) => openEvidence(id, e.currentTarget) }, h("span", { text: label }));
}

function today() {
  return f.localToday();
}

async function setLead(leadId, action) {
  const l = leadsOf().find((x) => x.id === leadId);
  if (!l) return;
  const list = [...document.querySelectorAll("#panel .leads > li[data-id]")].filter((x) => !x.closest(".dismissed"));
  const at = list.findIndex((x) => x.dataset.id === leadId);
  const before = l.status;
  l.status = { keep: "kept", dismiss: "dismissed", restore: "new" }[action];
  renderPanel();
  renderTabs();
  if (action === "dismiss") announce("Dismissed. It is in the Dismissed list at the bottom, where you can restore it.");
  if (action === "keep") announce("Kept. The bar at the bottom of the list opens the comparison.");
  try {
    await api.setLead(S.briefId, l.id, action);
  } catch (e) {
    l.status = before;
    renderPanel();
    announce(`That change was not saved: ${e.message}`);
  }
  if (action === "dismiss") {
    // focus the card that took this one's place, or the one before it at the end
    const now = [...document.querySelectorAll("#panel .leads > li[data-id]")].filter((x) => !x.closest(".dismissed"));
    const next = now[Math.min(at, now.length - 1)];
    const target = next && next.querySelector(".title-btn");
    if (target) target.focus();
  }
}

// ---------- evidence panel ----------

let evidenceOpener = null;

async function openEvidence(id, opener) {
  // On a laptop the record opens in the rail beside the list (S24); elsewhere, and on a
  // phone, in the sheet.
  const railEv = $("#rail-ev");
  if (railEv && railEv.offsetParent !== null && window.matchMedia("(min-width: 901px)").matches) {
    return openInRail(railEv, id, opener);
  }
  evidenceOpener = opener || null;
  const panel = $("#evidence");
  const body = $("#evidence-body");
  fill(body, h("div", { class: "loading" }, owl("look", "owl-sm"), h("p", { text: "Fetching the record" })));
  $("#evidence-kind").textContent = "Evidence";
  const modal = !window.matchMedia("(min-width: 960px)").matches;
  panel.setAttribute("aria-modal", String(modal));
  panel.setAttribute("aria-labelledby", "evidence-kind");
  for (const el of [main(), $(".bar"), $(".foot"), $("#banner")]) el.inert = modal;
  panel.hidden = false;
  document.body.classList.add("sheet-open");
  requestAnimationFrame(() => panel.classList.add("in"));
  $("#evidence-close").focus();
  try {
    const r = await api.record(id);
    if (panel.hidden) return;
    $("#evidence-kind").textContent = KINDS[r.kind] || "Record";
    fill(body, ...recordView(r));
    panel.setAttribute("aria-labelledby", "evidence-kind evidence-title");
  } catch (e) {
    fill(body, h("p", { class: "notice error" }, icon("warn"), h("span", { text: `The record could not be opened: ${e.message}` })));
  }
}

async function openInRail(box, id, opener) {
  document.querySelectorAll("#panel .lead.selected").forEach((x) => x.classList.remove("selected"));
  const card = opener && opener.closest && opener.closest(".lead");
  if (card) card.classList.add("selected");
  fill(box, h("p", { class: "ev-kind", text: "Evidence" }), h("div", { class: "loading" }, owl("look", "owl-sm"), h("p", { text: "Fetching the record" })));
  try {
    const r = await api.record(id);
    fill(box, h("p", { class: "ev-kind", text: `Evidence · ${KINDS[r.kind] || "Record"}` }), ...recordView(r));
    box.setAttribute("aria-labelledby", "evidence-title");
    announce(`Evidence: ${r.title || r.name || r.display_name || "record"} is in the panel beside the list.`);
  } catch (e) {
    fill(box, h("p", { class: "notice error" }, icon("warn"), h("span", { text: `The record could not be opened: ${e.message}` })));
  }
}

function closeEvidence() {
  const panel = $("#evidence");
  if (panel.hidden) return;
  panel.classList.remove("in");
  document.body.classList.remove("sheet-open");
  for (const el of [main(), $(".bar"), $(".foot"), $("#banner")]) el.inert = false;
  panel.hidden = true;
  if (evidenceOpener && document.contains(evidenceOpener)) evidenceOpener.focus();
}

function field(label, value) {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) return null;
  return h("div", { class: "field" }, h("dt", { text: label }), h("dd", {}, value));
}

function recordView(r) {
  const out = [];
  if (r.kind === "scholarship") {
    const e = r.eligibility || {};
    const req = r.application_requirements;
    const items = [];
    if (req) {
      if (req.transcript) items.push("Transcript");
      if (req.essay) items.push("Essay");
      if (req.letters_count) items.push(`${req.letters_count} letter${req.letters_count > 1 ? "s" : ""} of recommendation`);
      if (req.portfolio) items.push("Portfolio");
      if (req.interview) items.push("Interview");
      if (req.fafsa) items.push("FAFSA");
    }
    const amt = r.amount_max != null ? (r.amount_min != null && r.amount_min !== r.amount_max
      ? `${f.money(r.amount_min)} to ${f.money(r.amount_max)}` : f.money(r.amount_max)) : "Not stated in the record";
    out.push(r.source === "synthetic" ? h("p", { class: "notice warn sample-note" }, h("span", { class: "tag sample", text: "Sample data" }),
      h("span", { text: " An invented record from a test corpus. Not a real scholarship." })) : null,
    h("h2", { class: "rec-title", id: "evidence-title", text: r.name }),
    h("dl", { class: "fields" },
      field("Sponsor", r.sponsor), field("Purpose", r.purpose), field("Type", r.award_type),
      field("Level", (r.level_of_study || []).join(", ") || "Not stated in the record"),
      field("Field", (r.field_of_study || []).join(", ")),
      field("Amount", amt),
      field("Deadline", f.formatDate(r.deadline) || "Not stated in the record"),
      field("Minimum GPA", e.gpa_min != null ? e.gpa_min.toFixed(2) : null),
      field("Undergraduate year", (e.class_year || []).join(", ")),
      field("Majors", (e.major || []).join(", ")),
      field("Enrolment", e.enrolment_status),
      field("Residency", e.residency_state), field("Citizenship", e.citizenship),
      field("Also asks (you decide)", e.targeted_criterion),
      field("Listing notes", e.notes),
      field("Application asks for", items.join(", ")),
      field("May be open to international students", r.international_ok ? "Yes, per the listing" : null),
      field("Source", SOURCES[r.source] || r.source),
      field("Fetched", f.formatDate(r.fetched_at))),
    r.source !== "synthetic" && f.safeUrl(r.source_url) ? h("p", {}, h("a", { href: f.safeUrl(r.source_url), target: "_blank", rel: "noopener", text: "Open the public page" })) : null);
    return out.filter(Boolean);
  }
  if (r.kind === "opportunity") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("dl", { class: "fields" },
        field("Opportunity number", r.opportunity_number), field("Agency", r.agency),
        field("Department", r.parent_agency),
        field("Status", r.status ? r.status[0].toUpperCase() + r.status.slice(1) : null),
        field("Posted", f.formatDate(r.open_date)),
        field("Closes", f.formatDate(r.close_date) || "Not stated in the record"),
        field("Deadline note", r.close_date_note),
        field("Archive date", f.formatDate(r.archive_date)),
        field("Award ceiling", r.award_ceiling ? f.money(r.award_ceiling) : "Not stated in the record"),
        field("Award floor", r.award_floor ? f.money(r.award_floor) : "Not stated in the record"),
        field("Activity code", r.activity_code),
        field("Funding instrument", (r.funding_instruments || []).join(", ")),
        field("Assistance listings", (r.assistance_listings || []).join(", "))));
    const all = r.eligible_applicants || [];
    // University types first and the rest behind a toggle; with no university type,
    // the record's own list shows as it is (S27).
    const uni = f.higherEdRows(all);
    const higher = uni.length ? uni : all;
    if (all.length) {
      out.push(h("h3", { class: "mini", text: "Eligible applicants" }),
        h("ul", { class: "elig-list" }, higher.map((x) => h("li", { class: uni.includes(x) ? "hi" : null, text: x }))),
        all.length > higher.length ? h("details", { class: "more" },
          h("summary", { text: `Show ${f.plural(all.length - higher.length, "other applicant type", "other applicant types")}` }),
          h("ul", { class: "elig-list" }, all.filter((x) => !higher.includes(x)).map((x) => h("li", { text: x })))) : null);
    }
    if (r.eligibility_notes) out.push(h("h3", { class: "mini", text: "Eligibility notes" }), longText(r.eligibility_notes));
    if (r.description) out.push(h("h3", { class: "mini", text: "Description" }), longText(r.description));
  } else if (r.kind === "private") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("p", {}, lockLabel("Held in this session's memory only")), longText(r.text || ""));
  } else if (r.kind === "work") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("dl", { class: "fields" }, field("Year", r.publication_year), field("Venue", r.venue),
        field("Type", r.type),
        field("DOI", r.doi ? h("a", { href: f.doiUrl(r.doi), target: "_blank", rel: "noopener", text: r.doi.replace(/^https?:\/\/doi\.org\//, "") }) : null),
        field("Cited by", r.cited_by_count !== null ? r.cited_by_count.toLocaleString("en-US") : null)));
    if (r.abstract) out.push(h("h3", { class: "mini", text: "Abstract" }), longText(r.abstract));
  } else if (r.kind === "award") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("dl", { class: "fields" }, field("Agency", r.agency), field("Award number", r.award_number),
        field("Start", f.formatDate(r.start_date)), field("End", f.formatDate(r.end_date)),
        field("Amount", r.amount ? `${f.money(r.amount)}${r.amount_basis ? ` (${r.amount_basis})` : ""}` : "Not stated in the record"),
        field("Fiscal year", r.fiscal_year), field("Activity code", r.activity_code),
        field("Funding opportunity", r.opportunity_number), field("Institution", r.institution)));
  } else if (r.kind === "lead" && r.route === "B") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: `Industry lead ${r.rank}` }),
      h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Inference" }), h("span", { text: r.inference || "" })),
      h("p", { text: r.explanation || "" }),
      h("dl", { class: "fields" }, field("Suggested relationship", r.relationship),
        field("Organisation", h("button", { class: "cite", onclick: (e) => openEvidence(r.record_id, e.currentTarget) },
          h("span", { text: "Open the organisation record" })))));
  } else if (r.kind === "organisation") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.name }),
      h("dl", { class: "fields" }, field("Type", r.type), field("Country", r.country),
        field("Names merged", (r.aliases || []).length > 1 ? r.aliases.join("; ") : null)),
      h("p", { class: "hint", text: "Perch counts a company's signals under one name when the source "
        + "names match exactly, apart from case, punctuation, a country in brackets and a legal form such as Inc." }));
  } else if (r.kind === "researcher") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.display_name }),
      h("dl", { class: "fields" }, field("Institutions", (r.institutions || []).join(", ")),
        field("Works", r.works_count), field("Cited by", r.cited_by_count),
        field("ORCID", r.orcid)));
  } else {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.id }));
  }
  const url = f.safeUrl(r.source_url);
  if (url) {
    out.splice(1, 0, h("p", { class: "source-top" }, h("a", { class: "btn primary", href: url, target: "_blank", rel: "noopener" },
      icon("external"), h("span", { text: `Open at ${SOURCES[r.source] || "the source"}` }))));
  }
  out.push(h("div", { class: "source" },
    h("p", {}, h("span", { class: "hint", text: "Source " }), h("b", { text: SOURCES[r.source] || r.source })),
    h("p", { class: "hint", text: `${r.source === "private" ? "Added" : "Fetched"} ${fetched(r.fetched_at)}` }),
    url ? h("a", { href: url, target: "_blank", rel: "noopener", text: url }) : null,
    r.source === "grants_gov" ? h("p", { class: "attrib", text: S.brief ? S.brief.notice : GRANTS_NOTICE }) : null));
  return out;
}

const GRANTS_NOTICE = "This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.";

function fetched(iso) {
  if (!iso) return "at an unknown time";
  return `${f.formatDate(iso)}, ${iso.slice(11, 16)} UTC`;
}

// Long record text shows once, cut to a few lines; the button opens it in place (S27).
let longSeq = 0;
function longText(text) {
  const t = String(text);
  if (t.length <= 700) return h("p", { class: "long", text: t });
  const id = `long-${++longSeq}`;
  const p = h("p", { class: "long clamped", id, text: t });
  const btn = h("button", { type: "button", class: "more-btn", "aria-expanded": "false", "aria-controls": id,
    onclick: () => {
      const open = p.classList.toggle("clamped") === false;
      btn.setAttribute("aria-expanded", String(open));
      btn.lastChild.textContent = open ? "Show less" : "Show the full text";
    } }, h("span", { text: "Show the full text" }));
  return h("div", { class: "long-wrap" }, p, btn);
}

// ---------- theme ----------

const THEMES = ["system", "light", "dark"];

function applyTheme(t) {
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  const b = $("#theme");
  const word = { system: "Auto", light: "Light", dark: "Dark" }[t];
  b.setAttribute("aria-label", `Theme: ${word}`);
  b.querySelector(".theme-word").textContent = word;
}

function initTheme() {
  let t = "system";
  try { t = localStorage.getItem("perch.theme") || "system"; } catch { /* default */ }
  if (!THEMES.includes(t)) t = "system";
  applyTheme(t);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || "system";
    const next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
    applyTheme(next);
    try { localStorage.setItem("perch.theme", next); } catch { /* convenience only */ }
  });
}

// ---------- start ----------

function init() {
  document.addEventListener("click", (e) => {
    const o = e.target.closest(".owl");
    if (o && !o.classList.contains("owl-xs")) poke(o);
  });
  initTheme();
  $("#evidence-close").addEventListener("click", closeEvidence);
  $("#evidence-scrim").addEventListener("click", closeEvidence);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeEvidence();
    if (e.key === "Tab" && !$("#evidence").hidden && window.matchMedia("(max-width: 959px)").matches) {
      const items = [...$("#evidence").querySelectorAll("button, a[href], summary, [tabindex='0']")].filter((x) => x.offsetParent);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  if (api.mode === "replay") {
    const b = $("#banner");
    b.hidden = false;
    fill(b, h("p", {}, h("b", { text: "Preview. " }),
      h("span", { text: window.PERCH_REPLAY.student
        ? "A SYNTHETIC student brief, played back: an invented student, real fellowship listings and sample scholarships."
        : "A saved brief, played back. Press Find, then This is the one and Build brief, to watch it build." }),
      h("a", { href: `#/brief/${encodeURIComponent(api.briefId)}/routes`, text: "Skip to the result" })));
    S.find.q = (window.PERCH_REPLAY.candidates[0] || {}).display_name || "";
  }
  $(".skip").addEventListener("click", (e) => { e.preventDefault(); main().focus(); });
  $("#status-chip").addEventListener("click", openModels);
  $("#end-session").addEventListener("click", endSession);
  if (api.mode === "live") {
    privateAvailable(privApi).then((on) => {
      S.privateOn = on;
      mode.setAvailable(on, on ? "" : "It needs every model to run on this server.");
      drawSwitch();
      if (!S.briefId && !location.hash.startsWith("#/private") && !location.hash.startsWith("#/help")
        && !location.hash.startsWith("#/student")) route();
    });
  } else {
    mode.setAvailable(false, "The preview has no server.");
  }
  const setBar = () => document.documentElement.style.setProperty("--bar-h", `${$(".bar").offsetHeight}px`);
  setBar();
  window.addEventListener("resize", setBar);
  window.addEventListener("hashchange", route);
  route();
}

init();
