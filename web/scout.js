// Ask Scout: follow-up questions about a finished brief (S10). Each tool Scout uses is a
// card, and each runs as soon as the model asks for it (S27: the ask-first mode is gone).
// Answers cite records; a citation opens the record. The chat reads like a chat window:
// the question box stays at the bottom and older replies scroll up and fade (S27).

import { h, fill, icon } from "./dom.js";
import { owl } from "./owl.js";
import { money } from "./format.js";

const POLL_MS = 1200;
const TOOLS = {
  resolve_author: "Find the researcher", build_profile: "Read the research profile",
  list_awards: "List public awards", search_opportunities: "Search opportunities",
  get_org_signals: "Industry signals", explain_fit: "Explain the fit",
  compare: "Compare leads", draft_handoff: "Draft a hand-off", get_record: "Open a record",
  search_options: "Search options", check_option: "Check against your CV", explain_verdict: "Explain a verdict",
  read_cv: "What Perch read", compare_options: "Compare options", draft_note: "Draft a note",
};
// The rail lists what Scout can use; students get their own tools (S24, Q27 revised).
const CAN_USE = {
  researcher: ["Search with filters: agency, ceiling, close date, activity code, words",
    "Industry leads and their signals", "Any record in the brief", "Public awards and the research profile",
    "A fit explanation", "Compare chosen or kept leads", "A hand-off draft, shown for you to copy"],
  student: ["Search fellowships and sample scholarships with filters: verdict, deadline, amount, words",
    "Check one option against your CV by rule", "Explain a verdict and what is still needed",
    "What Perch read from your CV", "Compare chosen or kept options", "A note to a Temple office, shown for you to copy"],
};
const STUDENT_EXAMPLES = ["Only options with a deadline after 2027-03-01", "Why is my top fellowship “may be eligible”?",
  "What do my kept options still need?", "Draft a note about my kept fellowships"];
const ARGS = {
  route: "Route", author_id: "Researcher", min_amount: "Ceiling at least", max_amount: "Ceiling at most",
  agencies: "Agencies", exclude_agencies: "Not these agencies", closes_by: "Closes by",
  activity_codes: "Activity codes", keywords: "Mentions", exclude_keywords: "Does not mention",
  top: "How many", id: "Record", opportunity_id: "Opportunity", opportunity_ids: "Opportunities",
  ids: "Leads", office: "Office",
  name: "Name",
  // student tools (S28: the read-as line showed their raw keys)
  deadline_after: "Deadline after", deadline_before: "Deadline before", verdict: "Verdict",
  words: "Mentions", option_id: "Option",
};
const STATUS = { proposed: "Running…", done: "Done", not_run: "Not run", refused: "Refused", error: "Failed", repeated: "Repeat, not run again" };
const EXAMPLES = ["Only R21 grants that close by 2027-03-01", "Small grants only: a ceiling of $200k or less",
  "Drop anything that mentions clinical trials", "Why does the top lead fit?"];

// One Scout conversation per brief, kept while the brief is on screen.
// Scout runs every step as soon as the model asks for it and shows each one (S27, S28).
const T = { briefId: null, data: null, error: null, timer: null, draft: "", sending: false, stopping: false, openSteps: new Set(), seen: 0, stick: true, top: 0 };

