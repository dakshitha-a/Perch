// Two back ends with one shape: the live API (perch serve) and replay, which plays a
// saved brief back from window.PERCH_REPLAY (built by scripts/export_replay.py).

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function call(base, path, opts = {}) {
  let r;
  try {
    r = await fetch(base + path, { headers: { "Content-Type": "application/json" }, ...opts });
  } catch {
    throw new ApiError("Perch's server did not answer. Check that `perch serve` is running.", 0);
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(typeof body.detail === "string" ? body.detail
    : `The server answered ${r.status}.`, r.status);
  return body;
}

export function liveApi(base = "") {
  return {
    mode: "live",
    resolve: (q) => call(base, `/authors/resolve?q=${encodeURIComponent(q)}`),
    create: (req) => call(base, "/briefs", { method: "POST", body: JSON.stringify(req) }),
    brief: (id) => call(base, `/briefs/${encodeURIComponent(id)}`),
    setLead: (id, leadId, action) => call(base,
      `/briefs/${encodeURIComponent(id)}/leads/${encodeURIComponent(leadId)}/${action}`,
      { method: "POST" }),
    record: (id) => call(base, `/records/${encodeURIComponent(id)}`),
    compare: (id) => call(base, `/briefs/${encodeURIComponent(id)}/compare`),
    handoff: (id, body) => call(base, `/briefs/${encodeURIComponent(id)}/handoff`,
      { method: "POST", body: JSON.stringify(body) }),
    scoutStart: (id, body) => call(base, `/briefs/${encodeURIComponent(id)}/scout`,
      { method: "POST", body: JSON.stringify(body) }),
    scoutGet: (sid) => call(base, `/scout/${encodeURIComponent(sid)}`),
    scoutAct: (sid, action, body) => call(base, `/scout/${encodeURIComponent(sid)}/${action}`,
      { method: "POST", body: JSON.stringify(body) }),
  };
}

// Seconds each stage takes in replay. Explanations land one per EXPLAIN_STEP.
const REPLAY_STAGE = { researcher: 0.7, works: 0.9, awards: 0.9, profile: 1.4, route_a: 1.4,
  summary: 1.4 };
const EXPLAIN_STEP = 0.9;

export function replayApi(data) {
  const final = data.brief;
  const statuses = {};
  let startedAt = null, startedWall = 0;
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const leadsIn = () => final.leads.map((l) => ({ ...l, status: statuses[l.id] || l.status }));

  function snapshot() {
    const out = clone(final);
    out.leads = leadsIn();
    if (startedAt === null) return out; // opened directly: the finished brief
    let t = (performance.now() - startedAt) / 1000;
    const b = out.brief;
    const stamp = (s) => new Date(startedWall + s * 1000).toISOString();
    b.created_at = stamp(0);
    let clock = 0, running = null;
    for (const s of b.stages) {
      const dur = s.name === "explanations" ? EXPLAIN_STEP * final.leads.length + 0.4
        : REPLAY_STAGE[s.name] || 1;
      if (t >= clock + dur) {
        s.started_at = stamp(clock);
        s.finished_at = stamp(clock + dur);
      } else if (t >= clock) {
        s.status = "running";
        s.started_at = stamp(clock);
        s.finished_at = null;
        s.detail = null;
        running = { name: s.name, at: t - clock };
      } else {
        Object.assign(s, { status: "pending", started_at: null, finished_at: null,
          detail: null });
      }
      clock += dur;
    }
    if (!running) return out;
    b.status = "running";
    const done = (name) => b.stages.find((s) => s.name === name).status !== "running"
      && b.stages.find((s) => s.name === name).status !== "pending";
    if (!done("awards")) { out.awards = []; b.award_horizon = null; b.award_ids = []; }
    if (!done("profile")) { b.threads = []; b.work_ids = []; out.papers = {}; }
    if (!done("route_a")) { out.leads = []; b.lead_ids = []; }
    if (!done("summary")) { b.summary = null; b.topics = []; }
    if (!done("explanations")) {
      const landed = running.name === "explanations" ? Math.floor(running.at / EXPLAIN_STEP) : 0;
      out.leads = out.leads.map((l, i) => (i < landed ? l : { ...l,
        explanation: null, inference: null, cited_ids: [], unsupported: [], flagged: false }));
    }
    return out;
  }

  const find = (id) => {
    const r = data.records;
    return r[id] || r[`https://openalex.org/${id}`] || r[`grants_gov:${id}`] || null;
  };
  const later = (v, ms = 250) => new Promise((ok) => setTimeout(() => ok(v), ms));

  return {
    mode: "replay",
    resolve: () => later({ candidates: data.candidates }, 700),
    create: () => { startedAt = performance.now(); startedWall = Date.now(); return later({ id: final.brief.id }); },
    brief: (id) => (id === final.brief.id ? later(snapshot(), 60)
      : Promise.reject(new ApiError("This preview holds one saved brief only.", 404))),
    setLead: (id, leadId, action) => {
      statuses[leadId] = { keep: "kept", dismiss: "dismissed", restore: "new" }[action];
      return later({ id: leadId, status: statuses[leadId] }, 80);
    },
    record: (id) => {
      const r = find(id);
      return r ? later(clone(r), 120) : Promise.reject(new ApiError(`No record ${id}.`, 404));
    },
    // Later steps, recorded by scripts/export_replay.py (version 2 files). The comparison
    // is filtered to the kept leads; a hand-off draft and a Scout answer play back only
    // for what was recorded, and say so otherwise.
    compare: () => {
      if (!data.compare) return Promise.reject(new ApiError("The comparison needs the live app.", 0));
      const kept = new Set(leadsIn().filter((l) => l.status === "kept").map((l) => l.id));
      return later({ ...clone(data.compare), rows: data.compare.rows.filter((r) => kept.has(r.lead_id)) });
    },
    handoff: (id, body) => {
      const rec = (data.handoffs || {})[body.office];
      if (!rec) return Promise.reject(new ApiError("Hand-off drafts need the live app.", 0));
      const route = (data.compare.offices.find((o) => o.key === body.office) || {}).route;
      const kept = leadsIn().filter((l) => l.status === "kept" && (l.route || "A") === route)
        .map((l) => l.id).sort();
      if (kept.join(",") === [...rec.lead_ids].sort().join(",")) return later(clone(rec.draft), 600);
      const names = rec.lead_ids.map((i) => final.leads.find((l) => l.id === i))
        .map((l) => (l.opportunity ? l.opportunity.title : l.organisation ? l.organisation.name : l.record_id));
      return Promise.reject(new ApiError("This preview holds the draft for these kept leads only: "
        + `${names.join("; ")}. Keep exactly those to see it.`, 0));
    },
    // A student preview (scripts/export_student_replay.py) holds the server's note for its
    // top option on each route, and the office names; other kept sets say so (review W9).
    studentOffices: data.offices || null,
    studentNote: (route) => {
      const rec = (data.notes || {})[route];
      if (!rec) return Promise.reject(new ApiError("The note needs the live app.", 0));
      const kept = leadsIn().filter((l) => l.status === "kept" && l.route === route).map((l) => l.id).sort();
      if (kept.join(",") === [...rec.lead_ids].sort().join(",")) return later(clone(rec.note), 300);
      const names = rec.lead_ids.map((i) => final.leads.find((l) => l.id === i))
        .map((l) => (l && l.record ? l.record.name || l.record.title : "")).filter(Boolean);
      return Promise.reject(new ApiError(`This preview holds the note for these kept options only: ${names.join("; ")}. Keep exactly those to see it.`, 0));
    },
    recordedQuestion: data.scout ? data.scout.question : null,
    scoutStart: data.scout ? (id, body) => {
      const norm = (q) => q.trim().toLowerCase().replace(/[?.!]+$/, "");
      if (norm(body.question) !== norm(data.scout.question)) {
        return Promise.reject(new ApiError(`This preview holds one recorded question: “${data.scout.question}”`, 0));
      }
      return later(clone(data.scout.session), 900);
    } : undefined,
    scoutGet: () => later(clone(data.scout.session)),
    scoutAct: () => Promise.reject(new ApiError("This preview holds one recorded answer. Ask follow-ups in the live app.", 0)),
    briefId: final.brief.id,
  };
}

// The session id sits in this tab's sessionStorage (review W18, U2), so a reload finds the
// brief the server still holds. Another tab does not share it, and closing the tab forgets
// it. Beside it sit flags only (such as "the brief came from the SYNTHETIC sample"): never
// text, a brief or a lead. Storage can be blocked; then nothing resumes, and that is all.
const TAB_KEY = "perch.session";
const TAB_FLAGS = "perch.flags";
function tabStore() {
  try { return typeof sessionStorage === "undefined" ? null : sessionStorage; } catch { return null; }
}
function tabGet(key) {
  try { const s = tabStore(); return s ? s.getItem(key) : null; } catch { return null; }
}
function tabSet(key, value) {
  try {
    const s = tabStore();
    if (!s) return;
    if (value === null) s.removeItem(key); else s.setItem(key, value);
  } catch { /* storage blocked: a reload starts over */ }
}

// A session (S13; every brief since S23): the same shape as liveApi, scoped to one session. The session
// id travels in a header, never in a path or a query.
export function privateApi(base = "") {
  let token = tabGet(TAB_KEY);
  const keep = (t) => { token = t; tabSet(TAB_KEY, t); if (!t) tabSet(TAB_FLAGS, null); };
  const hdr = () => ({ "Content-Type": "application/json", "X-Perch-Private": token || "" });
  // A 401 means the server no longer holds this session (30 minutes idle, or a restart).
  // The token is dropped and `onExpired` runs once, so the app can go home and say so (S27).
  let last = { token: null, etag: null, body: null }; // the last brief answer (P3)
  const lost = (e) => {
    if (e instanceof ApiError && e.status === 401 && token) {
      keep(null);
      if (api.onExpired) api.onExpired(e.message);
    }
    throw e;
  };
  const p = (path, opts = {}) => call(base, path, { ...opts, headers: hdr() }).catch(lost);
  const post = (path, body = {}) => p(path, { method: "POST", body: JSON.stringify(body) });
  const api = {
    mode: "private",
    onExpired: null,
    get open() { return Boolean(token); },
    info: () => call(base, "/private"),
    sample: (name) => call(base, `/private/samples/${encodeURIComponent(name)}`),
    start: async () => { const r = await call(base, "/private/session", { method: "POST" }); keep(r.token); return r; },
    // A flag kept with the session id for this tab, e.g. flag("sample", true); flag("sample") reads it.
    flag: (name, value) => {
      let all = {};
      try { all = JSON.parse(tabGet(TAB_FLAGS) || "{}") || {}; } catch { all = {}; }
      if (value === undefined) return all[name];
      if (!token) return value;
      all[name] = value;
      tabSet(TAB_FLAGS, JSON.stringify(all));
      return value;
    },
    session: () => p("/private/session"),
    addDocument: (body) => post("/private/documents", body),
    cloud: (on, confirm, documentsConfirm) => post("/private/cloud", { on, confirm, documents_confirm: documentsConfirm || null }),
    removeDocument: (kind) => post(`/private/documents/${encodeURIComponent(kind)}/remove`),
    create: (req) => post("/private/brief", req),
    createStudent: (req) => post("/private/student/brief", req),
    studentNote: (route) => p(`/private/student/note?route=${encodeURIComponent(route)}`),
    end: async () => { try { await post("/private/end"); } finally { keep(null); last = { token: null, etag: null, body: null }; } },
    // A poll sends the last ETag; 304 means nothing changed, so the last body is reused
    // (P3). Held in memory only, like the token; the server marks the answer no-store.
    brief: async () => {
      const tok = token;
      let r;
      try {
        r = await fetch(`${base}/private/brief`, { headers: { ...hdr(),
          ...(last.etag && last.token === tok ? { "If-None-Match": last.etag } : {}) } });
      } catch {
        throw new ApiError("Perch's server did not answer. Check that `perch serve` is running.", 0);
      }
      if (r.status === 304 && last.body && last.token === tok) return JSON.parse(last.body);
      const text = await r.text();
      let body = {};
      try { body = JSON.parse(text); } catch { /* not JSON */ }
      if (!r.ok) lost(new ApiError(typeof body.detail === "string" ? body.detail : `The server answered ${r.status}.`, r.status));
      last = { token: tok, etag: r.headers.get("ETag"), body: text };
      return body;
    },
    setLead: (_id, leadId, action) => post(`/private/leads/${encodeURIComponent(leadId)}/${action}`),
    record: (id) => p(`/private/records/${encodeURIComponent(id)}`),
    // Downloads go through fetch with the header (exportFile), never a link.
    exportFile: async (kind, mask) => {
      const r = await fetch(`${base}/private/export.${kind}?mask=${mask ? "true" : "false"}`, { headers: hdr() });
      if (!r.ok) lost(new ApiError(`The server answered ${r.status}.`, r.status));
      return r.blob();
    },
    unmask: (text) => post("/private/unmask", { text }),
    compare: () => p("/private/compare"),
    handoff: (_id, body) => post("/private/handoff", body),
    scoutStart: (_id, body) => post("/private/scout", body),
    scoutGet: (sid) => p(`/private/scout/${encodeURIComponent(sid)}`),
    scoutAct: (sid, action, body) => post(`/private/scout/${encodeURIComponent(sid)}/${action}`, body),
  };
  return api;
}
