// Perch web app: Find -> Profile -> Routes, with the evidence panel (docs/design/UI.md).
// Plain DOM, no build step. Every value from a record goes in through textContent.

import { liveApi, replayApi } from "./api.js";
import { add, fill, h, icon } from "./dom.js";
import { renderHelp } from "./help.js";
import { compareOffices, loadCompare, renderCompare } from "./compare.js";
import { renderHandoff } from "./handoff.js";
import { renderScout } from "./scout.js";
import * as f from "./format.js";
import { hop, owl, poke, setOwl } from "./owl.js";

const api = window.PERCH_REPLAY ? replayApi(window.PERCH_REPLAY) : liveApi(window.PERCH_API || "");
const POLL_MS = 1500;
const TABS = ["profile", "routes", "compare", "scout"];
const SOURCES = { openalex: "OpenAlex", grants_gov: "Grants.gov", nih_reporter: "NIH RePORTER",
  nsf: "NSF Award Search", perch: "Perch" };
const KINDS = { opportunity: "Funding opportunity", work: "Paper", award: "Public award",
  researcher: "Researcher", organisation: "Organisation", lead: "Industry lead" };
const SIGNALS = { citing_works: "They cite your papers", sbir_sttr: "NIH SBIR/STTR awards",
  topic_works: "They publish in your topics" };

const S = {
  find: { q: "", busy: false, error: null, candidates: null, searched: "", explain: true,
    minAmount: "" },
  brief: null, // last GET /briefs payload
  briefId: null,
  tab: "profile",
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

function route() {
  if (location.hash && !location.hash.startsWith("#/")) return; // in-page anchors, e.g. the skip link
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const onHelp = parts[0] === "help";
  if (onHelp) $("#help").setAttribute("aria-current", "page");
  else $("#help").removeAttribute("aria-current");
  document.body.classList.toggle("on-help", onHelp);
  if (onHelp) {
    stopPolling();
    S.briefId = null;
    S.brief = null;
    document.title = "Help — Perch";
    barOwl("idle");
    renderHelp(main(), { back: S.lastHash && S.lastHash !== location.hash ? S.lastHash : "#/" });
    window.scrollTo(0, 0);
    main().focus({ preventScroll: true });
    return;
  }
  S.lastHash = location.hash || "#/";
  if (parts[0] === "brief" && parts[1]) {
    const id = decodeURIComponent(parts[1]);
    S.tab = TABS.includes(parts[2]) ? parts[2] : S.tab;
    if (id !== S.briefId) openBrief(id);
    else renderPanel();
    return;
  }
  stopPolling();
  S.briefId = null;
  S.brief = null;
  renderFind();
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

// ---------- app bar owl ----------

function barOwl(state) {
  setOwl($("#bar-owl"), state);
}

// ---------- Find ----------

function keepFocus(render) {
  const a = document.activeElement;
  const key = a && (a.id || a.dataset.key);
  render();
  if (!key) return;
  const t = document.getElementById(key) || main().querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (t && t !== document.activeElement) t.focus({ preventScroll: true });
}

function renderFind() {
  document.title = "Perch";
  barOwl(S.find.busy ? "look" : "idle");
  const F = S.find;
  const input = h("input", { id: "q", name: "q", type: "search", autocomplete: "off",
    enterkeyhint: "search", placeholder: "Name, ORCID iD or OpenAlex ID", required: true,
    "aria-describedby": "q-hint", value: F.q,
    oninput: (e) => { F.q = e.target.value; } });
  const form = h("form", { class: "search", role: "search", onsubmit: (e) => {
    e.preventDefault(); search(); } },
  h("label", { for: "q", class: "field-label", text: "Researcher" }),
  h("div", { class: "search-row" }, input,
    h("button", { class: "btn primary", type: "submit", disabled: F.busy,
      "aria-busy": F.busy ? "true" : null }, icon("search"),
    h("span", { text: F.busy ? "Searching" : "Find researcher" }))),
  h("p", { id: "q-hint", class: "hint", text:
    "Names are searched among Temple University authors in OpenAlex. An ORCID iD or OpenAlex ID finds anyone." }),
  h("details", { class: "options" },
    h("summary", { text: "Options" }),
    h("label", { class: "check" },
      h("input", { type: "checkbox", checked: F.explain,
        onchange: (e) => { F.explain = e.target.checked; } }),
      h("span", {}, h("b", { text: "Explain each lead" }),
        h("span", { class: "hint", text:
          " A model writes a short, cited reason for every lead. This is the slow step." }))),
    h("label", { class: "field-label", for: "min", text: "Smallest award ceiling, in US dollars" }),
    h("input", { id: "min", type: "number", inputmode: "numeric", min: "0", step: "any",
      placeholder: "Any", value: F.minAmount, "aria-describedby": "min-hint",
      oninput: (e) => { F.minAmount = e.target.value; } }),
    h("p", { id: "min-hint", class: "hint", text:
      "Leaves out opportunities whose record states a lower ceiling. Records that state no amount stay in." })));

  const results = [];
  if (F.error) {
    results.push(h("div", { class: "notice error", role: "alert" }, icon("warn"),
      h("p", { text: F.error })));
  }
  if (F.candidates && !F.candidates.length) {
    results.push(h("div", { class: "empty" }, owl("worry", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: `No Temple University author matches “${F.searched}”.` }),
        h("p", { class: "hint", text:
          "Try the name as it appears on papers, or paste an ORCID iD such as 0000-0002-1825-0097." }))));
  } else if (F.candidates) {
    results.push(h("h2", { id: "pick", tabindex: "-1", class: "section-title",
      text: F.candidates.length === 1 ? "Is this the right person?" : "Which one is the right person?" }),
    h("p", { class: "hint", text: "Pick the match. Nothing runs until you do." }),
    h("ul", { class: "candidates" }, F.candidates.map(candidateCard)));
  }

  const recent = recentBriefs();
  const page = h("div", { class: "find" },
    h("section", { class: "hero" }, F.candidates || F.error ? null : heroArt(),
      h("div", { class: "hero-text" },
        h("h1", { text: "See every route to fund your work." }),
        h("p", { class: "lede", text:
          "Perch reads a researcher’s public papers and lists open funding that fits. Every claim links to the public record behind it." }),
        h("p", { class: "hero-help" }, h("a", { href: "#/help" }, icon("help"), h("span", { text: "New here? See how Perch works" }))))),
    form,
    h("div", { class: "results" }, results),
    recent.length ? h("section", { class: "recent" },
      h("h2", { class: "section-title", text: "Recent briefs on this device" }),
      h("ul", {}, recent.map((r) => h("li", {}, h("a", { href: `#/brief/${encodeURIComponent(r.id)}/routes` },
        h("span", { text: r.name }), h("span", { class: "hint", text: f.formatDate(r.at) })))))) : null);
  fill(main(), page);
}

