// Ask Scout: follow-up questions about a finished brief (S10). Each tool Scout uses is a
// card, and each runs as soon as the model asks for it (S27: the ask-first mode is gone).
// Answers cite records; a citation opens the record. The chat reads like a chat window:
// the question box stays at the bottom and older replies scroll up and fade (S27).

import { h, fill, icon } from "./dom.js";
import { owl } from "./owl.js";
import { money, formatDate } from "./format.js";

const POLL_MS = 1200;
const TOOLS = {
  resolve_author: "Find the researcher", build_profile: "Read the research profile",
  list_awards: "List public awards", search_opportunities: "Search opportunities",
  get_org_signals: "Industry signals", explain_fit: "Explain the fit",
  compare: "Compare leads", draft_handoff: "Draft a hand-off", get_record: "Open a record",
  search_options: "Search options", check_option: "Check against your CV", explain_verdict: "Explain a verdict",
  read_cv: "What Perch read", compare_options: "Compare options", draft_note: "Draft a note",
  cover_points: "Points for a cover letter",
  // Scout v2's read tools (perch/scout/read_tools.py), the only steps it runs (S45)
  search_records: "Search records", read_record: "Read a record", read_brief: "Read the brief",
  read_cv_part: "Read a CV part", read_entries: "Read your entries", read_saved: "Read your saved list",
};
// The rail lists what Scout can use: its read tools (perch/scout/read_tools.py) and the
// buttons, which code answers (perch/scout/buttons.py). S45 fix round 3: search takes words
// only, so no filter is claimed.
const BUTTONS_LINE = "Buttons answered by code: Top leads, Deadlines, Compare kept leads, Hand-off to a Temple office";
const CAN_USE = {
  researcher: ["Search Perch’s public records by words", "Read one record in full",
    "Read this brief: its leads, their order and which you kept",
    "Read your CV, documents and entries, with contact details blanked", "Read your saved list", BUTTONS_LINE],
  student: ["Search fellowships and scholarships by words", "Read one record in full",
    "Read this brief: its options, their order and which you kept",
    "Read your CV and entries, with contact details blanked", "Read your saved list", BUTTONS_LINE],
};
// Examples Scout's read tools can answer: words, the brief, the CV (S45 fix round 3).
const STUDENT_EXAMPLES = ["Which of my options closes soonest?",
  "What does my top option ask for that my CV does not show yet?",
  "Find scholarships for a graduate student in public health.",
  "What should my application for my top option highlight?"];
const ARGS = {
  route: "Route", author_id: "Researcher", min_amount: "Ceiling at least", max_amount: "Ceiling at most",
  agencies: "Agencies", exclude_agencies: "Not these agencies", closes_by: "Closes by",
  closes_after: "Closes after", sort: "Sorted by",
  activity_codes: "Activity codes", keywords: "Mentions", exclude_keywords: "Does not mention",
  top: "How many", id: "Record", opportunity_id: "Opportunity", opportunity_ids: "Opportunities",
  ids: "Leads", office: "Office",
  name: "Name",
  // student tools (S28: the read-as line showed their raw keys)
  deadline_after: "Deadline after", deadline_before: "Deadline before", verdict: "Verdict",
  words: "Mentions", option_id: "Option",
  scope: "Within",  // F1: the brief's leads, or every opportunity in the store
};
const SCOPES = { brief: "your brief", all: "all opportunities" };
const STATUS = { proposed: "Running…", done: "Done", not_run: "Not run", refused: "Refused", error: "Failed", repeated: "Repeat, not run again" };
const EXAMPLES = ["Which of my leads closes soonest?",
  "What does my top lead ask for that my CV does not show yet?",
  "Find NSF grants on sensor networks.", "What could my cover letter for the top lead say?"];
