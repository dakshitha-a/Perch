// Two back ends with one shape: the live API (perch serve) and replay, which plays a
// saved brief back from window.PERCH_REPLAY (built by scripts/export_replay.py).

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

// The server's {"detail": {"error": "<code>"}} answers, in plain words. Kept small.
const ERROR_WORDS = {
  auth_required: "Start a guest session to continue.",
  account_required: "Sign in to use this: guests cannot draft hand-offs or use Scout.",
  consent_required: "Accept the consent at sign-up first.",
  rate_limited: "You have reached your limit for now. Try again later.",
  quota_exceeded: "You have reached your limit for now. Try again later.",
};

function detailText(body, status) {
  const d = body && body.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && !Array.isArray(d)) {
    return ERROR_WORDS[d.error] || `The server answered ${status}.`;
  }
  return `The server answered ${status}.`;
}

function failed(body, status) {
  const err = new ApiError(detailText(body, status), status);
  const d = body && body.detail;
  err.code = d && typeof d === "object" ? d.error || null : null;
  return err;
}

async function call(base, path, opts = {}) {
  let r;
  try {
    r = await fetch(base + path, { headers: { "Content-Type": "application/json" }, ...opts });
  } catch {
    throw new ApiError("Perch's server did not answer. Check that `perch serve` is running.", 0);
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw failed(body, r.status);
  return body;
}

// The live API. The session is a cookie the server sets; the CSRF token it hands back is
// kept in memory only and sent on every request that is not a GET. A visitor with no
// session gets a guest session before the first brief, on the side (audience) they asked
// for. `onExpired(message)` runs when the server no longer knows the session.
export function liveApi(base = "") {
  let csrf = null, audience = null, guest = false;
  let epoch = 0; // bumps when the session is lost, so calls that fail together report it once
  let last = { id: null, etag: null, body: null }; // the last brief answer, for 304 (P3)
  const api = { mode: "live", onExpired: null };

  const adopt = (r) => { csrf = r.csrf || null; audience = r.audience || null; return r; };
  const lost = (e, from) => {
    if (e instanceof ApiError && e.status === 401 && from === epoch) {
      epoch += 1;
      csrf = null; audience = null; guest = false; last = { id: null, etag: null, body: null };
      if (api.onExpired) api.onExpired("Your guest session ended, so Perch went back to the start. A guest session lasts an hour. Start again whenever you are ready.");
    }
    throw e;
  };
  // The session for this side: the cookie's own if it has one. Only a new brief
  // (`side` given) starts a guest session when there is none, or when the guest is on
  // the other side. Other calls just pick up the cookie's CSRF token, or answer 401.
  async function ensure(side) {
    if (csrf && (!side || side === audience || !guest)) return;
    if (!csrf) {
      const now = await call(base, "/auth/session");
      if (now.csrf) { adopt(now); guest = Boolean(now.guest); }
      if (!side || (now.csrf && (now.audience === side || !now.guest))) return;
    }
    const made = adopt(await call(base, "/auth/guest", { method: "POST", body: JSON.stringify({ audience: side }) }));
    guest = Boolean(made.guest);
  }
  const hdr = (method) => ({ "Content-Type": "application/json",
    ...(method && method !== "GET" && csrf ? { "X-CSRF-Token": csrf } : {}) });
  const p = async (path, opts = {}) => {
    await ensure(null);
    const from = epoch;
    return call(base, path, { ...opts, headers: hdr(opts.method) }).catch((e) => lost(e, from));
  };
  const post = (path, body) => p(path, { method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const bid = (id) => `/briefs/${encodeURIComponent(id)}`;
  Object.assign(api, {
    resolve: (q) => call(base, `/authors/resolve?q=${encodeURIComponent(q)}`),
    create: async (req, side = "researcher") => {
      await ensure(side);
      last = { id: null, etag: null, body: null };
      const from = epoch;
      return call(base, "/briefs", { method: "POST", headers: hdr("POST"), body: JSON.stringify(req) })
        .catch((e) => lost(e, from));
    },
    // A poll sends the last ETag; 304 means nothing changed, so the last body is reused.
    // Held in memory only; the server marks the answer no-store.
    brief: async (id) => {
      await ensure(null);
      const from = epoch;
      let r;
      try {
        r = await fetch(`${base}${bid(id)}`, { headers: { ...hdr("GET"),
          ...(last.etag && last.id === id ? { "If-None-Match": last.etag } : {}) } });
      } catch {
        throw new ApiError("Perch's server did not answer. Check that `perch serve` is running.", 0);
      }
      if (r.status === 304 && last.body && last.id === id) return JSON.parse(last.body);
      const text = await r.text();
      let body = {};
      try { body = JSON.parse(text); } catch { /* not JSON */ }
      if (!r.ok) lost(failed(body, r.status), from);
      last = { id, etag: r.headers.get("ETag"), body: text };
      return body;
    },
    setLead: (id, leadId, action) => post(`${bid(id)}/leads/${encodeURIComponent(leadId)}/${action}`),
    record: (id) => p(`/records/${encodeURIComponent(id)}`),
    compare: (id) => p(`${bid(id)}/compare`),
    handoff: (id, body) => post(`${bid(id)}/handoff`, body),
    studentNote: (id, route) => p(`${bid(id)}/student/note?route=${encodeURIComponent(route)}`),
    // The export as a Blob (a plain fetch with the cookie); the caller saves or opens it.
    exportFile: async (id, kind, status = null) => {
      await ensure(null);
      const from = epoch;
      let r;
      try {
        r = await fetch(`${base}${bid(id)}/export.${kind}${status ? `?status=${encodeURIComponent(status)}` : ""}`);
      } catch {
        throw new ApiError("Perch's server did not answer. Check that `perch serve` is running.", 0);
      }
      if (!r.ok) lost(failed(await r.json().catch(() => ({})), r.status), from);
      return r.blob();
    },
    scoutStart: (id, body) => post(`${bid(id)}/scout`, body),
    scoutGet: (sid) => p(`/scout/${encodeURIComponent(sid)}`),
    scoutAct: (sid, action, body) => post(`/scout/${encodeURIComponent(sid)}/${action}`, body),
  });
  return api;
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
    studentNote: (_id, route) => {
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
