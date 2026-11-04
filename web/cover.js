// Cover-letter points on a lead card (S46). One button asks for the points for one record of
// the open brief (POST /briefs/{id}/cover-points); the page polls the job and shows the result
// with scout.js's pointsBlock. The busy state and the results live here, outside the card
// render, so a card that is rebuilt while the job runs comes back in the same state.

import { h, icon } from "./dom.js";
import { pointsBlock } from "./scout.js";

export const COVER_HINT = "A model writes these from your CV and papers. You put them in your own words.";
export const COVER_WAIT = "A model is reading the record and your CV. This takes up to two minutes…";
export const COVER_READY = "The points are ready below.";
export const COVER_SIGNIN = "Sign in to get cover-letter points";
export const COVER_FAILED = "The points could not be made. Try again.";
export const COVER_NOT_DONE = "Cover points start once the brief has finished.";
const POLL_MS = 2000;
const POLL_MAX_MS = 150000;

// key -> { busy, error, signin, result, restored }; each drawn block rebuilds itself from it.
const STATE = new Map();
const NODES = new Map();
let UI = null; // the latest context: { api, announce, openEvidence, label }

const keyOf = (briefId, recordId) => `${briefId}|${recordId}`;
const st = (k) => {
  if (!STATE.has(k)) STATE.set(k, { busy: false, error: null, signin: false, result: null, restored: false });
  return STATE.get(k);
};

export function resetCover() {
  STATE.clear();
  NODES.clear();
}

// The stored set has record_id, title and sample; pointsBlock reads them under `for`.
function asPoints(r) {
  return { ...r, for: { id: r.record_id, title: r.title, sample: r.sample } };
}

export function coverError(e) {
  if (e && e.status === 429 && e.code === "quota_exceeded") return { text: e.serverMessage || e.message };
  if (e && e.status === 429) {
    const n = Number.parseInt(e.retryAfter, 10);
    return { text: Number.isFinite(n) && n > 0 ? `Too many requests. Try again in ${n} seconds.`
      : "Too many requests. Try again in a little while." };
  }
  if (e && e.status === 409) return { text: COVER_NOT_DONE };
  if (e && e.status === 403) return { signin: true };
  if (e && e.status === 0) return { text: e.message };
  return { text: COVER_FAILED };
}

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
  Object.assign(s, { busy: true, error: null, signin: false });
  draw(k, "button");
  const { api, announce } = UI;
  try {
    const job = await api.coverStart(briefId, recordId);
    const end = Date.now() + POLL_MAX_MS;
    for (;;) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      const got = await api.coverGet(briefId, recordId, job.job_id);
      const state = got.job && got.job.state;
      if (state === "succeeded" && got.result) {
        s.result = got.result;
        s.busy = false;
        draw(k, "result");
        announce(COVER_READY);
        return;
      }
      if (!got.job || state === "succeeded" || ["failed", "dead", "cancelled"].includes(state)) throw new Error("job");
      if (Date.now() > end) throw new Error("timeout");
    }
  } catch (e) {
    const c = coverError(e);
    Object.assign(s, { busy: false, error: c.text || null, signin: Boolean(c.signin) });
    draw(k, "button");
  }
}

// One GET on first draw brings back points that are already stored.
async function restore(k, briefId, recordId, api) {
  const s = st(k);
  if (s.restored) return;
  s.restored = true;
  try {
    const got = await api.coverGet(briefId, recordId, null);
    if (got.result && !s.busy) { s.result = got.result; draw(k, null); }
  } catch { /* nothing stored, or no access: the button stays */ }
}

// The block for one card. `ctx`: { api, announce, openEvidence, label, guest, signIn }.
export function coverBlock(ctx, briefId, recordId) {
  if (!ctx.api || ctx.api.mode !== "live" || !ctx.api.coverStart) return null;
  UI = ctx;
  const k = keyOf(briefId, recordId);
  const s = st(k);
  const build = () => {
    if (ctx.guest) {
      return [h("a", { class: "btn", href: ctx.signIn, "data-key": `cover-${recordId}`, text: COVER_SIGNIN })];
    }
    const out = [h("div", { class: "actions" },
      h("button", { class: "btn", type: "button", "data-key": `cover-${recordId}`, disabled: s.busy,
        "aria-busy": s.busy ? "true" : null, onclick: () => run(k, briefId, recordId) },
      icon("pen"), h("span", { text: s.result ? "Points again" : "Cover-letter points" }))),
    h("p", { class: "hint", text: COVER_HINT })];
    if (s.busy) out.push(h("p", { class: "hint", role: "status", text: COVER_WAIT }));
    else if (s.signin) {
      out.push(h("p", { class: "notice error", role: "alert" }, icon("warn"),
        h("span", {}, h("span", { text: "Sign in to get cover-letter points. " }),
          h("a", { href: ctx.signIn, text: "Sign in" }))));
    } else if (s.error) out.push(h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: s.error })));
    if (s.result) out.push(pointsBlock(asPoints(s.result), ctx));
    return out;
  };
  const box = h("div", { class: "cover", "data-cover": recordId });
  if (!NODES.has(k)) NODES.set(k, new Map());
  NODES.get(k).set(box, build);
  box.replaceChildren(...build());
  if (!ctx.guest && !s.restored) restore(k, briefId, recordId, ctx.api);
  return box;
}
