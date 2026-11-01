// Student mode (S18): the start form, the profile read from the CV, the two tabs
// (Fellowships, public; Scholarships, sample), a compare table and a code-written
// hand-off. Student mode exists only inside private mode: a student's input is always
// personal. Every verdict, gap, date and amount is written by the server's rule code or
// copied from the record; nothing here is a model's claim.

import { evMark, fill, h, icon, labelCells } from "./dom.js";
import { copy, mailto } from "./handoff.js";
import * as f from "./format.js";

// The sample tab holds fellowships and prizes as well as scholarships (S22, audit S9).
export const STUDENT_ROUTES = { F: "Fellowships (public)", S: "Scholarships and awards (sample)" };
const SAMPLE = "Sample data";
const SAMPLE_NOTE = "These are invented records from a test corpus. They show how student mode works with a real scholarship feed; they are not real scholarships. Do not apply to them.";
const VERDICTS = { eligible: ["eligible", "✓", "Eligible"], "may be eligible": ["may", "?", "May be eligible"],
  "not eligible": ["not", "✕", "Not eligible"] };

// A verdict chip: a mark and a word, so colour is never the only signal (S24).
export function verdictChip(v) {
  const [cls, mark, word] = VERDICTS[v] || ["", "", v];
  return h("span", { class: `verdict ${cls}` }, h("span", { class: "mk", "aria-hidden": "true", text: mark }), h("span", { text: word }));
}
const HINTS = {
  cv: "Read by rule only: level, year, major, GPA, enrollment, expected graduation and referees. It is never sent to a model.",
  interests: "A few sentences on what you want to study or work on. This steers the search.",
  achievements: "Up to five, one per line or numbered. Explanations may cite them.",
};
const D = { drafts: {}, files: {}, busy: false, error: null, errorAt: null, sample: false, missing: false, replacing: new Set() };
const NOT_STATED = "Not stated in the record";
const SHUT = new Set(); // cards whose "More on why it may fit" was closed; it starts open (S27, Dakshitha)

// The brief on screen was built from the SYNTHETIC sample (for its banner).
export function usedSample() { return Boolean(D.lastSample); }
// Forget what this module held for a session that has ended (S27).
export function resetStudent() {
  Object.assign(D, { drafts: {}, files: {}, busy: false, error: null, errorAt: null, sample: false, lastSample: false, missing: false, replacing: new Set() });
  SORT.by = "order";
  Object.assign(NOTE, { office: null, edits: {}, subjects: {}, got: {}, keptSig: "" });
}

// The kept count on a student brief, public and sample apart (U10, standing rule 11):
// "2 fellowships, 1 sample".
export function keptWords(kept) {
  const pub = kept.filter((l) => !l.sample).length, smp = kept.length - pub;
  return [pub ? f.plural(pub, "fellowship") : null, smp ? f.plural(smp, "sample") : null].filter(Boolean).join(", ");
}

export function isStudent(brief) {
  return Boolean(brief && brief.brief && brief.brief.options && brief.brief.options.student);
}

// ----- start: CV, interests, achievements -----

