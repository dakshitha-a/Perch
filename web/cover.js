// Cover-letter points on a lead card (S46). One button asks for the points for one record of
// the open brief (POST /briefs/{id}/cover-points); the page polls the job and shows the result
// with scout.js's pointsBlock. The busy state and the results live here, outside the card
// render, so a card that is rebuilt while the job runs comes back in the same state.

import { h, icon } from "./dom.js";
import { pointsBlock } from "./scout.js";

export const COVER_HINT = {
  student: "A model writes these from your CV and entries. You put them in your own words.",
  researcher: "A model writes these from your CV, entries and the papers the record cites. You put them in your own words.",
};
export const COVER_WAIT = "A model is reading the record and your CV. This takes up to two minutes…";
export const COVER_READY = "The points are ready below.";
export const COVER_SIGNIN = "Sign in to get cover-letter points";
export const COVER_FAILED = "The points could not be made. Try again.";
export const COVER_NOT_DONE = "Cover points start once the brief has finished.";
export const COVER_SLOW = "Still running. Try again in a minute.";
export const COVER_CONSENT = "Agree to the consent first.";
const COVER_NEEDS_CONSENT = "Cover-letter points use your CV, so they need your consent first. ";
export const COVER_QUOTA_CARD = "Today’s allowance is used. See the note above the list.";
const QUOTA_DEFAULT = "You have used today’s model allowance.";
const POLL_MS = 2000;
const POLL_MAX_MS = 150000;

// key -> { busy, error, quota, signin, consent, slow, jobId, result, tried }; each drawn block rebuilds itself from it.
const STATE = new Map();
const NODES = new Map();
// The daily-allowance note for this page view: { text, resetsAt } once a points request is refused.
let QUOTA = null;
let UI = null; // the latest context: { api, announce, openEvidence, label }

const keyOf = (briefId, recordId) => `${briefId}|${recordId}`;
const st = (k) => {
  if (!STATE.has(k)) STATE.set(k, { busy: false, error: null, quota: false, signin: false, consent: false, slow: false, jobId: null, result: null, tried: false });
  return STATE.get(k);
};

export function resetCover() {
  STATE.clear();
  NODES.clear();
  QUOTA = null;
}

// The stored set has record_id, title and sample; pointsBlock reads them under `for`.
function asPoints(r) {
  return { ...r, for: { id: r.record_id, title: r.title, sample: r.sample } };
}

export function coverError(e) {
  if (e && e.status === 429 && e.code === "quota_exceeded") return { quota: true, text: e.serverMessage || QUOTA_DEFAULT };
  if (e && e.status === 429) {
    const n = Number.parseInt(e.retryAfter, 10);
    return { text: Number.isFinite(n) && n > 0 ? `Too many requests. Try again in ${n} seconds.`
      : "Too many requests. Try again in a little while." };
  }
  if (e && e.status === 409) return { text: COVER_NOT_DONE };
  if (e && e.status === 403) return e.code === "consent_required" ? { consent: true } : { signin: true };
  if (e && e.message === "timeout") return { slow: true, text: COVER_SLOW };
  if (e && e.status === 0) return { text: e.message };
  return { text: COVER_FAILED };
}

const onPage = (k) => [...(NODES.get(k) || [])].some(([n]) => n.isConnected);

function draw(k, focus) {
  const nodes = NODES.get(k);
  if (!nodes) return;
  for (const [node, build] of [...nodes]) {
    if (!node.isConnected) { nodes.delete(node); continue; }
    node.replaceChildren(...build());
    if (focus === "result") { const t = node.querySelector(".scout-points summary"); if (t) t.focus(); }
    else if (focus === "button") { const t = node.querySelector("[data-key^=cover-]"); if (t) t.focus(); }
  }
}

async function run(k, briefId, recordId) {
  const s = st(k);
  if (s.busy) return;
  const again = Boolean(s.result) && !s.jobId; // a finished set asks for a fresh one; a slow job is resumed
  Object.assign(s, { busy: true, error: null, quota: false, signin: false, consent: false, slow: false });
  draw(k, "button");
  const { api, announce } = UI;
  announce(COVER_WAIT);
  try {
    if (!s.jobId) s.jobId = (await api.coverStart(briefId, recordId, again)).job_id;
    const end = Date.now() + POLL_MAX_MS;
    for (;;) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      if (!onPage(k)) { s.busy = false; return; } // the user left the brief: stop, say nothing
      const got = await api.coverGet(briefId, recordId, s.jobId);
      const state = got.job && got.job.state;
      if (state === "succeeded" && got.result) {
        Object.assign(s, { result: got.result, busy: false, jobId: null });
        draw(k, "result");
        if (onPage(k)) announce(COVER_READY);
        return;
      }
      if (!got.job || state === "succeeded" || ["failed", "dead", "cancelled"].includes(state)) throw new Error("job");
      if (Date.now() > end) throw new Error("timeout");
    }
  } catch (e) {
    const c = coverError(e);
    if (!c.slow) s.jobId = null; // a slow job keeps its id, so the next press resumes it
    Object.assign(s, { busy: false, error: c.text || null, quota: false, signin: Boolean(c.signin), consent: Boolean(c.consent), slow: Boolean(c.slow) });
    // One note above the list says the allowance is used; the card keeps a short pointer to it (U6).
    if (c.quota) {
      QUOTA = { text: c.text, resetsAt: QUOTA ? QUOTA.resetsAt : null };
      if (!QUOTA.resetsAt && api.usage) {
        try { QUOTA.resetsAt = (await api.usage()).resets_at || null; } catch { /* the note then has no time */ }
      }
      if (drawListNotice()) Object.assign(s, { quota: true, error: null });
    }
    draw(k, "button");
  }
}