// F9: "start over" and its kin open a new conversation, as the button beside the box does.
// G9: with polite words around it ("can we start over", "lets start over pls"), as the
// server's START_OVER_RE (perch/scout/loop.py) reads it.
const START_OVER = /^\W*(?:(?:ok(?:ay)?|so|hey|um|please|pls|plz|can|could|would|will|we|you|i|let'?s|let|us|want|wanna|to|like|just|now|and|maybe)\W+)*(?:start (?:over|again|afresh)|restart|reset|clear (?:the )?(?:chat|conversation)|new (?:conversation|chat)|begin again)(?:\W+(?:the|this|chat|conversation|please|pls|plz|now|again|thanks|thank you))*\W*$/i;

// One Scout conversation per brief, kept while the brief is on screen.
// Scout runs every step as soon as the model asks for it and shows each one (S27, S28).
const T = { briefId: null, data: null, error: null, timer: null, draft: "", sending: false, stopping: false, openSteps: new Set(), seen: 0, stick: true, top: 0 };

// Stop polling and forget the conversation.
export function resetScout() {
  clearTimeout(T.timer);
  Object.assign(T, { briefId: null, data: null, error: null, timer: null, draft: "", sending: false, stopping: false, openSteps: new Set(), seen: 0, stick: true, top: 0 });
}

export function renderScout(panel, ctx) {
  const key = `${ctx.briefId}:${ctx.student ? "s" : "r"}`;
  if (T.briefId !== key) reset(key);
  if (!ctx.api.scoutStart) {
    fill(panel, h("div", { class: "empty" }, owl("look", "owl-md"), h("div", {},
      h("p", { class: "lede", text: "Scout needs the live server." }),
      h("p", { class: "hint", text: "This preview plays back a saved brief, so there is no one to ask." }))));
    return;
  }
  if (ctx.signedIn === false) {
    // Every Scout route needs an account (perch/api.py signed_in), so a guest gets the reason
    // and the way in, not a question box that cannot send (S46 QA round 2).
    fill(panel, h("div", { class: "empty" }, owl("look", "owl-md"), h("div", {},
      h("p", { class: "lede", text: "Ask Scout needs an account." }),
      h("p", { class: "hint", text: "Scout reads your brief, the records and your CV to answer, so it works once you sign in." }),
      h("p", {}, h("a", { class: "btn primary", href: ctx.signIn, "data-key": "scout-signin", text: "Sign in to ask Scout" })))));
    return;
  }
  if (!ctx.done) {
    fill(panel, h("div", { class: "empty" }, owl("look", "owl-md"), h("div", {},
      h("p", { class: "lede", text: "Scout can help once the brief has finished." }),
      h("p", { class: "hint", text: "Then ask about your leads in plain words, such as “what does my top lead ask for?”." }))));
    return;
  }
  // Polls redraw only when something changed, so the reader's scroll is left alone.
  const sig = JSON.stringify([key, T.data, T.error, T.sending, T.stopping]);
  if (panel.dataset.scoutSig === sig && panel.querySelector(".scout")) return;
  panel.dataset.scoutSig = sig;
  const busy = Boolean(T.data && T.data.busy) || T.sending;
  const fresh = !panel.querySelector(".scout");
  // One column, like a chat app (S27, Dakshitha): Scout's welcome is the first message and
  // says what it can use; the question box is pinned to the bottom of the window.
  const view = h("div", { class: "scout" },
    h("div", { class: "scout-scroll", tabindex: "0", "aria-label": "Conversation with Scout",
      onscroll: (e) => {
        const b = e.currentTarget;
        b.classList.toggle("faded", b.scrollTop > 4);
        T.stick = b.scrollHeight - b.scrollTop - b.clientHeight < 32;
        T.top = b.scrollTop;
      } },
    welcome(ctx),
    h("ol", { class: "scout-log", "aria-live": "polite" }, ...(T.data ? T.data.exchanges.map((x, i) => exchange(x, ctx, busy, i >= T.seen, i)) : [])),
    T.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: T.error })) : null,
    // Where the model runs stays in view; its name and the token count sit in the Steps (U32).
    T.data && T.data.exchanges.length ? h("p", { class: "scout-meta", text: modelWhere(T.data.model) }) : null),
    askForm(ctx, busy));
  const focused = document.activeElement && document.activeElement.id;
  fill(panel, view);
  T.seen = T.data ? T.data.exchanges.length : 0;
  fitChat(view, fresh);
  const box = view.querySelector(".scout-scroll");
  // New replies come in at the bottom, as in a chat window; a reader who scrolled up to
  // read an older reply stays where they are.
  box.scrollTop = T.stick ? box.scrollHeight : T.top;
  box.classList.toggle("faded", box.scrollTop > 4);
  if (focused === "scout-q") {
    const q = panel.querySelector("#scout-q");
    q.focus({ preventScroll: true });
    q.setSelectionRange(q.value.length, q.value.length);
  }
}

