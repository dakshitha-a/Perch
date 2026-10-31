// Ask Scout: follow-up questions about a finished brief (S10). Each tool Scout uses is a
// card, and each runs as soon as the model asks for it (S27: the ask-first mode is gone).
// Answers cite records; a citation opens the record. The chat reads like a chat window:
// the question box stays at the bottom and older replies scroll up and fade (S27).

import { h, fill, icon } from "./dom.js";
import { owl } from "./owl.js";

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
};
const STATUS = { proposed: "Running…", done: "Done", skipped: "Skipped", refused: "Refused", error: "Failed", repeated: "Repeat, not run again" };
const EXAMPLES = ["Only R21 grants that close by 2027-03-01", "Small grants only: a ceiling of $200k or less",
  "Drop anything that mentions clinical trials", "Why does the top lead fit?"];

// One Scout conversation per brief, kept while the brief is on screen.
// Scout runs every step as soon as the model asks for it and shows each one; the ask-first
// switch is gone (Dakshitha, S27; the server's ask mode goes in S28).
const T = { briefId: null, data: null, mode: "run", error: null, timer: null, draft: "", sending: false, seen: 0, stick: true, top: 0 };

// Stop polling and forget the conversation when the session has ended (S27).
export function resetScout() {
  clearTimeout(T.timer);
  Object.assign(T, { briefId: null, data: null, error: null, timer: null, draft: "", sending: false, seen: 0, stick: true, top: 0 });
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
  const sig = JSON.stringify([key, T.data, T.error, T.sending]);
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
    h("ol", { class: "scout-log", "aria-live": "polite" }, ...(T.data ? T.data.exchanges.map((x, i) => exchange(x, ctx, busy, i >= T.seen)) : [])),
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
  const under = tabs ? tabs.getBoundingClientRect().bottom - Math.min(0, tabs.getBoundingClientRect().top) : 0;
  window.scrollTo({ top: Math.max(0, top - under - 4) });
}

window.addEventListener("resize", () => {
  const view = document.querySelector("#panel > .scout");
  if (view) fitChat(view, false);
});

function reset(briefId) {
  clearTimeout(T.timer);
  Object.assign(T, { briefId, data: null, error: null, timer: null, draft: "", sending: false, seen: 0, stick: true, top: 0 });
}

function exchange(x, ctx, busy, fresh) {
  const running = x.status === "running";
  return h("li", { class: fresh ? "scout-x new" : "scout-x" },
    h("p", { class: "scout-q" }, h("span", { class: "sr-only", text: "You asked: " }), x.question),
    x.cards.length ? h("ol", { class: "scout-cards" }, ...x.cards.map((c) => card(c, ctx))) : null,
    answer(x, ctx, running && busy));
}

function card(c, ctx) {
  const args = Object.entries(c.arguments || {}).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length));
  return h("li", { class: `scout-card s-${c.status}` },
    h("div", { class: "scout-card-head" },
      h("span", { class: "scout-tool", text: TOOLS[c.tool] || c.tool }),
      h("code", { class: "scout-tool-name", text: c.tool }),
      h("span", { class: "scout-status", text: STATUS[c.status] || c.status })),
    args.length ? h("ul", { class: "chips" }, ...args.map(([k, v]) => h("li", { class: "chip",
      text: `${ARGS[k] || k}: ${Array.isArray(v) ? v.join(", ") : v}` }))) : null,
    c.detail ? h("p", { class: "hint", text: c.detail }) : null,
    c.records && c.records.length ? h("p", { class: "scout-records" }, h("span", { class: "hint", text: "Records: " }),
      ...c.records.slice(0, 8).map((id) => citeBtn(id, ctx))) : null,
    c.draft ? draftBlock(c.draft, ctx) : null);
}

// A hand-off draft from draft_handoff: the full text to copy. Never sent.
function draftBlock(d, ctx) {
  const text = `Subject: ${d.subject}\n\n${d.body}`;
  return h("details", { class: "scout-draft" },
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
  if (thinking) return h("p", { class: "scout-wait" }, owl("look", "owl-sm"), h("span", { text: "Scout is working…" }));
  if (x.answer) return h("div", { class: "scout-answer" }, ...withCites(x.answer, ctx));
  if (x.flagged) return h("p", { class: "notice warn" }, icon("warn"), h("span", { text: "Scout’s answer was withheld: it did not pass the citation check twice. The tool cards above show what it found." }));
  if (x.status === "stopped" || x.status === "failed") return h("p", { class: "notice warn" }, icon("warn"), h("span", { text: `Scout stopped: ${(x.errors || []).join("; ") || "no answer"}.` }));
  return null;
}

// "[id]" and "[id, id]" become buttons that open the record in the evidence panel.
function withCites(text, ctx) {
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

function citeBtn(id, ctx) {
  return h("button", { class: "cite", "aria-label": `Evidence: ${id}`, onclick: (e) => ctx.openEvidence(id, e.currentTarget) },
    h("span", { text: leadLabel(id) || id.replace(/^grants_gov:/, "") }));
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
      : await ctx.api.scoutStart(ctx.briefId, { question: q, mode: T.mode });
    T.draft = "";
    poll(ctx);
    pinChat();
  } catch (e) {
    T.error = e.message;
  }
  T.sending = false;
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
      if (!T.data.busy) ctx.announce("Scout answered.");
    } catch (e) {
      T.error = e.message;
      T.data = { ...T.data, busy: false };
    }
    ctx.rerender();
    poll(ctx);
  }, POLL_MS);
}