function heroArt() {
  // A branch at dusk with Scout on it. Decorative.
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
  wrap.append(owl("idle", "owl-hero", { button: true }));
  return wrap;
}

function candidateCard(c) {
  const id = f.shortId(c.id);
  const temple = (c.institutions || []).some((i) => /temple university/i.test(i));
  return h("li", { class: "card candidate" },
    h("div", { class: "cand-head" },
      h("h3", { class: "cand-name", text: c.display_name }),
      temple ? h("span", { class: "tag moss", text: "Temple University" }) : null),
    h("p", { class: "cand-meta" },
      (c.institutions || []).filter((i) => !/temple university/i.test(i)).join(", ") || null,
      c.works_count !== null ? h("span", { text: `${(c.works_count ?? 0).toLocaleString("en-US")} works` }) : null,
      c.cited_by_count !== null ? h("span", { text: `${(c.cited_by_count ?? 0).toLocaleString("en-US")} citations` }) : null),
    c.topics && c.topics.length ? h("ul", { class: "chips", "aria-label": "OpenAlex topics" },
      c.topics.slice(0, 3).map((t) => h("li", { class: "chip", text: t.display_name }))) : null,
    h("p", { class: "hint ids" }, h("span", { text: `OpenAlex ${id}` }),
      c.orcid ? h("a", { href: f.safeUrl(c.orcid), target: "_blank", rel: "noopener",
        text: `ORCID ${c.orcid.replace(/^https?:\/\/orcid\.org\//, "")}` }) : null),
    h("button", { class: "btn primary wide", onclick: () => build(c) },
      h("span", { text: "Build brief" }), h("span", { class: "sr-only", text: ` for ${c.display_name}` })));
}