// The brief payload lists the records that have stored points; only those cards make a GET.
async function restore(k, briefId, recordId, api) {
  const s = st(k);
  if (s.tried || s.busy || s.result) return;
  s.tried = true;
  try {
    const got = await api.coverGet(briefId, recordId, null);
    if (got.result && !s.busy) { s.result = got.result; draw(k, null); }
  } catch { /* no access: the button stays */ }
}

// The time the allowance comes back, in local time. A date comes first when it is not today.
function backAt(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return time;
  const opts = d.getFullYear() === now.getFullYear() ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" };
  return `${d.toLocaleDateString([], opts)} ${time}`;
}

const quotaLine = () => {
  const at = QUOTA.resetsAt ? backAt(QUOTA.resetsAt) : "";
  return h("p", { class: "notice info list-note", role: "status", "data-cover-line": "" }, icon("clock"),
    h("span", { text: `${QUOTA.text}${at ? ` It comes back at ${at}.` : ""}` }));
};

// Redraw the cover line inside #list-notices, leaving the other notices there alone.
// False when the page has no such slot, so the card shows the error itself.
function drawListNotice() {
  const slot = document.getElementById("list-notices");
  if (!slot) return false;
  slot.querySelectorAll("[data-cover-line]").forEach((n) => n.remove());
  if (QUOTA) slot.append(quotaLine());
  return true;
}

// The one line above a list. A guest is told once, not on every card; a signed-in user reads how
// the points are written once, not on every card (V5); after a refused request the allowance note
// replaces it. `ctx` is the object coverBlock takes.
export function coverListLine(ctx) {
  if (QUOTA) return quotaLine();
  if (ctx && !ctx.guest && ctx.api && ctx.api.mode === "live" && ctx.api.coverStart) {
    return h("p", { class: "list-note", "data-cover-line": "" }, icon("pen"),
      h("span", { text: COVER_HINT[ctx.audience === "student" ? "student" : "researcher"] }));
  }
  if (ctx && ctx.guest && ctx.api && ctx.api.mode === "live") {
    return h("p", { class: "list-note", "data-cover-line": "" }, icon("pen"),
      h("span", {}, h("span", { text: "Cover-letter points need an account. " }), h("a", { href: ctx.signIn, text: "Sign in" })));
  }
  return null;
}

// The block for one card. `ctx`: { api, announce, openEvidence, guest, signIn, audience, stored }.
// `stored` is the brief's cover_points list: record ids that have points saved.
export function coverBlock(ctx, briefId, recordId) {
  if (!ctx.api || ctx.api.mode !== "live" || !ctx.api.coverStart) return null;
  if (ctx.guest) return null; // a guest is told once above the list (coverListLine), not on every card (U16)
  UI = ctx;
  const k = keyOf(briefId, recordId);
  const s = st(k);
  const build = () => {
    const act = h("div", { class: "actions" },
      h("button", { class: "btn", type: "button", "data-key": `cover-${recordId}`,
        "aria-disabled": s.busy ? "true" : null, "aria-busy": s.busy ? "true" : null,
        onclick: () => run(k, briefId, recordId) },
      icon("pen"), h("span", { text: s.result ? "Points again" : "Cover-letter points" })));
    // With a result, the points come first and the action to ask again sits under them (U14).
    const out = s.result ? [pointsBlock(asPoints(s.result), ctx, { short: true }), act] : [act];
    if (s.busy) out.push(h("p", { class: "hint", "data-cover-wait": "", text: COVER_WAIT }));
    else if (s.consent) {
      out.push(h("p", { class: "notice info", role: "status" }, icon("info"),
        h("span", {}, h("span", { text: COVER_NEEDS_CONSENT }), h("a", { class: "btn", href: "#/welcome", text: "Read and agree" }))));
    } else if (s.slow) out.push(h("p", { class: "hint", role: "status", text: COVER_SLOW }));
    else if (s.quota) out.push(h("p", { class: "hint quota-hint", text: COVER_QUOTA_CARD }));
    else if (s.signin) {
      out.push(h("p", { class: "notice error", role: "alert" }, icon("warn"),
        h("span", {}, h("span", { text: "Sign in to get cover-letter points. " }),
          h("a", { href: ctx.signIn, text: "Sign in" }))));
    } else if (s.error) out.push(h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: s.error })));
    return out;
  };
  const box = h("div", { class: "cover", "data-cover": recordId });
  if (!NODES.has(k)) NODES.set(k, new Map());
  NODES.get(k).set(box, build);
  box.replaceChildren(...build());
  if ((ctx.stored || []).includes(recordId)) restore(k, briefId, recordId, ctx.api);
  return box;
}