// Scout's first message: what it can use, example questions, and its limits.
function welcome(ctx) {
  const examples = ctx.api.recordedQuestion ? [ctx.api.recordedQuestion] : ctx.student ? STUDENT_EXAMPLES : EXAMPLES;
  return h("div", { class: "scout-hello" }, owl("idle", "owl-sm", { button: true }),
    h("div", { class: "scout-hello-body" },
      h("p", { class: "lede", text: ctx.student ? "Hello. Ask about your options in plain words. I can use Perch’s own tools:"
        : "Hello. Ask about this brief in plain words. I can use Perch’s own tools:" }),
      h("ul", { class: "scout-can" }, CAN_USE[ctx.student ? "student" : "researcher"].map((x) => h("li", { text: x }))),
      ctx.api.recordedQuestion ? h("p", { class: "hint", text: "This preview plays back one recorded question. Tap it below." }) : null,
      !T.data ? h("ul", { class: "chips scout-try", "aria-label": "Example questions" }, ...examples.map((q) => h("li", {},
        h("button", { class: "chip", type: "button", onclick: () => { T.draft = q; send(ctx); } }, q)))) : null,
      h("details", { class: "scout-limits" }, h("summary", { text: "What I will not do" }),
        h("p", { text: ctx.student
          ? "I cite records. A date or amount not in a cited record is rewritten once, then withheld. I stop after a fixed number of tool steps for one question, cannot browse the web, send anything or change a record. A model reads a part of your CV, your entries or your saved list when it opens them to answer a question. Contact details are blanked first. Sample scholarships stay marked as samples. Scout has a daily budget; when it is spent, it resets each day."
          : "I cite records. A date or amount not in a cited record is rewritten once, then withheld. I stop after a fixed number of tool steps for one question, cannot browse the web, send anything or change a record. A model reads your CV, documents, entries or saved list when it opens them to answer a question, with contact details blanked. Scout has a daily budget; when it is spent, it resets each day." }))));
}

// The chat fills the window below the sticky tabs, so the question box sits on the bottom
// edge of the screen. Opening the tab, or asking, scrolls the brief's header away once.
function fitChat(view, scroll) {
  const bar = document.querySelector(".bar"), tabs = document.querySelector(".tabs-wrap");
  const under = (bar ? bar.offsetHeight : 64) + (tabs ? tabs.offsetHeight : 48);
  view.style.setProperty("--chat-h", `${Math.max(360, window.innerHeight - under - 12)}px`);
  if (scroll) pinChat();
}

function pinChat() {
  const view = document.querySelector("#panel > .scout"), tabs = document.querySelector(".tabs-wrap");
  if (!view) return;
  const top = view.getBoundingClientRect().top + window.scrollY;
  // Where the tabs end once they stick, not where they sit now: at the top of the page
  // they have not stuck yet, and measuring them there left the box below the window.
  const under = tabs ? (parseFloat(getComputedStyle(tabs).top) || 0) + tabs.offsetHeight : 0;
  window.scrollTo({ top: Math.max(0, top - under - 4) });
}

window.addEventListener("resize", () => {
  const view = document.querySelector("#panel > .scout");
  if (view) fitChat(view, false);
});

function reset(briefId) {
  clearTimeout(T.timer);
  Object.assign(T, { briefId, data: null, error: null, timer: null, draft: "", sending: false, stopping: false, openSteps: new Set(), seen: 0, stick: true, top: 0 });
}

// One exchange (S28, the spec's section 6): the question, how Scout read it as one line
// per finished step with its filters, the answer, any hand-off draft to copy, and then
// the step cards, folded, since nobody needs to act on them.
function exchange(x, ctx, busy, fresh, i) {
  const last = T.data && i === T.data.exchanges.length - 1;
  const running = x.status === "running";
  const drafts = x.cards.filter((c) => c.draft);
  const points = x.cards.filter((c) => c.points);  // S33: cover-letter points, shown like a draft
  return h("li", { class: fresh ? "scout-x new" : "scout-x" },
    h("p", { class: "scout-q" }, h("span", { class: "sr-only", text: "You asked: " }), x.question),
    readAs(x, ctx),
    answer(x, ctx, running && busy),
    ...drafts.map((c) => draftBlock(c.draft, ctx)),
    ...points.map((c) => pointsBlock(c.points, ctx)),
    x.cards.length ? h("details", { class: "scout-steps", open: T.openSteps.has(i),
      ontoggle: (e) => { if (e.target.open) T.openSteps.add(i); else T.openSteps.delete(i); } },
      h("summary", { text: `Steps (${x.cards.length})` }),
      h("ol", { class: "scout-cards" }, ...x.cards.map((c) => card(c, ctx))),
      last && T.data.model ? h("p", { class: "hint scout-model", text: `Model ${T.data.model}.${T.data.tokens ? ` ${T.data.tokens.toLocaleString()} tokens so far in this conversation.` : ""}` }) : null) : null);
}