async function search() {
  const F = S.find;
  const q = F.q.trim();
  if (!q) { $("#q").focus(); return; }
  Object.assign(F, { busy: true, error: null, candidates: null, searched: q });
  keepFocus(renderFind);
  try {
    const r = await api.resolve(q);
    F.candidates = r.candidates || [];
  } catch (e) {
    F.error = e.status === 0 ? e.message
      : `OpenAlex could not be searched: ${e.message} Check the spelling or try an ORCID iD.`;
  }
  F.busy = false;
  renderFind();
  const n = (F.candidates || []).length;
  if (F.candidates) announce(n ? `${f.plural(n, "match", "matches")} found.` : "No match found.");
  const pick = $("#pick");
  if (pick) pick.focus();
}

async function build(c) {
  const F = S.find;
  const req = { author_id: f.shortId(c.id), explain: F.explain };
  const min = parseFloat(F.minAmount);
  if (Number.isFinite(min) && min > 0) req.min_amount = min;
  try {
    const r = await api.create(req);
    remember(r.id, c.display_name);
    S.startedHere = true;
    S.tab = "profile";
    go(`#/brief/${encodeURIComponent(r.id)}/profile`);
  } catch (e) {
    F.error = `The brief could not start: ${e.message}`;
    renderFind();
    const err = main().querySelector(".notice.error");
    if (err) err.scrollIntoView({ block: "center" });
  }
}

function recentBriefs() {
  if (api.mode === "replay") return [];
  try { return JSON.parse(localStorage.getItem("perch.recent") || "[]"); } catch { return []; }
}

function remember(id, name) {
  if (api.mode === "replay") return;
  try {
    const list = recentBriefs().filter((r) => r.id !== id);
    list.unshift({ id, name, at: new Date().toISOString().slice(0, 10) });
    localStorage.setItem("perch.recent", JSON.stringify(list.slice(0, 5)));
  } catch { /* storage may be blocked; recent list is a convenience */ }
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
  const name = r.display_name || "Researcher";
  document.title = `${name} — Perch`;
  const head = h("header", { class: "brief-head" },
    h("a", { class: "back", href: "#/", "aria-label": "New search" }, icon("back"),
      h("span", { text: "New search" })),
    h("h1", { class: "who", text: name }),
    h("p", { class: "who-meta" },
      h("span", { text: (r.institutions || []).join(", ") || "Institution not stated in the record" }),
      h("span", { text: `Brief as of ${f.formatDate(d.brief.options.as_of)}` })));
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Brief sections" },
    tabButton("profile", "Profile"), tabButton("routes", "Routes"), tabButton("compare", "Compare"),
    tabButton("scout", "Ask Scout"));
  fill(main(), h("div", { class: "brief" }, head,
    h("div", { id: "progress" }),
    h("div", { class: "tabs-wrap" }, tabs),
    h("div", { id: "panel", role: "tabpanel", tabindex: "-1" }),
    exportLink()));
  S.seen.explained = explainedCount();
  S.seen.stagesDone = d.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  if (!S.startedHere && d.brief.status === "done" && location.hash.split("/").length < 4) S.tab = "routes";
  S.startedHere = false;
  renderProgress();
  renderTabs();
  renderPanel();
}

function exportLink() {
  const url = api.exportUrl(S.briefId);
  return url ? h("p", { class: "export" }, h("a", { class: "btn quiet", href: url, download: `perch-brief-${S.briefId}.json` },
    icon("download"), h("span", { text: "Download the records as JSON" }))) : null;
}

