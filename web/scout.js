// Ask Scout: follow-up questions about a finished brief (S10). Each tool Scout wants to
// use is a card. In "Ask before every step" mode a card waits for Approve or Skip; in
// "Run and show me" it runs at once. Answers cite records; a citation opens the record.

import { h, fill, icon } from "./dom.js";
import { owl } from "./owl.js";

const POLL_MS = 1200;
const TOOLS = {
  resolve_author: "Find the researcher", build_profile: "Read the research profile",
  list_awards: "List public awards", search_opportunities: "Search opportunities",
  get_org_signals: "Industry signals", explain_fit: "Explain the fit",
  compare: "Compare leads", draft_handoff: "Draft a hand-off", get_record: "Open a record",
};
const ARGS = {
  route: "Route", author_id: "Researcher", min_amount: "Ceiling at least", max_amount: "Ceiling at most",
  agencies: "Agencies", exclude_agencies: "Not these agencies", closes_by: "Closes by",
  activity_codes: "Activity codes", keywords: "Mentions", exclude_keywords: "Does not mention",
  top: "How many", id: "Record", opportunity_id: "Opportunity", opportunity_ids: "Opportunities",
  ids: "Leads", office: "Office",
  name: "Name",
};
const STATUS = { proposed: "Waiting for you", done: "Done", skipped: "Skipped", refused: "Refused", error: "Failed", repeated: "Repeat, not run again" };
const EXAMPLES = ["Only R21 grants that close by 2027-03-01", "Small grants only: a ceiling of $200k or less",
  "Drop anything that mentions clinical trials", "Why does the top lead fit?"];

// One Scout conversation per brief, kept while the brief is on screen.
const T = { briefId: null, data: null, mode: "ask", error: null, timer: null, draft: "", sending: false };

export function renderScout(panel, ctx) {
  if (T.briefId !== ctx.briefId) reset(ctx.briefId);
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
  const busy = Boolean(T.data && T.data.busy) || T.sending;
  const view = h("div", { class: "scout" },
    h("div", { class: "scout-intro" },
      h("p", { class: "lede", text: "Ask Scout to narrow or explain this brief." }),
      h("p", { class: "hint", text: "Scout can only use Perch’s own tools on public records. It cannot browse the web, send anything or change a record. Every fact in an answer links to its record." })),
    modeSwitch(ctx),
    h("ol", { class: "scout-log", "aria-live": "polite" }, ...(T.data ? T.data.exchanges.map((x) => exchange(x, ctx, busy)) : [])),
    T.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: T.error })) : null,
    askForm(ctx, busy),
    T.data ? h("p", { class: "hint scout-meta", text: `Model ${T.data.model}. ${T.data.tokens.toLocaleString()} tokens so far in this conversation.` }) : null);
  const focused = document.activeElement && document.activeElement.id;
  fill(panel, view);
  if (focused === "scout-q") {
    const q = panel.querySelector("#scout-q");
    q.focus();
    q.setSelectionRange(q.value.length, q.value.length);
  }
}

function reset(briefId) {
  clearTimeout(T.timer);
  Object.assign(T, { briefId, data: null, error: null, timer: null, draft: "", sending: false });
}

function modeSwitch(ctx) {
  const opt = (value, label, hint) => h("label", { class: "scout-mode-opt" },
    h("input", { type: "radio", name: "scout-mode", value, checked: T.mode === value,
      onchange: () => setMode(value, ctx) }),
    h("span", {}, h("b", { text: label }), h("span", { class: "hint", text: hint })));
  return h("fieldset", { class: "scout-mode" }, h("legend", { class: "mini", text: "How Scout works" }),
    opt("ask", "Ask before every step", "You approve each tool before it runs."),
    opt("run", "Run and show me", "Tools run at once; you see each one."));
}

async function setMode(mode, ctx) {
  const was = T.mode;
  T.mode = mode;
  if (!T.data || T.data.mode === mode) return ctx.rerender();
  try {
    T.data = await ctx.api.scoutAct(T.data.id, "mode", {});
    poll(ctx);
  } catch (e) {
    T.mode = was;
    T.error = e.message;
  }
  ctx.rerender();
}

function exchange(x, ctx, busy) {
  const running = x.status === "running" || x.status === "awaiting_approval";
  return h("li", { class: "scout-x" },
    h("p", { class: "scout-q" }, h("span", { class: "sr-only", text: "You asked: " }), x.question),
    x.cards.length ? h("ol", { class: "scout-cards" }, ...x.cards.map((c) => card(c, ctx, busy))) : null,
    answer(x, ctx, running && busy));
}

function card(c, ctx, busy) {
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
    c.draft ? draftBlock(c.draft, ctx) : null,
    c.status === "proposed" ? h("div", { class: "scout-actions" },
      h("button", { class: "btn primary", disabled: busy, onclick: () => act(ctx, "approve", c.id) }, icon("keep"), h("span", { text: "Approve" })),
      h("button", { class: "btn", disabled: busy, onclick: () => act(ctx, "skip", c.id) }, h("span", { text: "Skip" }))) : null);
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
  if (x.status === "awaiting_approval") return null;
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
  const waiting = T.data && T.data.exchanges.some((x) => x.status === "awaiting_approval");
  return h("form", { class: "scout-ask", onsubmit: (e) => { e.preventDefault(); send(ctx); } },
    h("label", { for: "scout-q", class: "mini", text: T.data ? "Ask a follow-up" : "Your question" }),
    h("div", { class: "scout-ask-row" },
      h("input", { id: "scout-q", type: "text", maxlength: "1000", autocomplete: "off", value: T.draft,
        placeholder: "For example: only NIH, ceiling at least $500k", oninput: (e) => { T.draft = e.target.value; } }),
      h("button", { class: "btn primary", type: "submit", disabled: busy || waiting }, h("span", { text: "Ask" }))),
    waiting ? h("p", { class: "hint", text: "Approve or skip Scout’s step above first." }) : null,
    !T.data && ctx.api.recordedQuestion ? h("p", { class: "hint", text: "This preview plays back one recorded question. Tap it below." }) : null,
    !T.data ? h("ul", { class: "chips" }, ...(ctx.api.recordedQuestion ? [ctx.api.recordedQuestion] : EXAMPLES).map((q) => h("li", {},
      h("button", { class: "chip", type: "button", onclick: () => { T.draft = q; send(ctx); } }, q)))) : null);
}

async function send(ctx) {
  const q = T.draft.trim();
  if (!q || T.sending) return;
  T.sending = true;
  T.error = null;
  ctx.rerender();
  try {
    T.data = T.data ? await ctx.api.scoutAct(T.data.id, "ask", { question: q })
      : await ctx.api.scoutStart(ctx.briefId, { question: q, mode: T.mode });
    T.draft = "";
    poll(ctx);
  } catch (e) {
    T.error = e.message;
  }
  T.sending = false;
  ctx.rerender();
}

async function act(ctx, action, cardId) {
  T.error = null;
  try {
    T.data = await ctx.api.scoutAct(T.data.id, action, { card_id: cardId });
    ctx.announce(action === "approve" ? "Approved. Scout is running that step." : "Skipped.");
    poll(ctx);
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
      if (!T.data.busy) ctx.announce(T.data.status === "awaiting_approval" ? "Scout has a step for you to approve." : "Scout answered.");
    } catch (e) {
      T.error = e.message;
      T.data = { ...T.data, busy: false };
    }
    ctx.rerender();
    poll(ctx);
  }, POLL_MS);
}