function readAs(x, ctx) {
  const done = x.cards.filter((c) => c.status === "done");
  const trouble = x.cards.filter((c) => c.status === "refused" || c.status === "error").length;
  if (!done.length && !trouble) return null;
  return h("div", { class: "scout-read" },
    h("p", { class: "mini", text: "How Scout read your question" }),
    h("ul", {}, ...done.map((c) => h("li", {},
      h("span", { class: "scout-read-tool", text: TOOLS[c.tool] || c.tool }),
      ...argList(c, ctx).map(([k, v]) => h("span", { class: "chip", text: `${ARGS[k] || k}: ${v}` })),
      c.detail ? h("span", { class: "scout-read-result", text: `→ ${c.detail}` }) : null))),
    trouble ? h("p", { class: "hint", text: `${trouble === 1 ? "One step" : `${trouble} steps`} failed or were refused; the steps below say why.` }) : null);
}

const ROUTES = { A: "Grants", B: "Industry leads", F: "Fellowships", S: "Scholarships" };
// T9: sort keys and dates read as the other chips do ("Closes after: 1 Nov 2026").
const SORTS = { match: "Match", close_date: "close date", award_ceiling: "award ceiling", deadline: "deadline" };
const DATE_ARGS = new Set(["closes_by", "closes_after", "deadline_after", "deadline_before"]);
// Record keys in a step's filters read as the brief names them (U8).
const ID_ARGS = new Set(["id", "ids", "opportunity_id", "opportunity_ids", "option_id"]);
function argList(c, ctx) {
  const name = (v) => { const k = ctx && ctx.label ? ctx.label(String(v)) : null;
    return k ? k.name : leadLabel(String(v)) || String(v).replace(/^grants_gov:/, ""); };
  return Object.entries(c.arguments || {}).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => [k, k === "route" ? ROUTES[v] || v
      : k === "scope" ? SCOPES[v] || v
      : k === "sort" ? SORTS[v] || String(v).replace(/_/g, " ")
      : (k === "min_amount" || k === "max_amount") && Number.isFinite(Number(v)) ? money(v)  // G18: as the cards
        : DATE_ARGS.has(k) && /^\d{4}-\d{2}-\d{2}$/.test(String(v)) ? formatDate(String(v))
      : ID_ARGS.has(k) ? [].concat(v).map(name).join(", ")
        : Array.isArray(v) ? v.join(", ") : v]);
}

function card(c, ctx) {
  const args = argList(c, ctx);
  return h("li", { class: `scout-card s-${c.status}` },
    h("div", { class: "scout-card-head" },
      h("span", { class: "scout-tool", text: TOOLS[c.tool] || c.tool }),
      h("code", { class: "scout-tool-name", text: c.tool }),
      whereTag(c),
      h("span", { class: "scout-status", text: STATUS[c.status] || c.status })),
    args.length ? h("ul", { class: "chips" }, ...args.map(([k, v]) => h("li", { class: "chip", text: `${ARGS[k] || k}: ${v}` }))) : null,
    c.detail ? h("p", { class: "hint", text: c.detail }) : null,
    c.records && c.records.length ? h("p", { class: "scout-records" }, h("span", { class: "hint", text: "Records: " }),
      ...c.records.slice(0, 8).map((id) => citeBtn(id, ctx))) : null);
}

// Where a step ran (S28): code, a local model, or a named Cloud provider, as the
// card shows it. Recordings made before S28 carry no "where" and show no tag.
const CLOUD_NAMES = { anthropic: "Anthropic" };
// The planner's model string reads "provider:model"; only a named Cloud provider is Cloud (U32).
function modelWhere(model) {
  const p = String(model || "").split(":")[0];
  return CLOUD_NAMES[p] ? `Cloud: ${CLOUD_NAMES[p]}` : "Local model";
}
function whereTag(c) {
  if (!c.where) return null;
  if (c.where === "cloud") return h("span", { class: "tag cloud scout-where", text: `Cloud: ${CLOUD_NAMES[c.provider] || c.provider}` });
  return h("span", { class: "tag scout-where", text: c.where === "local" ? "Local model" : "Code, no model" });
}