function tabButton(key, label) {
  return h("button", { role: "tab", id: `tab-${key}`, class: "tab", "aria-controls": "panel",
    onclick: () => go(`#/brief/${encodeURIComponent(S.briefId)}/${key}`),
    onkeydown: (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        const other = TABS[(TABS.indexOf(key) + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
        go(`#/brief/${encodeURIComponent(S.briefId)}/${other}`);
        setTimeout(() => $(`#tab-${other}`).focus(), 0);
      }
    } }, h("span", { text: label }), ["routes", "compare"].includes(key) ? h("span", { class: "tab-count", hidden: true }) : null);
}

function renderTabs() {
  for (const key of TABS) {
    const t = $(`#tab-${key}`);
    if (!t) continue;
    const on = S.tab === key;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
  }
  const n = leadsOf().filter((l) => l.status !== "dismissed").length;
  const c = $("#tab-routes .tab-count");
  c.textContent = isDone("route_a") ? String(n) : "";
  if (isDone("route_a")) c.append(h("span", { class: "sr-only", text: n === 1 ? " lead" : " leads" }));
  c.hidden = !isDone("route_a");
  const kept = leadsOf().filter((l) => l.status === "kept").length;
  const k = $("#tab-compare .tab-count");
  k.textContent = kept ? String(kept) : "";
  if (kept) k.append(h("span", { class: "sr-only", text: " kept" }));
  k.hidden = !kept;
  $("#panel").setAttribute("aria-labelledby", `tab-${S.tab}`);
}

function updateBrief() {
  const ex = explainedCount();
  const done = S.brief.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  const pOwl = $("#progress .owl");
  if (ex > S.seen.explained || done > S.seen.stagesDone) { hop(pOwl); hop($("#bar-owl")); }
  if (done > S.seen.stagesDone) {
    const last = S.brief.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).pop();
    if (last) announce(`${f.STAGES[last.name] || last.name}: done.`);
  }
  S.seen = { explained: ex, stagesDone: done };
  renderProgress();
  renderTabs();
  renderPanel();
}

// ---------- progress ----------

function renderProgress() {
  const b = S.brief.brief;
  const box = $("#progress");
  const stages = b.stages;
  const runningIdx = stages.findIndex((s) => s.status === "running");
  const failedIdx = stages.findIndex((s) => s.status === "failed");
  const doneN = stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  const t0 = Date.parse(stages[0] && stages[0].started_at) || Date.parse(b.created_at);
  const lastEnd = Math.max(...stages.map((s) => Date.parse(s.finished_at) || 0));
  let state = "work", headline, sub;
  if (b.status === "failed") {
    state = "droop";
    const s = stages[failedIdx] || {};
    headline = `Stopped at: ${f.STAGES[s.name] || s.name || "a step"}`;
    sub = b.error || s.detail || "The server did not say why.";
  } else if (b.status === "done") {
    state = "done";
    headline = "Brief ready";
    sub = `Built in ${f.elapsed(lastEnd - t0)}.`;
  } else {
    const s = stages[runningIdx] || stages.find((x) => x.status === "pending") || stages[0];
    headline = `${f.STAGES[s.name] || s.name}`;
    if (s.name === "explanations" && isDone("route_a")) {
      sub = `${explainedCount()} of ${routeLeads("A").length} explained`;
    } else sub = b.status === "queued" ? "Waiting for the previous brief to finish" : "Working";
  }
  barOwl(state === "done" ? "done" : state);
  const pos = b.status === "done" ? stages.length - 1
    : failedIdx >= 0 ? failedIdx : Math.max(runningIdx, doneN, 0);
  const pct = stages.length > 1 ? (pos / (stages.length - 1)) * 100 : 0;

  let branch = box.querySelector(".branch");
  const compact = b.status === "done";
  if (!branch) {
    branch = h("div", { class: "branch", "aria-hidden": "true" },
      h("div", { class: "branch-line" }), h("div", { class: "branch-fill" }),
      h("div", { class: "knots" }, stages.map((s) => h("span", { class: "knot" }))),
      h("div", { class: "rider" }, owl(state, "owl-rider", { button: true })));
    fill(box, h("section", { class: "progress", "aria-label": "Building the brief" },
      branch, h("div", { class: "progress-text" }), h("div", { class: "progress-steps" })));
  }
  const sec = box.querySelector(".progress");
  sec.classList.toggle("compact", compact);
  sec.classList.toggle("failed", b.status === "failed");
  setOwl(box.querySelector(".owl-rider"), state);
  branch.querySelector(".rider").style.left = `${pct}%`;
  branch.querySelector(".branch-fill").style.width = `${pct}%`;
  branch.querySelectorAll(".knot").forEach((k, i) => {
    k.dataset.status = stages[i].status;
  });
  const elapsedNow = b.status === "done" || b.status === "failed" ? null
    : h("span", { class: "elapsed", "data-t0": String(t0) }, icon("clock"),
      h("span", { text: f.elapsed(Date.now() - t0) }));
  fill(box.querySelector(".progress-text"), 
    h("p", { class: "progress-head" }, h("b", { text: headline }), elapsedNow),
    h("p", { class: "progress-sub", text: sub }),
    b.status === "failed" ? h("button", { class: "btn primary", onclick: rebuild },
      h("span", { text: "Build again" })) : null);
  const steps = h("details", { class: "steps", open: S.stepsOpen,
    ontoggle: (e) => { S.stepsOpen = e.target.open; } },
  h("summary", { text: `Steps (${doneN} of ${stages.length} done)` }),
  h("ol", {}, stages.map((s) => h("li", { "data-status": s.status },
    h("span", { class: "step-dot", "aria-hidden": "true" }),
    h("span", { class: "step-name" }, h("b", { text: f.STAGES[s.name] || s.name }),
      h("span", { class: "sr-only", text: `, ${stepWord(s.status)}` })),
    h("span", { class: "step-detail", text: stepDetail(s) })))));
  fill(box.querySelector(".progress-steps"), steps);
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

setInterval(() => {
  const el = document.querySelector(".elapsed");
  if (el) el.lastChild.textContent = f.elapsed(Date.now() - Number(el.dataset.t0));
}, 1000);

async function rebuild() {
  const b = S.brief.brief;
  try {
    const r = await api.create({ author_id: f.shortId(b.researcher_id), ...b.options });
    remember(r.id, (S.brief.researcher || {}).display_name || f.shortId(b.researcher_id));
    S.startedHere = true;
    go(`#/brief/${encodeURIComponent(r.id)}/profile`);
  } catch (e) {
    const box = $("#progress .progress-text");
    if (box) add(box, [h("p", { class: "notice error", role: "alert" }, icon("warn"),
      h("span", { text: `The brief could not start again: ${e.message}` }))]);
  }
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
  }
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
  renderScout(panel, { api, briefId: S.briefId, done: S.brief.brief.status === "done",
    openEvidence, announce, rerender: drawScout });
}