// Stop polling and forget the conversation when the session has ended (S27).
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
  if (!ctx.done) {
    fill(panel, h("div", { class: "empty" }, owl("look", "owl-md"), h("div", {},
      h("p", { class: "lede", text: "Scout can help once the brief has finished." }),
      h("p", { class: "hint", text: "Then ask follow-up questions, such as “only R21s” or “under $200k”." }))));
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
    T.data ? h("p", { class: "scout-meta", text: `Model ${T.data.model}. ${T.data.tokens.toLocaleString()} tokens so far in this conversation.` }) : null),
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
          ? "I cite records. A date or amount not in a cited record is rewritten once, then withheld. I stop after eight model calls for one question, cannot browse the web, send anything or change a record, and run on a local model, because your CV is in this session. Sample scholarships stay marked as samples. The conversation ends with the session."
          : "I cite records. A date or amount not in a cited record is rewritten once, then withheld. I stop after eight model calls for one question, cannot browse the web, send anything or change a record, and run on a local model. The conversation ends with the session." }))));
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
  const running = x.status === "running";
  const drafts = x.cards.filter((c) => c.draft);
  return h("li", { class: fresh ? "scout-x new" : "scout-x" },
    h("p", { class: "scout-q" }, h("span", { class: "sr-only", text: "You asked: " }), x.question),
    readAs(x, ctx),
    answer(x, ctx, running && busy),
    ...drafts.map((c) => draftBlock(c.draft, ctx)),
    x.cards.length ? h("details", { class: "scout-steps", open: T.openSteps.has(i),
      ontoggle: (e) => { if (e.target.open) T.openSteps.add(i); else T.openSteps.delete(i); } },
      h("summary", { text: `Steps (${x.cards.length})` }),
      h("ol", { class: "scout-cards" }, ...x.cards.map((c) => card(c, ctx)))) : null);
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
// Record keys in a step's filters read as the brief names them (U8).
const ID_ARGS = new Set(["id", "ids", "opportunity_id", "opportunity_ids", "option_id"]);
function argList(c, ctx) {
  const name = (v) => { const k = ctx && ctx.label ? ctx.label(String(v)) : null;
    return k ? k.name : leadLabel(String(v)) || String(v).replace(/^grants_gov:/, ""); };
  return Object.entries(c.arguments || {}).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => [k, k === "route" ? ROUTES[v] || v
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

// Where a step ran (S28): code, a local model, or a named Cloud provider, matching the
// header chip. Recordings made before S28 carry no "where" and show no tag.
const CLOUD_NAMES = { anthropic: "Anthropic" };
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
    d.opening_withheld ? h("p", { class: "hint", text: "The model’s opening failed the checks twice; a plain sentence replaces it." }) : null,
    h("pre", { class: "draft-text", text }),
    h("div", { class: "scout-actions" },
      h("button", { class: "btn", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(text); ctx.announce("The draft is copied."); }
        catch { ctx.announce("Copying was blocked by the browser. Select the text and copy it by hand."); }
      } }, h("span", { text: "Copy the draft" })),
      h("a", { class: "btn quiet", href: d.office_page, target: "_blank", rel: "noopener", text: "Office page" })),
    h("p", { class: "hint", text: "Perch never sends this. The To line is yours to fill in." }));
}

function answer(x, ctx, thinking) {
  // Stop ends the question between steps; the steps already done stay (S28).
  const now = x.cards.find((c) => c.status === "proposed");
  if (thinking) return h("div", { class: "scout-wait" }, owl("look", "owl-sm"),
    h("span", { text: T.stopping ? "Stopping after this step…" : now ? `${TOOLS[now.tool] || now.tool}…` : "Scout is working…" }),
    h("button", { class: "btn quiet scout-stop", type: "button", disabled: T.stopping, onclick: () => stop(ctx) }, icon("stop"), h("span", { text: "Stop" })));
  if (x.status === "stopped" && x.by_user) return h("p", { class: "hint scout-stopped", text: "You stopped this question. The steps below show what ran; ask again to go on." });
  // Model prose says so in words, not by its tint alone (U7).
  if (x.answer) return h("div", { class: "scout-answer" },
    h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Model text" }),
      h("span", { text: "Written by a model; checked against the records it cites." })),
    ...withCites(x.answer, ctx));
  if (x.flagged) return h("p", { class: "notice warn" }, icon("warn"), h("span", { text: "Scout’s answer was withheld: it did not pass the citation check twice. The steps below show what it found." }));
  if (x.status === "stopped" || x.status === "failed") return h("p", { class: "notice warn" }, icon("warn"), h("span", { text: `Scout stopped: ${(x.errors || []).join("; ") || "no answer"}.` }));
  return null;
}

// The model's text, tidied for reading (U8): lines that start with "* " or "- " become a
// list, "**" marks go, and amounts read as the cards write them ($200,000, not
// $200,000.0). "[id]" and "[id, id]" become buttons that open the record.
function withCites(text, ctx) {
  const clean = String(text).replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\$(\d[\d,]*(?:\.\d+)?)/g, (m, n) => (Number.isFinite(Number(n.replace(/,/g, ""))) ? money(Number(n.replace(/,/g, ""))) : m));
  const out = [];
  let list = null;
  for (const line of clean.split("\n")) {
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

function inline(text, ctx) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(/\[([^[\]]+)\]/g)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    for (const id of m[1].split(/[,;]\s*/).filter(Boolean)) out.push(citeBtn(id.trim(), ctx));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
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
      h("button", { class: "btn primary", type: "submit", disabled: busy }, h("span", { text: "Ask" }))));
}

async function send(ctx) {
  const q = T.draft.trim();
  if (!q || T.sending) return;
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