export async function renderStudentStart(root, { api, mode, go, announce, info, onDocs }) {
  document.title = "Tell Perch about you — Perch";
  const draw = () => renderStudentStart(root, { api, mode, go, announce, info, onDocs });
  if (!mode.state.available) {
    fill(root, h("div", { class: "screen" }, h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
      h("h1", { class: "page", text: "Student mode" }),
      h("p", { class: "notice", text: `Student mode is not available on this server. ${mode.state.reason}` })));
    return;
  }
  if (!api.open) await mode.enable(); // a CV is personal: the session opens before any text is typed in
  for (const [k, v] of Object.entries(mode.state.drafts)) if (v && !D.drafts[k]) { D.drafts[k] = v; delete mode.state.drafts[k]; }
  const sess = await api.session();
  const docs = sess.documents;
  if (onDocs) onDocs(docs.length); // the chip follows what the session holds (Q7)
  const hasBrief = Boolean(sess.brief_id); // the session's brief, kept when going back here
  const have = new Set(docs.map((d) => d.kind));
  const kinds = info.student_kinds || { cv: "Your CV or résumé", interests: "Your interests", achievements: "Your achievements" };
  const text = (k) => (D.drafts[k] || "").trim();
  // Checked when Build is pressed, not when the form is drawn: typing does not redraw.
  const ready = () => (text("cv") || D.files.cv || have.has("cv"))
    && (text("interests") || text("achievements") || have.has("interests") || have.has("achievements"));
  const set = (k) => (e) => { D.drafts[k] = e.target.value; if (D.sample) { D.sample = false; drawSample(); } };
  const noCv = () => !(text("cv") || D.files.cv || have.has("cv"));
  const noSide = () => !(text("interests") || text("achievements") || have.has("interests") || have.has("achievements"));
  const missingText = () => noCv() && noSide() ? "Add your CV and either your interests or your achievements."
    : noCv() ? "Add your CV." : "Add your interests or your achievements.";
  const invalid = (kind) => D.missing && (kind === "cv" ? noCv() : noSide());

  async function build() {
    D.busy = true; D.error = null; draw();
    try {
      for (const kind of Object.keys(kinds)) {
        const body = D.files[kind] ? { kind, filename: D.files[kind].name, data: D.files[kind].data }
          : text(kind) ? { kind, text: text(kind) } : null;
        if (!body) continue;
        if (have.has(kind)) await api.removeDocument(kind);
        await mode.send(body);
      }
      D.drafts = {}; D.files = {}; D.replacing = new Set();
      if (onDocs) onDocs((await api.session()).documents.length);
      D.lastSample = D.sample;
      await api.createStudent({});
      api.flag("studentSample", D.lastSample); // the Sample data banner survives a reload (W18)
      D.busy = false;
      go("#/brief/private/routes");
    } catch (e) {
      // The error sits by the button that was pressed, which takes focus (R4, as U4).
      D.error = e.message; D.errorAt = "go"; D.busy = false; await draw();
      const b = root.querySelector('[data-key="st-build"]'); if (b) b.focus();
    }
  }
  async function fillSample() {
    try {
      const x = await api.sample("student");
      D.drafts = { cv: x.cv, interests: x.interests, achievements: x.achievements };
      D.files = {}; D.sample = true;
      draw(); announce("Filled with a SYNTHETIC sample.");
    } catch (e) { D.error = `The sample could not be loaded: ${e.message}`; D.errorAt = null; draw(); }
  }
  async function pick(kind, file) {
    if (!file) return;
    if (file.size > info.max_bytes) { D.error = `${file.name} is larger than ${info.max_bytes / 1e6} MB: choose a smaller file.`; D.errorAt = "go"; draw(); return; }
    if (D.errorAt === "go") D.error = null;
    const data = await new Promise((ok, bad) => {
      const r = new FileReader();
      r.onload = () => ok(String(r.result).split(",", 2)[1] || "");
      r.onerror = () => bad(new Error("The file could not be read."));
      r.readAsDataURL(file);
    });
    D.files[kind] = { name: file.name, data };
    draw();
  }
  const drawSample = () => { const b = document.getElementById("st-sample"); if (b) fill(b, sampleLine()); };
  const sampleLine = () => (D.sample ? h("p", { class: "sample-status", role: "status" }, h("span", { class: "sample-badge", text: SAMPLE }),
    h("span", { text: "An invented student, labelled SYNTHETIC. Edit it or clear it before you run your own." })) : null);
  const box = (kind, label, note, rows, need) => {
    const d = docs.find((x) => x.kind === kind);
    const file = D.files[kind];
    const held = Boolean(d && !text(kind) && !file && !D.replacing.has(kind));
    return h("section", { class: "box" },
      h("div", { class: "box-head" }, h("label", { class: "big", for: `st-${kind}`, text: label }),
        need ? h("span", { class: "local", text: "Needed" }) : null),
      h("p", { class: "note", id: `st-${kind}-note`, text: note }),
      held ? h("p", { class: "added" }, icon("lock"),
        h("span", { text: `Added, ${d.chars.toLocaleString("en-US")} characters, in this session's memory` }),
        // The paste box stays hidden while a document is held; Replace opens it (U21).
        h("button", { class: "btn quiet", type: "button", "data-key": `st-replace-${kind}`, onclick: () => {
          D.replacing.add(kind); draw(); const t = document.getElementById(`st-${kind}`); if (t) t.focus();
        } }, h("span", { text: "Replace" })),
        h("button", { class: "btn quiet", type: "button", onclick: async () => { await api.removeDocument(kind); D.replacing.delete(kind); draw(); } }, h("span", { text: "Remove" }))) : null,
      held ? null : file ? h("p", { class: "added" }, icon("paper"), h("span", { text: `${file.name}, read on this server when you start` }),
        h("button", { class: "btn quiet", type: "button", onclick: () => { delete D.files[kind]; draw(); } }, h("span", { text: "Remove" })))
        : h("textarea", { id: `st-${kind}`, rows, placeholder: kind === "achievements" ? "One per line" : kind === "interests" ? "For example, the field you want to work in" : "Paste text here",
          "aria-describedby": invalid(kind) ? `st-${kind}-note st-missing` : `st-${kind}-note`,
          "aria-invalid": invalid(kind) ? "true" : null, value: D.drafts[kind] || "", oninput: set(kind) }),
      kind === "cv" && !file && !held ? h("div", { class: "file-row" },
        h("label", { class: "btn" }, h("span", { text: "Or upload a file" }),
          h("input", { type: "file", class: "sr-only", accept: (info.formats || []).join(","), onchange: (e) => pick(kind, e.target.files[0]) })),
        h("span", { class: "hint", text: "Text, Markdown, Word or PDF" })) : null);
  };
  fill(root, h("div", { class: "screen student-start" },
    h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
    h("div", {}, h("h1", { class: "page", text: "Tell Perch about you." }),
      h("p", { class: "page-sub", text: "Code reads your CV by rule on this server; no model reads it. It is held in memory for this session and never saved." })),
    hasBrief ? h("p", {}, h("a", { class: "btn", href: "#/brief/private/routes" }, h("span", { text: "Back to your options" }))) : null,
    h("div", { class: "sample-row" },
      h("span", { text: "Not sure what to paste? See a sample laid out the way that matches best: clear headings for education, honors, research, activities and references." }),
      h("button", { class: "btn outline", type: "button", "data-key": "st-fill", onclick: fillSample }, h("span", { text: "Fill with a sample" })),
      h("button", { class: "btn ghost", type: "button", "data-key": "st-clear", onclick: () => { D.drafts = {}; D.files = {}; D.sample = false; draw(); announce("Cleared."); } },
        h("span", { text: "Clear" }))),
    h("div", { id: "st-sample" }, sampleLine()),
    D.error && D.errorAt !== "go" ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: D.error })) : null,
    h("div", { class: "st-cols" },
      h("div", { class: "st-cv" }, box("cv", kinds.cv, "Level, year, major, GPA, enrollment, graduation date and referees are read from it.", 12, true)),
      h("div", { class: "st-side" },
        box("interests", "What you are interested in", "A few sentences. This steers the search.", 4),
        box("achievements", kinds.achievements || "Your achievements", "Up to five, one per line. Explanations may cite them.", 4))),
    h("div", { class: "go-row" },
      h("button", { class: "btn primary big", type: "button", "data-key": "st-build", disabled: D.busy, onclick: () => {
        // The error sits by the button that was pressed, and marks the boxes it names (U4).
        if (!ready()) {
          D.missing = true; draw();
          const b = root.querySelector('[data-key="st-build"]'); if (b) b.focus();
          return;
        }
        D.missing = false;
        build();
      } }, h("span", { text: D.busy ? "Starting" : "Find fellowships and scholarships" })),
      D.missing ? h("p", { class: "notice error go-error", id: "st-missing", role: "alert" }, icon("warn"),
        h("span", { text: missingText() }))
        : D.error && D.errorAt === "go" ? h("p", { class: "notice error go-error", id: "st-error", role: "alert" }, icon("warn"), h("span", { text: D.error }))
          : h("span", { class: "hint", text: "Needs your CV and either your interests or your achievements." }))));
}