// ----- Profile -----

function renderProfile(panel) {
  const d = S.brief, b = d.brief;
  const sig = JSON.stringify([b.summary, b.topics, b.threads.length, d.awards.length,
    Object.keys(d.papers || {}).length, b.stages.map((s) => s.status)]);
  if (panel.dataset.sig === sig) return;
  panel.dataset.sig = sig;
  keepFocus(() => fill(panel, 
    summarySection(), horizonSection(), threadsSection(),
    isDone("route_a") ? h("p", { class: "next" },
      h("a", { class: "btn primary", href: `#/brief/${encodeURIComponent(S.briefId)}/routes` },
        h("span", { text: `See ${f.plural(leadsOf().filter((l) => l.status !== "dismissed").length, "route")}` }))) : null));
}

function summarySection() {
  const b = S.brief.brief;
  const st = stage("summary");
  let body;
  if (b.summary) {
    body = [h("p", { class: "summary", text: b.summary }),
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
  return h("section", { class: "block" }, h("h2", { class: "section-title", text: "Research profile" }), body);
}

function openAlexTopics() {
  const t = (S.brief.researcher || {}).topics || [];
  return t.length ? [h("ul", { class: "chips", "aria-label": "OpenAlex topics" },
    t.slice(0, 5).map((x) => h("li", { class: "chip", text: x.display_name }))),
  h("p", { class: "provenance" }, h("span", { text: "Topics as OpenAlex lists them." }))] : null;
}

function horizonSection() {
  const d = S.brief, b = d.brief;
  const title = h("h2", { class: "section-title", text: "Public award horizon" });
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
    h("p", { class: "hint", text: `${f.plural(b.work_ids.length, "paper")} grouped by what they are about. Labels are the words that set each group apart.` }),
    h("ol", { class: "threads" }, b.threads.map((t) => {
      const papers = (t.work_ids || []).slice(0, 5).map((id) => d.papers[id]).filter(Boolean);
      return h("li", { class: "thread" },
        h("div", { class: "thread-head" },
          h("h3", { text: t.label }),
          h("span", { class: "share", text: `${Math.round(t.weight * 100)}% of recent work` })),
        h("span", { class: "meter", "aria-hidden": "true" },
          h("span", { style: `width:${Math.max(t.weight * 100, 2)}%` })),
        h("p", { class: "hint", text: `${f.plural(t.work_ids.length, "paper")}. Most recent first:` }),
        h("ul", { class: "papers" }, papers.map(paperRow)));
    })));
}

function paperRow(w) {
  return h("li", {}, h("button", { class: "paper", "data-key": `paper-${w.id}`, onclick: (e) => openEvidence(w.id, e.currentTarget) },
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
        h("label", { class: "sort" }, h("span", { class: "sr-only", text: "Sort leads by" }),
          h("select", { onchange: (e) => { S.sort = e.target.value; renderPanel(); } },
            h("option", { value: "order", text: "Best match" }),
            h("option", { value: "closing", text: "Closing soon" }),
            h("option", { value: "fit", text: "Fit estimate" })))),
      h("ol", { class: "leads", "aria-labelledby": "routes-title" }),
      h("div", { class: "dismissed-box" }),
      h("div", { class: "keep-bar-box" }));
  }
  renderKeepBar(panel.querySelector(".keep-bar-box"), kept);
  updateSwitch(panel);
  panel.querySelector("select").value = S.sort;
  panel.querySelector("#routes-title").textContent = `${f.plural(active.length, "open opportunity", "open opportunities")}`;
  const subBits = [];
  if (kept) subBits.push(`${kept} kept`);
  if (explaining && S.brief.brief.options.explain) subBits.push(`${explainedCount()} of ${routeLeads("A").length} explained so far`);
  subBits.push("Fit is a model’s estimate, not the odds of funding");
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
    s.records.length ? h("ul", { class: "sig-recs" }, s.records.map((r) => h("li", {},
      h("button", { class: "paper-ref", "data-key": `rec-${r.id}`, onclick: (e) => openEvidence(r.id, e.currentTarget) },
        h("span", { class: "paper-ref-title", text: r.title || r.id }),
        h("span", { class: "paper-meta", text: [r.date ? f.formatDate(r.date) : null, r.venue].filter(Boolean).join(", ") }))))) : null,
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

// Keep bar: once a lead is kept, how many and what comes next: the Compare tab.
function renderKeepBar(box, kept) {
  if (!kept) { box.replaceChildren(); return; }
  const sig = `keep:${kept}`;
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  const link = h("a", { class: "btn primary", href: `#/brief/${encodeURIComponent(S.briefId)}/compare`,
    "data-key": "keep-compare" }, h("span", { text: `Compare ${kept === 1 ? "it" : "them"}` }));
  fill(box, h("section", { class: "keep-bar", "aria-label": "Kept leads" },
    h("div", {}, h("p", { class: "keep-count", text: `${f.plural(kept, "lead", "leads")} kept` }),
      h("p", { class: "hint", text: "Next: compare them side by side, then draft a hand-off "
        + "to the right Temple office." })),
    link));
}

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
      h("span", { class: "sr-only", text: " out of 100, from a model" }));
  } else if (pending) {
    fit = h("span", { class: "fit pending" }, owl("work", "owl-xs"), h("span", { text: "Reading" }));
  }

  const head = h("div", { class: "lead-head" },
    h("span", { class: "tags" },
      h("span", { class: "tag", text: f.agencyShort(o.agency) }),
      o.activity_code ? h("span", { class: "tag", text: o.activity_code }) : null,
      o.status && o.status !== "posted" ? h("span", { class: "tag ember", text: o.status === "forecasted" ? "Forecast" : o.status }) : null,
      l.status === "kept" ? h("span", { class: "tag moss", text: "Kept" }) : null),
    fit);

  const facts = h("dl", { class: `facts${size ? "" : " one"}` },
    h("div", { class: `fact close ${urg}` }, h("dt", { text: "Closes" }),
      h("dd", {}, o.close_date ? h("span", { text: f.formatDate(o.close_date) }) : h("span", { class: "missing", text: "Not stated in the record" }),
        days !== null ? h("span", { class: "rel", text: f.closesIn(days) }) : null)),
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
  facts, noSize, explain, h("div", { class: "actions" }, actions));
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
  h("summary", { "data-key": "why" }, h("span", { text: "Why it fits" }),
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
  const w = papers[`https://openalex.org/${id}`];
  return h("button", { class: "paper-ref", "data-key": `cite-${id}`,
    onclick: (e) => openEvidence(id, e.currentTarget) },
  h("span", { class: "paper-ref-title", text: w ? w.title : id }),
  w && w.publication_year ? h("span", { class: "paper-meta", text: [w.publication_year, w.venue].filter(Boolean).join(", ") }) : null);
}