// A hand-off draft from draft_handoff: the full text to copy. Never sent.
function draftBlock(d, ctx) {
  const text = `Subject: ${d.subject}\n\n${d.body}`;
  return h("details", { class: "scout-draft", open: true },
    h("summary", { text: `The draft to ${d.office}` }),
    // F7: who wrote the opening paragraph; code writes the rest of every draft.
    d.opening_by === "model" ? h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Model text" }),
      h("span", { text: "The opening paragraph is written by a model and checked against the records it cites. The rest is Perch’s code." }))
      : d.opening_by === "code" ? h("p", { class: "provenance" }, h("span", { class: "tag", text: "Code, no model" }),
        h("span", { text: d.opening_note || "Every line is written by Perch’s code." })) : null,
    d.opening_withheld ? h("p", { class: "hint", text: "The model’s opening failed the checks twice; a plain sentence replaces it." }) : null,
    // Focusable, so a keyboard can scroll a long draft (axe scrollable-region-focusable).
    h("pre", { class: "draft-text", tabindex: "0", "aria-label": `The draft to ${d.office}`, text }),
    h("div", { class: "scout-actions" },
      h("button", { class: "btn", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(text); ctx.announce("The draft is copied."); }
        catch { ctx.announce("Copying was blocked by the browser. Select the text and copy it by hand."); }
      } }, h("span", { text: "Copy the draft" })),
      h("a", { class: "btn quiet", href: d.office_page, target: "_blank", rel: "noopener", text: "Office page" })),
    h("p", { class: "hint", text: "Perch never sends this. The To line is yours to fill in." }));
}

// Cover-letter points from cover_points (S33): what the record asks, what the person's
// own records show, each sentence cited. Shown in full to copy; never sent, never exported.
const POINTS_HINT = "Perch never sends this, and it never enters an export or a hand-off draft.";
export function pointsBlock(p, ctx) {
  const title = p.for.title || p.for.id;
  const cite = (id) => pointCite(id, p, ctx);
  const text = pointsText(p);
  const flagged = new Set(p.unsupported || []);
  return h("details", { class: "scout-points", open: true },
    h("summary", {}, h("span", { text: `Points for your cover letter: ${title}` }),
      p.for.sample ? h("span", { class: "sample-badge", text: "Sample data" }) : null),
    p.status === "withheld" ? null : h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Model text" }),
      h("span", { text: "Written by a model and checked against the records it cites. Put them in your own words." })),
    p.for.sample ? h("p", { class: "hint", text: "This record is an invented sample, so the points are a demonstration, not advice." }) : null,
    p.status === "withheld" ? h("p", { class: "notice warn" }, icon("warn"), h("span", { text: p.detail || "The points were withheld." })) : null,
    p.status === "withheld" ? null : h("ol", { class: "points-list" }, ...p.points.map((pt) => h("li", {},
      h("p", { class: `point-line${flagged.has(pt.asks) ? " flagged" : ""}` }, h("b", { text: "The record asks" }),
        h("span", { text: ` ${pt.asks} ` }), ...pt.asks_ids.map(cite)),
      h("p", { class: `point-line${flagged.has(pt.you) ? " flagged" : ""}` }, h("b", { text: "You have" }),
        h("span", { text: ` ${pt.you} ` }), ...pt.you_ids.map(cite))))),
    p.status !== "withheld" && p.missing && p.missing.length ? h("div", { class: "points-missing" },
      h("p", { class: "mini", text: "Still missing" }),
      h("p", { class: "hint", text: "What the record asks for that nothing you added shows." }),
      h("ul", {}, ...p.missing.map((m) => h("li", { class: flagged.has(m) ? "flagged" : null }, h("span", { text: `${m} ` }), cite(p.for.id))))) : null,
    // The same flag the fit explanations use: the grounding model could not match the sentence.
    flagged.size ? h("div", { class: "notice warn" }, icon("warn"),
      h("div", {}, h("p", { text: "This statement could not be matched to its source:" }),
        h("ul", {}, [...flagged].map((u) => h("li", { text: u }))))) : null,
    p.status === "withheld" ? null : h("div", { class: "scout-actions" },
      h("button", { class: "btn points-copy", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(text); ctx.announce("The points are copied."); }
        catch { ctx.announce("Copying was blocked by the browser. Select the text and copy it by hand."); }
      } }, h("span", { text: "Copy the points" }))),
    h("p", { class: "hint", text: POINTS_HINT }));
}

// The points as plain text, for the clipboard.
function pointsText(p) {
  const lines = p.points.map((pt, i) => `${i + 1}. The record asks: ${pt.asks}\n   You have: ${pt.you}`);
  for (const m of p.missing || []) lines.push(`Still missing: ${m}`);
  const used = [...new Set(p.points.flatMap((pt) => [...pt.asks_ids, ...pt.you_ids]))];
  lines.push(`Each point cites: ${used.map((id) => `${id}: ${(p.sources || {})[id] || id}`).join("; ")}`);
  return `Points for your cover letter: ${p.for.title || p.for.id}${p.for.sample ? " (sample data)" : ""}\n\n${lines.join("\n")}`;
}

