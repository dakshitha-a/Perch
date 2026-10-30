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
    exportUrl: (id, kind = "json") => `${base}/briefs/${encodeURIComponent(id)}/export.${kind}`,
    keptUrl: (id) => `${base}/briefs/${encodeURIComponent(id)}/export.json?status=kept`,
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
  let startedAt = null, startedWall = 0, scoutMode = "ask";
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
      out.leads = out.leads.map((l, i) => (i < landed ? l : { ...l, fit_score: null,
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
    exportUrl: () => null,
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
    recordedQuestion: data.scout ? data.scout.question : null,
    scoutStart: data.scout ? (id, body) => {
      const norm = (q) => q.trim().toLowerCase().replace(/[?.!]+$/, "");
      if (norm(body.question) !== norm(data.scout.question)) {
        return Promise.reject(new ApiError(`This preview holds one recorded question: “${data.scout.question}”`, 0));
      }
      scoutMode = body.mode;
      return later({ ...clone(data.scout.session), mode: scoutMode }, 900);
    } : undefined,
    scoutGet: () => later({ ...clone(data.scout.session), mode: scoutMode }),
    scoutAct: (sid, action) => {
      if (action !== "mode") return Promise.reject(new ApiError("This preview holds one recorded answer. Ask follow-ups in the live app.", 0));
      scoutMode = scoutMode === "run" ? "ask" : "run";
      return later({ ...clone(data.scout.session), mode: scoutMode });
    },
    // Same shape as the live export with ?status=kept, built from the saved records.
    keptUrl: () => {
      const leads = leadsIn().filter((l) => l.status === "kept");
      const ids = new Set([final.brief.researcher_id]);
      for (const l of leads) { ids.add(l.record_id); l.cited_ids.forEach((c) => ids.add(c)); }
      const records = [...ids].map(find).filter(Boolean);
      const body = { brief: final.brief, leads, records, notice: final.notice };
      return URL.createObjectURL(new Blob([JSON.stringify(body, null, 1)],
        { type: "application/json" }));
    },
    briefId: final.brief.id,
  };
}

// A session (S13; every brief since S23): the same shape as liveApi, scoped to one session. The session
// id travels in a header, lives only in this object, and is never written to storage.
export function privateApi(base = "") {
  let token = null;
  const hdr = () => ({ "Content-Type": "application/json", "X-Perch-Private": token || "" });
  const p = (path, opts = {}) => call(base, path, { ...opts, headers: hdr() });
  const post = (path, body = {}) => p(path, { method: "POST", body: JSON.stringify(body) });
  return {
    mode: "private",
    get open() { return Boolean(token); },
    info: () => call(base, "/private"),
    start: async () => { const r = await call(base, "/private/session", { method: "POST" }); token = r.token; return r; },
    session: () => p("/private/session"),
    addDocument: (body) => post("/private/documents", body),
    cloud: (on, confirm) => post("/private/cloud", { on, confirm }),
    removeDocument: (kind) => post(`/private/documents/${encodeURIComponent(kind)}/remove`),
    create: (req) => post("/private/brief", req),
    createStudent: (req) => post("/private/student/brief", req),
    end: async () => { try { await post("/private/end"); } finally { token = null; } },
    brief: () => p("/private/brief"),
    setLead: (_id, leadId, action) => post(`/private/leads/${encodeURIComponent(leadId)}/${action}`),
    record: (id) => p(`/private/records/${encodeURIComponent(id)}`),
    exportUrl: () => null, // downloads go through fetch with the header (exportFile)
    exportFile: async (kind, mask) => {
      const r = await fetch(`${base}/private/export.${kind}?mask=${mask ? "true" : "false"}`, { headers: hdr() });
      if (!r.ok) throw new ApiError(`The server answered ${r.status}.`, r.status);
      return r.blob();
    },
    unmask: (text) => post("/private/unmask", { text }),
    compare: () => p("/private/compare"),
    handoff: (_id, body) => post("/private/handoff", body),
    scoutStart: (_id, body) => post("/private/scout", body),
    scoutGet: (sid) => p(`/private/scout/${encodeURIComponent(sid)}`),
    scoutAct: (sid, action, body) => post(`/private/scout/${encodeURIComponent(sid)}/${action}`, body),
  };
}