function cite(id, papers) {
  const w = papers[`https://openalex.org/${id}`];
  let label = id;
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
  if (r.kind === "opportunity") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("dl", { class: "fields" },
        field("Opportunity number", r.opportunity_number), field("Agency", r.agency),
        field("Status", r.status ? r.status[0].toUpperCase() + r.status.slice(1) : null),
        field("Posted", f.formatDate(r.open_date)),
        field("Closes", f.formatDate(r.close_date) || "Not stated in the record"),
        field("Archive date", f.formatDate(r.archive_date)),
        field("Award ceiling", r.award_ceiling ? f.money(r.award_ceiling) : "Not stated in the record"),
        field("Award floor", r.award_floor ? f.money(r.award_floor) : "Not stated in the record"),
        field("Activity code", r.activity_code),
        field("Funding instrument", (r.funding_instruments || []).join(", ")),
        field("Assistance listings", (r.assistance_listings || []).join(", "))));
    const all = r.eligible_applicants || [];
    const higher = f.higherEdRows(all);
    if (all.length) {
      out.push(h("h3", { class: "mini", text: "Eligible applicants" }),
        h("ul", { class: "elig-list" }, higher.map((x) => h("li", { class: "hi", text: x }))),
        all.length > higher.length ? h("details", { class: "more" },
          h("summary", { text: `Show ${all.length - higher.length} other applicant types` }),
          h("ul", { class: "elig-list" }, all.filter((x) => !higher.includes(x)).map((x) => h("li", { text: x })))) : null);
    }
    if (r.eligibility_notes) out.push(h("h3", { class: "mini", text: "Eligibility notes" }), longText(r.eligibility_notes));
    if (r.description) out.push(h("h3", { class: "mini", text: "Description" }), longText(r.description));
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
      icon("evidence"), h("span", { text: `Open at ${SOURCES[r.source] || "the source"}` }))));
  }
  out.push(h("div", { class: "source" },
    h("p", {}, h("span", { class: "hint", text: "Source " }), h("b", { text: SOURCES[r.source] || r.source })),
    h("p", { class: "hint", text: `Fetched ${fetched(r.fetched_at)}` }),
    url ? h("a", { href: url, target: "_blank", rel: "noopener", text: url }) : null,
    r.source === "grants_gov" ? h("p", { class: "attrib", text: S.brief ? S.brief.notice : GRANTS_NOTICE }) : null));
  return out;
}