// A citation chip for a point, labelled by the source's title (the id is the tooltip).
// The user's own document ("user:interests") shows a lock and opens nothing; a public record opens
// in the evidence panel, as the answer's citations do.
function pointCite(id, p, ctx) {
  const full = (p.sources || {})[id] || id;
  const short = full.length > 56 ? `${full.slice(0, 54).replace(/\s+\S*$/, "")}…` : full;
  if (id.startsWith("user:")) {
    return h("span", { class: "cite own", title: id }, icon("lock"), h("span", { text: short }),
      h("span", { class: "sr-only", text: `, from ${full}, your own document` }));
  }
  const sample = (id === p.for.id && p.for.sample) || Boolean(ctx.label && (ctx.label(id) || {}).sample);
  return h("button", { class: `cite${sample ? " sample" : ""}`, type: "button", title: id,
    "aria-label": `Evidence: ${full}${sample ? ", sample data" : ""}`, onclick: (e) => ctx.openEvidence(id, e.currentTarget) },
  h("span", { text: short }));
}

function answer(x, ctx, thinking) {
  // Stop ends the question between steps; the steps already done stay (S28).
  const now = x.cards.find((c) => c.status === "proposed");
  if (thinking) return h("div", { class: "scout-wait" }, owl("look", "owl-sm"),
    h("span", { text: T.stopping ? "Stopping after this step…" : now ? `${TOOLS[now.tool] || now.tool}…` : "Scout is working…" }),
    h("button", { class: "btn quiet scout-stop", type: "button", disabled: T.stopping, onclick: () => stop(ctx) }, icon("stop"), h("span", { text: "Stop" })));
  // A stopped turn writes no answer, so it usually has no steps to point to (S45 R1).
  if (x.status === "stopped" && x.by_user) return h("p", { class: "hint scout-stopped", text: x.cards.length
    ? "You stopped this question. The steps below show what ran; ask again to go on."
    : "You stopped this question before Scout answered. Ask again to go on." });
  // After a draft or a points step the answer line is written by code, not a model (R3, R20, S33).
  if (x.answer && x.answer_by === "code") {
    const hasDraft = x.cards.some((c) => c.draft), hasPoints = x.cards.some((c) => c.points);
    const below = hasDraft && hasPoints ? "The draft and the points below are the steps’ results."
      : hasPoints ? "The points below are the step’s result." : "The draft below is the step’s result.";
    return h("div", { class: "scout-answer by-code" },
      h("p", { class: "provenance" }, h("span", { class: "tag", text: "Code, no model" }),
        h("span", { text: `Written by Perch’s code. ${below}` })),
      h("p", { text: x.answer }));
  }
  // Model prose says so in words, not by its tint alone (U7). What the checks found is shown
  // with it (S45): sentences Scout could not confirm are marked, sentences it removed are
  // counted, and the General advice part sits apart, labelled as uncited.
  // An answer may be all General advice, with no grounded part (S45 R1).
  if (x.answer || (x.message && x.message.general)) {
    const m = x.message || {};
    if (m.flagged && m.withheld_all) {
      // The records Scout opened, so the notice is not left without them: public records only, as chips.
      const read = (m.read || []).filter((id) => !id.startsWith("user:")).slice(0, 8);
      return h("div", { class: "notice warn" }, icon("warn"), h("div", {},
        h("p", { text: x.answer }),
        read.length ? h("p", { class: "scout-records" }, h("span", { class: "hint", text: "Records Scout read: " }),
          ...read.map((id) => citeBtn(id, ctx))) : null));
    }
    const marked = markUnsupported(x.answer, m.unsupported || []);
    const n = (m.unsupported || []).length;
    const checked = m.flagged ? "Written by a model. It failed the citation check; sentences were removed."
      : n ? "Written by a model. Some sentences could not be confirmed; they are marked."
        : "Written by a model; checked against the records it cites.";
    const plural = (k) => `${k} sentence${k === 1 ? "" : "s"}`;
    return h("div", { class: "scout-answer-wrap" },
      m.flagged ? h("p", { class: "notice warn" }, icon("warn"), h("span", {
        text: `This answer did not pass the citation check twice. ${plural(m.withheld || 0)} ${m.withheld === 1 ? "was" : "were"} removed. What remains is shown, but check each claim against its record.` })) : null,
      h("div", { class: "scout-answer" },
        h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Model text" }), h("span", { text: checked })),
        ...withCites(marked.text, ctx),
        m.general ? h("div", { class: "scout-general" },
          h("p", { class: "provenance" }, h("b", { text: "General advice, not from records" }), h("span", { class: "tag", text: "Uncited" })),
          ...withCites(m.general, ctx),
          h("p", { class: "hint", text: "General guidance from the model. It cites no record and states no date or amount. Check details with the sponsor." })) : null),
      n && !m.flagged ? h("div", { class: "notice warn" }, icon("warn"), h("div", {},
        h("p", { text: `Scout could not confirm ${plural(n)} against the cited records. ${noticeWhere(n, marked.missed.length)} Open the record before relying on them.` }),
        marked.missed.length ? h("ul", {}, marked.missed.map((u) => h("li", { text: u.replace(/\*\*/g, "") }))) : null)) : null);
  }
  // A wholly withheld answer always carries its text (perch/scout/turn.py), and v2 has no
  // per-conversation limit, so the old empty-answer and limit notices are gone (S45 R1).
  if (x.status === "stopped" || x.status === "failed") return h("p", { class: "notice warn" }, icon("warn"), h("span", { text: `Scout stopped: ${(x.errors || []).join("; ") || "no answer"}.` }));
  return null;
}