// ----- profile -----

export function studentProfile(d, { openEvidence }) {
  const rows = d.student || [];
  const mine = Object.entries(d.papers || {}).filter(([id, w]) => w.private);
  const interests = mine.filter(([id]) => /interests/.test(id));
  const achievements = mine.filter(([id]) => /achievement-/.test(id)); // one row per achievement
  // Your own words, from this session's memory; exports still withhold or mask them.
  const ref = ([id, w]) => h("li", { class: "fade-in" }, h("button", { class: "paper", type: "button", onclick: (e) => openEvidence(id, e.currentTarget) },
    h("span", { class: "paper-title", text: w.title }),
    w.text ? h("span", { class: "paper-meta", text: w.text.replace(/^#.*$/gm, "").replace(/\s+/g, " ").trim().slice(0, 220) }) : null));
  return [h("div", { class: "prof-cols" },
    h("div", { class: "left" }, h("section", { class: "pblock" },
      h("h2", { class: "section-title", text: "What the rules read from your CV" }),
      rows.length ? h("dl", { class: "fields" }, rows.map(([k, v]) => h("div", { class: "field" }, h("dt", { text: k }), h("dd", { text: v }))))
        : h("div", { class: "skeleton" }, h("span", { style: "width:80%" }), h("span", { style: "width:60%" })),
      h("p", { class: "hint", text: "Read by code, not by a model. If something is wrong, fix your CV and run it again." }))),
    h("div", { class: "right" }, h("section", { class: "pblock" },
      h("h2", { class: "section-title", text: "What steers the search" }),
      interests.length ? h("ul", { class: "papers" }, interests.map(ref)) : h("p", { class: "hint", text: "No interests note in this session." }),
      h("h3", { class: "mini", text: "Your achievements" }),
      achievements.length ? h("ul", { class: "papers" }, achievements.map(ref)) : h("p", { class: "hint", text: "None added." }),
      h("p", { class: "hint", text: "Explanations may cite these. They stay in this session’s memory." }))),
    h("p", { class: "notice", style: "flex: 1 1 100%" }, icon("lock"), h("span", { text: "Perch never asks about residency, citizenship or other personal criteria. When a listing has one, it is quoted on the card for you to judge." })))];
}

// ----- routes -----

// Score (Match, highest first) or Closing date, as on the researcher side (S27).
const SORT = { by: "order" };
const deadlineOf = (l) => { const r = l.record || {}; return (r.kind === "scholarship" ? r.deadline : r.close_date) || "9999"; };

function sortLeads(leads) {
  const out = [...leads];
  if (SORT.by === "closing") return out.sort((a, b) => deadlineOf(a).localeCompare(deadlineOf(b)) || a.rank - b.rank);
  return out.sort((a, b) => (b.match_score ?? -1) - (a.match_score ?? -1) || a.rank - b.rank);
}

function sortSwitch(redraw) {
  return h("div", { class: "sort-group" }, h("span", { class: "sort-label", "aria-hidden": "true", text: "Sort" }),
    h("div", { class: "route-switch sort-switch", role: "group", "aria-label": "Sort options by" },
      [["order", "Score"], ["closing", "Closing date"]].map(([k, label]) => h("button", { class: "route-btn",
        "data-key": `sort-${k}`, "aria-pressed": String(SORT.by === k),
        onclick: () => { SORT.by = k; redraw(); const b = document.querySelector(`#panel [data-key="sort-${k}"]`); if (b) b.focus(); } }, label))));
}

let CLOUD = null; // the Cloud provider's name when the brief on screen ran on Cloud (Q33)

export function studentRoutes(panel, ctx) {
  const { brief, route, setRoute, openEvidence, setLead } = ctx;
  CLOUD = ctx.cloud || null;
  const leads = brief.leads.filter((l) => l.route === route);
  const done = (name) => {
    const s = brief.brief.stages.find((x) => x.name === name);
    return s && ["done", "skipped"].includes(s.status);
  };
  const ready = done(route === "F" ? "fellowships" : "scholarships");
  const n = (r) => brief.leads.filter((l) => l.route === r && l.verdict !== "not eligible" && l.status !== "dismissed").length;
  const sw = h("div", { class: "route-switch", role: "group", "aria-label": "Route" },
    ["F", "S"].map((r) => h("button", { class: "route-btn", "data-key": `route-${r}`, "aria-pressed": String(route === r),
      "aria-label": `${STUDENT_ROUTES[r]}${r === "S" ? ", sample data" : ""}${done(r === "F" ? "fellowships" : "scholarships") ? `, ${n(r)}` : ""}`,
      onclick: () => setRoute(r) },
    // Shorter visible names keep the sort switch on this row at laptop width; the aria-label
    // keeps the full name, and the Sample data tag marks the sample route (S27).
    h("span", { class: "lbl-long", "aria-hidden": "true", text: r === "F" ? "Fellowships" : "Scholarships and awards" }), h("span", { class: "lbl-short", "aria-hidden": "true", text: r === "F" ? "Fellowships" : "Samples" }),
    r === "S" ? h("span", { class: "tag sample lbl-long", text: SAMPLE }) : null,
    done(r === "F" ? "fellowships" : "scholarships") ? h("span", { class: "route-n", text: String(n(r)) }) : null)));
  if (!ready) {
    fill(panel, sw, h("p", { class: "hint", text: "Leads appear here when the search finishes." }));
    return;
  }
  const ok = sortLeads(leads.filter((l) => l.verdict !== "not eligible" && l.status !== "dismissed"));
  const out = leads.filter((l) => l.verdict === "not eligible");
  // A line most cards repeat word for word is said once above the list instead (U20).
  const counts = new Map();
  for (const l of ok) for (const x of new Set(cardLines(l))) counts.set(x, (counts.get(x) || 0) + 1);
  const common = ok.length >= 3 ? [...counts].filter(([, n]) => n >= 3 && n > ok.length / 2).map(([x]) => x) : [];
  const gone = leads.filter((l) => l.verdict !== "not eligible" && l.status === "dismissed");
  fill(panel, h("div", { class: "route-row" }, sw, sortSwitch(() => studentRoutes(panel, ctx))),
    route === "S" ? h("p", { class: "notice warn sample-note" }, h("span", { class: "tag sample", text: SAMPLE }), h("span", { text: ` ${SAMPLE_NOTE}` })) : null,
    h("h2", { class: "section-title", id: "routes-title",
      text: route === "S" ? `${f.plural(ok.length, "sample option")} (invented, for demonstration)`
        : `${f.plural(ok.length, "option")} you may apply for` }),
    h("p", { class: "hint", text: route === "F"
      ? "Public listings: Temple's Scholar Development and Fellowships Advising list and NIH fellowships. Their own pages set the full rules, so the best verdict here is “may be eligible”."
      : "Checked against your CV by rule. “May be eligible” means the record asks for something your CV does not show." }),
    common.length ? h("div", { class: "common-lines" }, h("p", { class: "mini", text: "Unless a card says otherwise" }),
      h("ul", {}, common.map((x) => h("li", { text: x === NO_FACTS ? "The listing states no deadline or amount." : x })))) : null,
    h("ol", { class: "leads", "aria-labelledby": "routes-title" }, ok.map((l) => card(l, ctx, common))),
    gone.length ? h("details", { class: "dismissed" }, h("summary", { text: `Dismissed (${gone.length})` }),
      h("ol", { class: "leads" }, gone.map((l) => card(l, ctx)))) : null,
    out.length ? h("details", { class: "dismissed" }, h("summary", { text: `Not eligible by rule (${out.length})` }),
      h("ol", { class: "leads" }, out.map((l) => card(l, ctx)))) : null);
}

// The Match pill: how closely the listing's text matches the papers, 0 to 100 (S27).
export function matchPill(score, band, what = "the papers") {
  return h("span", { class: `fit ${band.key}`, title: `How closely the listing’s text matches ${what}` },
    h("span", { class: "fit-k", text: "Match" }),
    h("span", { text: band.word }), h("b", { text: String(score) }),
    h("span", { class: "sr-only", text: ` out of 100: how closely the listing’s text matches ${what}, not the odds of funding` }));
}

const NO_FACTS = "no-facts";
// The deadline as the record gives it: "Expires 7 May 2028" for a parent announcement,
// the record's words where standard dates apply (T17).
function dueText(r, d) {
  if (!d) return NOT_STATED;
  if (r.kind !== "scholarship" && f.standardDates(r)) return r.close_date_note;
  return r.kind !== "scholarship" && f.expiresOnly(r) ? `Expires ${f.formatDate(d)}` : f.formatDate(d);
}
// The lines of a card that can repeat word for word: no deadline or amount, and the rule lines.
function cardLines(l) {
  const r = l.record || {};
  const sch = r.kind === "scholarship";
  const none = !(sch ? r.deadline : r.close_date) && (!sch || amountText(r) === NOT_STATED);
  return [none ? NO_FACTS : null, ...(l.verdict_lines.length === 1 ? l.verdict_lines : [])].filter(Boolean);
}

function card(l, { openEvidence, setLead, papers }, common = []) {
  const r = l.record || {};
  const sch = r.kind === "scholarship";
  const name = sch ? r.name : r.title;
  const deadline = sch ? r.deadline : r.close_date;
  const amount = sch ? amountText(r) : null;
  const parsed = f.parseExplanation(l.explanation, l.cited_ids);
  // Keep and Dismiss sit in the card head, next to the Match pill (review W2); the title
  // opens the record (W4).
  const actions = h("div", { class: "actions" },
    l.status === "dismissed"
      ? h("button", { class: "btn", "data-key": `restore-${l.id}`, onclick: () => setLead(l.id, "restore") }, icon("restore"), h("span", { text: "Restore" }))
      : [h("button", { class: `btn keep${l.status === "kept" ? " on" : ""}`, "data-key": `keep-${l.id}`, "aria-pressed": String(l.status === "kept"),
        onclick: () => setLead(l.id, l.status === "kept" ? "restore" : "keep") }, icon("keep"), h("span", { text: l.status === "kept" ? "Kept" : "Keep" })),
      l.verdict !== "not eligible" ? h("button", { class: "btn", "data-key": `dismiss-${l.id}`, onclick: () => setLead(l.id, "dismiss") }, icon("dismiss"), h("span", { text: "Dismiss" })) : null],
  );
  return h("li", { class: `card lead${l.sample ? " is-sample" : ""}${l.status === "kept" ? " kept" : ""}`, "data-id": l.id },
    h("div", { class: "lead-head" }, h("span", { class: "tags" },
      l.sample ? h("span", { class: "tag sample", text: SAMPLE }) : null,
      verdictChip(l.verdict),
      l.match_score != null ? matchPill(l.match_score, f.fitBand(l.match_score), "your interests and CV") : null,
      sch && r.award_type ? h("span", { class: "tag", text: r.award_type }) : null,
      !sch && r.activity_code ? h("span", { class: "tag", text: `NIH ${r.activity_code}` }) : null,
      !sch && r.status === "forecasted" ? h("span", { class: "tag ember", text: "Forecast: not open yet" }) : null),
    h("div", { class: "head-end" }, actions)),
    h("h3", { class: "lead-title" }, h("button", { class: "title-btn", onclick: (e) => openEvidence(l.record_id, e.currentTarget) },
      h("span", { text: name || l.record_id }), evMark())),
    sch && r.sponsor ? h("p", { class: "opp-num", text: r.sponsor }) : null,
    // A listing that states neither field gets one line, not two empty boxes (S22, audit S6).
    !deadline && (!sch || amount === NOT_STATED)
      ? (common.includes(NO_FACTS) ? null : h("p", { class: "hint no-size", text: sch ? "Deadline and amount: not stated in the record." : "Deadline: not stated in the record." }))
      : h("dl", { class: "facts" },
        // G17: an expiry sits under its own label, as on the researcher card (F20)
        h("div", { class: "fact" }, h("dt", { text: !sch && f.expiresOnly(r) && !f.standardDates(r) ? "Announcement" : "Deadline" }), h("dd", { text: dueText(r, deadline) })),
        sch ? h("div", { class: "fact" }, h("dt", { text: "Amount" }), h("dd", { text: amount })) : null),
    l.verdict_lines.length && !(l.verdict_lines.length === 1 && common.includes(l.verdict_lines[0])) ? h("div", { class: "reason" }, h("b", { text: l.verdict === "not eligible" ? "Why not: " : "To check: " }), // T23: not a second "Why"
      l.verdict_lines.length === 1 ? h("span", { text: l.verdict_lines[0] })
        : h("ul", { class: "notes" }, l.verdict_lines.map((x) => h("li", { text: x })))) : null,
    l.gaps.length ? h("div", { class: "reason" }, h("b", { text: "Still needed: " }), h("span", { text: l.gaps.map(f.lowerFirst).join("; ") })) : null, // R17
    l.flagged ? h("p", { class: "notice warn" }, icon("warn"), h("span", { text: "The explanation was withheld because it failed the citation checks twice." }))
      : parsed ? fitReason(l) : null);
}

// The reason it may fit leads, in plain view (S27, Dakshitha: say the reason right
// there). What it rests on, the listing's own sentence and the student's achievements in
// their own words, sits under it. The achievements are the student's own text, so there
// are no chips naming them; the records stay cited behind the text.
function fitReason(l) {
  // F2: the card's own record, cited where a noun stands, reads "this opportunity".
  const own = new Set([l.record_id, String(l.record_id || "").split(":").pop()]);
  const [about, work] = f.ownInPlace(String(l.explanation || ""), own).split(/\s*Cited work:\s*/);
  const items = (work || "").split(/;\s*/).map((x) => plainExplanation(x.replace(/^\s*(?:private:)?(?:achievement-[a-e]|interests)\s*/, ""))
    .replace(/\.$/, "")).filter(Boolean);
  const reason = l.inference ? plainExplanation(you(f.ownInPlace(l.inference, own))) : null;
  // In the weak band the model's sentence may say it does not fit, so the label does not
  // promise a fit: "How it relates", as on the researcher's weak cards (Q17, T15: one
  // rule on both paths, the band's).
  const weak = (f.fitBand(l.match_score) || {}).key === "weak";
  const label = weak ? "How it relates" : "Why it may fit";
  return h("div", { class: "fit-reason" },
    reason ? h("p", { class: "fit-why" }, h("b", { text: `${label}: ` }), h("span", { text: reason }),
      h("span", { class: `tag model${CLOUD ? " cloud" : ""}`, text: CLOUD ? `Cloud: ${CLOUD}` : "Model text" })) : null,
    h("details", { class: "why explain", open: !SHUT.has(l.id),
      ontoggle: (e) => { if (e.target.open) SHUT.delete(l.id); else SHUT.add(l.id); } },
    h("summary", { "data-key": `why-${l.id}` }, h("span", { text: reason ? `More on ${label.toLowerCase()}` : label })),
    about ? h("p", { text: plainExplanation(about) }) : null,
    items.length ? h("div", {}, h("p", { class: "mini", text: "From your achievements and interests" }),
      h("ul", { class: "notes" }, items.map((x) => h("li", { text: x })))) : null,
    h("p", { class: "hint", text: "A model wrote these sentences. Each one was checked against the listing or your own text." })));
}

// The model is told to say "you"; when it says "the student" anyway, the card says "you".
function you(text) {
  return text.replace(/\b([Tt])he student's\b/g, (_, t) => (t === "T" ? "Your" : "your"))
    .replace(/\b([Tt])he student\b/g, (_, t) => (t === "T" ? "You" : "you"));
}

// Citation brackets go; a session record's id reads as "your achievement A".
function plainExplanation(text) {
  return String(text || "").replace(/\s*\[[^\]]*\]/g, "")
    .replace(/\b(?:private:)?achievement-([a-e])\b/g, (_, c) => `your achievement ${c.toUpperCase()}`)
    .replace(/\b(?:private:)?interests\b/g, "your interests note")
    .replace(/\bCited work:/, "Your work:").trim()
    .replace(/^./, (c) => c.toUpperCase());
}

function amountText(r) {
  if (r.amount_min != null && r.amount_max != null && r.amount_min !== r.amount_max) return `${f.money(r.amount_min)} to ${f.money(r.amount_max)}`;
  if (r.amount_max != null) return f.money(r.amount_max);
  return NOT_STATED;
}

// ----- compare and hand-off (code-written; nothing is sent) -----

// The office picked, and the note as edited, per office, for the kept set it was written for.
// The office picked; per office, the note the server wrote and the note as edited, for the
// kept set they were written for.
const NOTE = { office: null, edits: {}, subjects: {}, got: {}, keptSig: "" };

export function studentCompare(panel, ctx) {
  const { brief, goRoutes, announce, api } = ctx;
  const offices = ctx.offices || {};
  const kept = brief.leads.filter((l) => l.status === "kept");
  if (!kept.length) {
    fill(panel, h("div", { class: "empty" }, h("div", {}, h("p", { class: "lede", text: "Nothing kept yet." }),
      h("p", { class: "hint", text: "Keep fellowships or scholarships under Your options to compare them here." }),
      h("button", { class: "btn", onclick: goRoutes }, h("span", { text: "Go to Your options" })))));
    return;
  }
  const draw = () => studentCompare(panel, ctx);
  const byOffice = { F: kept.filter((l) => l.route === "F"), S: kept.filter((l) => l.route === "S") };
  const routes = ["F", "S"].filter((r) => byOffice[r].length);
  if (!routes.includes(NOTE.office)) NOTE.office = routes[0];
  const keptSig = kept.map((l) => l.id).sort().join(",");
  if (NOTE.keptSig !== keptSig) { NOTE.edits = {}; NOTE.subjects = {}; NOTE.got = {}; NOTE.keptSig = keptSig; }
  // The note is written by the server, by the same code as Scout's draft_note (review W9).
  const route = NOTE.office;
  if (!NOTE.got[route]) {
    NOTE.got[route] = { wait: true };
    const ask = api && api.studentNote ? api.studentNote(route) : Promise.reject(new Error("The note needs the live app."));
    ask.then((n) => { NOTE.got[route] = { note: n }; }, (e) => { NOTE.got[route] = { error: e.message }; })
      .then(() => { if (NOTE.keptSig === keptSig && panel.querySelector(".st-note-wait")) draw(); });
  }
  const got = NOTE.got[route];
  const officeName = (r) => (offices[r] || {}).name || "The Temple office for this route";
  const row = (l) => {
    const r = l.record || {};
    const sch = r.kind === "scholarship";
    const d = sch ? r.deadline : r.close_date;
    return h("tr", {},
      h("th", { scope: "row" }, h("span", { class: "row-title", text: sch ? r.name : r.title }),
        l.sample ? h("span", { class: "tag sample", text: SAMPLE }) : null),
      h("td", {}, verdictChip(l.verdict)),
      // G17: under the Deadline column an expiry says it is none
      h("td", { text: !sch && f.expiresOnly(r) && !f.standardDates(r) ? `None stated; the announcement expires ${f.formatDate(d)}` : dueText(r, d) }),
      h("td", { text: sch ? amountText(r) : "See the record" }),
      h("td", { text: l.gaps.map((x, i) => (i ? f.lowerFirst(x) : x)).join("; ") || "Nothing listed" }), // R17, T24
      h("td", { text: officeName(l.route) }));
  };
  fill(panel,
    kept.some((l) => l.sample) ? h("p", { class: "notice warn sample-note", role: "note" }, h("span", { class: "tag sample", text: SAMPLE }),
      h("span", { text: " Your shortlist includes invented sample scholarships. They are not real." })) : null,
    // The note comes before the table, so drafting it needs no scroll (review W2).
    h("section", { class: "handoff" },
      h("h2", { class: "section-title", text: "Draft a note to a Temple office" }),
      h("fieldset", { class: "office-pick" }, h("legend", { text: "Office" }),
        routes.map((r) => h("label", { class: "office-opt" },
          h("input", { type: "radio", name: "st-office", checked: NOTE.office === r, onchange: () => { NOTE.office = r; draw(); } }),
          h("span", {}, h("b", { text: officeName(r) }), h("br"),
            h("span", { class: "hint", text: r === "F" ? "For the kept fellowships" : "For the kept sample scholarships" }))))),
      // Code writes the note at once, so it shows without a Draft press (review W8).
      h("p", { class: "hint", text: "Code writes this note; no model. Perch never sends it." }),
      got.note ? note(route, got.note, announce)
        : got.error ? h("p", { class: "notice error" }, icon("warn"), h("span", { text: `The note could not be written: ${got.error}` }))
          : h("p", { class: "hint st-note-wait", role: "status", text: "Writing the note…" })),
    // Public fellowships and SYNTHETIC samples never share a table (U10, standing rule 11).
    ...routes.map((r) => h("div", { class: "compare-group" }, // the table's region carries the heading as its name
      h("h2", { class: "section-title", id: `cmp-${r}` }, h("span", { text: STUDENT_ROUTES[r] }),
        r === "S" ? h("span", { class: "tag sample", text: SAMPLE }) : null),
      h("div", { class: "table-wrap compare-wrap", role: "region", "aria-labelledby": `cmp-${r}`, tabindex: "0" }, labelCells(h("table", { class: "compare stack" },
        h("thead", {}, h("tr", {}, [r === "S" ? "Sample option" : "Fellowship", "Rule check", "Deadline", "Amount", "Still needed", "Temple office"].map((x) => h("th", { scope: "col", text: x })))),
        h("tbody", {}, byOffice[r].map(row))))))),
    h("p", { class: "hint", text: "Each cell is copied from its record or checked against your CV by rule. “Not stated in the record” means the listing leaves it blank." }));
}

// The note as the server wrote it (GET /private/student/note), editable here.
function note(route, n, announce) {
  const subjectNow = () => NOTE.subjects[route] ?? n.subject;
  // The subject is editable, as in the researcher's note; the mail link and the copy use the edit.
  const subject = h("input", { id: "st-subject", "data-key": "st-subject", class: "input", value: subjectNow(),
    oninput: (e) => { NOTE.subjects[route] = e.target.value; } });
  const box = h("textarea", { id: "st-body", class: "input draft-body", rows: 10,
    oninput: (e) => { NOTE.edits[route] = e.target.value; } });
  box.value = NOTE.edits[route] ?? n.body;
  return h("div", { class: "draft fade-in" },
    n.sample ? h("p", { class: "notice warn sample-note" }, h("span", { class: "tag sample", text: SAMPLE }),
      h("span", { text: " This note names invented sample scholarships." })) : null,
    h("p", { class: "office-link", text: "To: left blank for you." }),
    h("label", { class: "field-label", for: "st-subject", text: "Subject" }), subject,
    h("label", { class: "field-label", for: "st-body", text: "Note" }), box,
    h("p", { class: "hint" }, h("a", { href: f.safeUrl(n.office_page), target: "_blank", rel: "noopener", text: `${n.office} (public page)` })),
    h("div", { class: "actions" },
      h("button", { class: "btn", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(`Subject: ${subjectNow()}\n\n${box.value}`); announce("The draft is copied."); } catch { box.select(); }
      } }, icon("paper"), h("span", { text: "Copy the draft" })),
      // A note about invented scholarships is a demonstration: there is no mail button.
      // The link is built on the press, from the text as edited (review W8), and the note
      // is copied too, in case the mail app shortens a long one.
      n.sample ? null : h("a", { class: "btn", href: "#", "data-key": "st-mail", onclick: async (e) => {
        e.currentTarget.href = mailto({ subject: subjectNow(), body: box.value });
        await copy(`Subject: ${subjectNow()}\n\n${box.value}`, announce);
      } }, icon("mail"), h("span", { text: "Open in my mail app" }))),
    n.sample ? null : h("p", { class: "hint", text: "Open in my mail app also copies the draft. A long draft is too long for a mail link: paste it into the new message." }));
}