const GRANTS_NOTICE = "This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.";

function fetched(iso) {
  if (!iso) return "at an unknown time";
  return `${f.formatDate(iso)}, ${iso.slice(11, 16)} UTC`;
}

function longText(text) {
  const t = String(text);
  if (t.length <= 700) return h("p", { class: "long", text: t });
  return h("div", {}, h("p", { class: "long", text: `${t.slice(0, 600).trimEnd()}…` }),
    h("details", { class: "more" }, h("summary", { text: "Show the full text" }), h("p", { class: "long", text: t })));
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
  $("#bar-owl-slot").replaceWith(Object.assign(owl("idle", "owl-bar", { button: true }), { id: "bar-owl" }));
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
      const items = [...$("#evidence").querySelectorAll("button, a[href], summary")].filter((x) => x.offsetParent);
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
      h("span", { text: "A saved brief, played back. Press Find researcher to watch it build." }),
      h("a", { href: `#/brief/${encodeURIComponent(api.briefId)}/routes`, text: "Skip to the result" })));
    S.find.q = (window.PERCH_REPLAY.candidates[0] || {}).display_name || "";
  }
  $(".skip").addEventListener("click", (e) => { e.preventDefault(); main().focus(); });
  const setBar = () => document.documentElement.style.setProperty("--bar-h", `${$(".bar").offsetHeight}px`);
  setBar();
  window.addEventListener("resize", setBar);
  window.addEventListener("hashchange", route);
  route();
}

init();