// T4: forget this conversation on the page; the next question opens a new Scout session
// on the same brief.
function newConversation(ctx) {
  const typed = T.draft;
  reset(T.briefId);
  T.draft = typed;
  ctx.rerender();
  const q = document.getElementById("scout-q");
  if (q) q.focus();
  ctx.announce("New conversation. Ask Scout a question.");
}

// The model's text, tidied for reading (U8): lines that start with "* " or "- " become a
// list, "**" marks go, and amounts read as the cards write them ($200,000, not
// $200,000.0). "[id]" and "[id, id]" become buttons that open the record.
function withCites(text, ctx) {
  const clean = String(text).replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\$(\d[\d,]*(?:\.\d+)?)/g, (m, n) => (Number.isFinite(Number(n.replace(/,/g, ""))) ? money(Number(n.replace(/,/g, ""))) : m));
  const out = [];
  let list = null, table = null;
  for (const line of clean.split("\n")) {
    // F11: a pipe table becomes a table; its |---| rule line is dropped.
    const row = line.match(/^\s*\|(.*)\|\s*$/);
    if (row) {
      list = null;
      const cells = row[1].split("|").map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c) || !c)) continue;
      if (!table) {
        table = h("table", { class: "scout-table" }, h("thead", {}, h("tr", {}, ...cells.map((c) => h("th", { scope: "col" }, ...inline(c, ctx))))), h("tbody"));
        out.push(h("div", { class: "scout-table-wrap", tabindex: "0", role: "region", "aria-label": "Table in Scout’s answer" }, table));
      } else table.tBodies[0].append(h("tr", {}, ...cells.map((c, i) => h(i ? "td" : "th", i ? {} : { scope: "row" }, ...inline(c, ctx)))));
      continue;
    }
    if (table && !line.trim()) continue;
    table = null;
    const item = line.match(/^\s*[*-]\s+(.*)$/);
    if (item) {
      if (!list) { list = h("ul", { class: "scout-list" }); out.push(list); }
      list.append(h("li", {}, ...inline(item[1], ctx)));
      continue;
    }
    const after = list;
    list = null;
    if (!line.trim() && after) continue; // no blank line under a list
    if (out.length && !after) out.push("\n");
    out.push(...inline(line, ctx));
  }
  return out;
}

// Where the unconfirmed sentences are, said exactly: some may be underlined and some listed.
function noticeWhere(n, listed) {
  if (!listed) return n === 1 ? "It is underlined above." : "They are underlined above.";
  if (listed >= n) return n === 1 ? "It is listed here." : "They are listed here.";
  return `${n - listed} underlined above, ${listed} listed here.`;
}

// Wrap each unsupported sentence found in the text in sentinels, so inline() can turn it into a
// <mark>. A sentence that is not found as written goes to `missed` and is listed instead.
const MARK_ON = "\u0001", MARK_OFF = "\u0002";
function markUnsupported(text, sentences) {
  let t = String(text);
  const missed = [];
  for (const u of sentences) {
    const i = u ? t.indexOf(u) : -1;
    if (i < 0) { missed.push(u); continue; }
    t = `${t.slice(0, i)}${MARK_ON}${u}${MARK_OFF}${t.slice(i + u.length)}`;
  }
  return { text: t, missed };
}

function applyMarks(parts) {
  const out = [];
  let cur = null;
  const put = (v) => (cur ? cur.push(v) : out.push(v));
  for (const p of parts) {
    if (typeof p !== "string") { put(p); continue; }
    for (const seg of p.split(/([\u0001\u0002])/)) {
      if (seg === MARK_ON) cur = [];
      else if (seg === MARK_OFF) {
        if (cur) out.push(h("mark", { class: "unsupported" }, ...cur, h("span", { class: "unsupported-q", "aria-hidden": "true", text: "?" }),
          h("span", { class: "sr-only", text: " (not confirmed by the cited record)" })));
        cur = null;
      } else if (seg) put(seg);
    }
  }
  if (cur) out.push(...cur);
  return out;
}

function inline(text, ctx) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(/\[([^[\]]+)\]/g)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    for (const id of m[1].split(/[,;]\s*/).filter(Boolean)) out.push(citeBtn(id.trim(), ctx));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return text.includes(MARK_ON) || text.includes(MARK_OFF) ? applyMarks(out) : out;
}

// A citation reads as the brief shows the record: an opportunity number, an option's
// name with "(sample)" for a SYNTHETIC record, or an industry lead's number (U8).
function citeBtn(id, ctx) {
  const known = ctx.label ? ctx.label(id) : null;
  const text = known ? known.text : leadLabel(id) || id.replace(/^grants_gov:/, "");
  return h("button", { class: `cite${known && known.sample ? " sample" : ""}`,
    "aria-label": `Evidence: ${known ? known.full || known.text : id}`, onclick: (e) => ctx.openEvidence(id, e.currentTarget) },
  h("span", { text }));
}

// Route B lead ids look like "<brief>:B2"; show them as "Industry lead 2".
function leadLabel(id) {
  const m = id.match(/:B(\d+)$/);
  return m ? `Industry lead ${m[1]}` : null;
}

function askForm(ctx, busy) {
  return h("form", { class: "scout-ask", onsubmit: (e) => { e.preventDefault(); send(ctx); } },
    h("label", { for: "scout-q", class: "sr-only", text: T.data ? "Ask a follow-up" : "Ask Scout" }),
    h("div", { class: "scout-ask-row" },
      h("input", { id: "scout-q", type: "text", maxlength: "1000", autocomplete: "off", value: T.draft,
        placeholder: T.data ? "Ask a follow-up" : ctx.student ? "Ask Scout, for example: only options with a deadline after March" : "Ask Scout, for example: only R21s that close by March",
        oninput: (e) => { T.draft = e.target.value; } }),
      h("button", { class: "btn primary", type: "submit", disabled: busy }, h("span", { text: "Ask" })),
      // F9: always there once a conversation has begun, not only at the budget stop.
      T.data ? h("button", { class: "btn quiet scout-new", type: "button", "data-key": "scout-new-any", disabled: busy,
        "aria-label": "New conversation", title: "Start a new conversation", onclick: () => newConversation(ctx) },
      h("span", { class: "new-long", "aria-hidden": "true", text: "New conversation" }),
      h("span", { class: "new-short", "aria-hidden": "true", text: "New" })) : null));
}

async function send(ctx) {
  const q = T.draft.trim();
  if (!q || T.sending) return;
  if (START_OVER.test(q) && T.data) { T.draft = ""; newConversation(ctx); return; }
  T.sending = true;
  T.stick = true;  // asking jumps to the newest reply
  T.error = null;
  ctx.rerender();
  try {
    T.data = T.data ? await ctx.api.scoutAct(T.data.id, "ask", { question: q })
      : await ctx.api.scoutStart(ctx.briefId, { question: q });
    T.draft = "";
    poll(ctx);
    pinChat();
  } catch (e) {
    T.error = e.message;
  }
  T.sending = false;
  ctx.rerender();
}

async function stop(ctx) {
  if (!T.data || T.stopping) return;
  T.stopping = true;
  ctx.rerender();
  try {
    T.data = await ctx.api.scoutAct(T.data.id, "stop", {});
  } catch (e) {
    T.error = e.message;
  }
  ctx.rerender();
}

function poll(ctx) {
  clearTimeout(T.timer);
  if (!T.data || !T.data.busy) return;
  const id = T.data.id, brief = T.briefId;
  T.timer = setTimeout(async () => {
    if (T.briefId !== brief) return;
    try {
      T.data = await ctx.api.scoutGet(id);
      if (!T.data.busy) {
        const last = T.data.exchanges[T.data.exchanges.length - 1];
        ctx.announce(last && last.by_user ? "Scout stopped." : "Scout answered.");
        T.stopping = false;
      }
    } catch (e) {
      T.error = e.message;
      T.data = { ...T.data, busy: false };
    }
    ctx.rerender();
    poll(ctx);
  }, POLL_MS);
}
