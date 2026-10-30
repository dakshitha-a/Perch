// Student mode (S18): the start form, the profile read from the CV, the two tabs
// (Fellowships, public; Scholarships, sample), a compare table and a code-written
// hand-off. Student mode exists only inside private mode: a student's input is always
// personal. Every verdict, gap, date and amount is written by the server's rule code or
// copied from the record; nothing here is a model's claim.

import { fill, h, icon, labelCells } from "./dom.js";
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
const OFFICES = {
  F: { name: "Scholar Development and Fellowships Advising", url: "https://undergraduate.temple.edu/fellowships" },
  S: { name: "Student Financial Services", url: "https://sfs.temple.edu/" },
};
const HINTS = {
  cv: "Read by rule only: level, year, major, GPA, enrolment, expected graduation and referees. It is never sent to a model.",
  interests: "A few sentences on what you want to study or work on. This steers the search.",
  achievements: "Up to five, one per line or numbered. Explanations may cite them.",
};
const D = { drafts: {}, files: {}, busy: false, error: null, sample: false };
const NOT_STATED = "Not stated in the record";
const OPEN = new Set(); // cards whose "Why it may fit" is open; kept across redraws

// The brief on screen was built from the SYNTHETIC sample (for its banner).
export function usedSample() { return Boolean(D.lastSample); }

export function isStudent(brief) {
  return Boolean(brief && brief.brief && brief.brief.options && brief.brief.options.student);
}

// ----- start: CV, interests, achievements -----

export async function renderStudentStart(root, { api, mode, go, announce, info }) {
  document.title = "Tell Perch about you — Perch";
  const draw = () => renderStudentStart(root, { api, mode, go, announce, info });
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
  const hasBrief = Boolean(sess.brief_id); // the session's brief, kept when going back here
  const have = new Set(docs.map((d) => d.kind));
  const kinds = info.student_kinds || { cv: "Your CV or résumé", interests: "Your interests", achievements: "Your achievements" };
  const text = (k) => (D.drafts[k] || "").trim();
  // Checked when Build is pressed, not when the form is drawn: typing does not redraw.
  const ready = () => (text("cv") || D.files.cv || have.has("cv"))
    && (text("interests") || text("achievements") || have.has("interests") || have.has("achievements"));
  const set = (k) => (e) => { D.drafts[k] = e.target.value; if (D.sample) { D.sample = false; drawSample(); } };

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
      D.drafts = {}; D.files = {};
      D.lastSample = D.sample;
      await api.createStudent({});
      D.busy = false;
      go("#/brief/private/routes");
    } catch (e) { D.error = e.message; D.busy = false; draw(); }
  }
  async function fillSample() {
    try {
      const x = await api.sample("student");
      D.drafts = { cv: x.cv, interests: x.interests, achievements: x.achievements };
      D.files = {}; D.sample = true;
      draw(); announce("Filled with a SYNTHETIC sample.");
    } catch (e) { D.error = `The sample could not be loaded: ${e.message}`; draw(); }
  }
  async function pick(kind, file) {
    if (!file) return;
    if (file.size > info.max_bytes) { D.error = `That file is larger than ${info.max_bytes / 1e6} MB.`; draw(); return; }
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
    return h("section", { class: "box" },
      h("div", { class: "box-head" }, h("label", { class: "big", for: `st-${kind}`, text: label }),
        need ? h("span", { class: "local", text: "Needed" }) : null),
      h("p", { class: "note", id: `st-${kind}-note`, text: note }),
      d && !text(kind) && !file ? h("p", { class: "added" }, icon("lock"),
        h("span", { text: `Added, ${d.chars.toLocaleString("en-US")} characters, in this session's memory` }),
        h("button", { class: "btn quiet", type: "button", onclick: async () => { await api.removeDocument(kind); draw(); } }, h("span", { text: "Remove" }))) : null,
      file ? h("p", { class: "added" }, icon("paper"), h("span", { text: `${file.name}, read on this server when you start` }),
        h("button", { class: "btn quiet", type: "button", onclick: () => { delete D.files[kind]; draw(); } }, h("span", { text: "Remove" })))
        : h("textarea", { id: `st-${kind}`, rows, placeholder: kind === "achievements" ? "One per line" : kind === "interests" ? "For example, the field you want to work in" : "Paste text here",
          "aria-describedby": `st-${kind}-note`, value: D.drafts[kind] || "", oninput: set(kind) }),
      kind === "cv" && !file ? h("div", { class: "file-row" },
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
      h("span", { text: "Not sure what to paste? See a sample laid out the way that matches best: clear headings for education, honours, research, activities and references." }),
      h("button", { class: "btn outline", type: "button", "data-key": "st-fill", onclick: fillSample }, h("span", { text: "Fill with a sample" })),
      h("button", { class: "btn ghost", type: "button", "data-key": "st-clear", onclick: () => { D.drafts = {}; D.files = {}; D.sample = false; draw(); announce("Cleared."); } },
        h("span", { text: "Clear" }))),
    h("div", { id: "st-sample" }, sampleLine()),
    D.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: D.error })) : null,
    h("div", { class: "st-cols" },
      h("div", { class: "st-cv" }, box("cv", kinds.cv, "Level, year, major, GPA, enrolment, graduation date and referees are read from it.", 12, true)),
      h("div", { class: "st-side" },
        box("interests", "What you are interested in", "A few sentences. This steers the search.", 4),
        box("achievements", kinds.achievements || "Your achievements", "Up to five, one per line. Explanations may cite them.", 4))),
    h("div", { class: "go-row" },
      h("button", { class: "btn primary big", type: "button", "data-key": "st-build", disabled: D.busy, onclick: () => {
        if (!ready()) { D.error = "Add your CV and either your interests or your achievements."; draw(); return; }
        build();
      } }, h("span", { text: D.busy ? "Starting" : "Find fellowships and scholarships" })),
      h("span", { class: "hint", text: "Needs your CV and either your interests or your achievements." }))));
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

export function studentRoutes(panel, ctx) {
  const { brief, route, setRoute, openEvidence, setLead } = ctx;
  const leads = brief.leads.filter((l) => l.route === route);
  const done = (name) => {
    const s = brief.brief.stages.find((x) => x.name === name);
    return s && ["done", "skipped"].includes(s.status);
  };
  const ready = done(route === "F" ? "fellowships" : "scholarships");
  const n = (r) => brief.leads.filter((l) => l.route === r && l.verdict !== "not eligible" && l.status !== "dismissed").length;
  const sw = h("div", { class: "route-switch", role: "group", "aria-label": "Route" },
    ["F", "S"].map((r) => h("button", { class: "route-btn", "data-key": `route-${r}`, "aria-pressed": String(route === r),
      onclick: () => setRoute(r) },
    h("span", { class: "long", text: STUDENT_ROUTES[r] }), h("span", { class: "short", "aria-hidden": "true", text: r === "F" ? "Fellowships" : "Samples" }),
    r === "S" ? h("span", { class: "tag sample long", text: SAMPLE }) : null,
    done(r === "F" ? "fellowships" : "scholarships") ? h("span", { class: "route-n", text: String(n(r)) }) : null)));
  if (!ready) {
    fill(panel, sw, h("p", { class: "hint", text: "Leads appear here when the search finishes." }));
    return;
  }
  const ok = leads.filter((l) => l.verdict !== "not eligible" && l.status !== "dismissed");
  const out = leads.filter((l) => l.verdict === "not eligible");
  const gone = leads.filter((l) => l.verdict !== "not eligible" && l.status === "dismissed");
  fill(panel, sw,
    route === "S" ? h("p", { class: "notice warn sample-note" }, h("span", { class: "tag sample", text: SAMPLE }), h("span", { text: ` ${SAMPLE_NOTE}` })) : null,
    h("h2", { class: "section-title", id: "routes-title",
      text: route === "S" ? `${f.plural(ok.length, "sample option")} (invented, for demonstration)`
        : `${f.plural(ok.length, "option")} you may apply for` }),
    h("p", { class: "hint", text: route === "F"
      ? "Public listings: Temple's Scholar Development and Fellowships Advising list and NIH fellowships. Their own pages set the full rules, so the best verdict here is “may be eligible”."
      : "Checked against your CV by rule. “May be eligible” means the record asks for something your CV does not show." }),
    h("ol", { class: "leads", "aria-labelledby": "routes-title" }, ok.map((l) => card(l, ctx))),
    gone.length ? h("details", { class: "dismissed" }, h("summary", { text: `Dismissed (${gone.length})` }),
      h("ol", { class: "leads" }, gone.map((l) => card(l, ctx)))) : null,
    out.length ? h("details", { class: "dismissed" }, h("summary", { text: `Not eligible by rule (${out.length})` }),
      h("ol", { class: "leads" }, out.map((l) => card(l, ctx)))) : null);
}

function card(l, { openEvidence, setLead, papers }) {
  const r = l.record || {};
  const sch = r.kind === "scholarship";
  const name = sch ? r.name : r.title;
  const deadline = sch ? r.deadline : r.close_date;
  const amount = sch ? amountText(r) : null;
  const parsed = f.parseExplanation(l.explanation, l.cited_ids);
  return h("li", { class: `card lead${l.sample ? " is-sample" : ""}${l.status === "kept" ? " kept" : ""}`, "data-id": l.id },
    h("div", { class: "lead-head" }, h("span", { class: "tags" },
      l.sample ? h("span", { class: "tag sample", text: SAMPLE }) : null,
      verdictChip(l.verdict),
      sch && r.award_type ? h("span", { class: "tag", text: r.award_type }) : null,
      !sch && r.activity_code ? h("span", { class: "tag", text: `NIH ${r.activity_code}` }) : null,
      !sch && r.status === "forecasted" ? h("span", { class: "tag ember", text: "Forecast: not open yet" }) : null,
      l.status === "kept" ? h("span", { class: "tag moss", text: "Kept" }) : null)),
    h("h3", { class: "lead-title" }, h("button", { class: "title-btn", onclick: (e) => openEvidence(l.record_id, e.currentTarget) },
      h("span", { text: name || l.record_id }))),
    sch && r.sponsor ? h("p", { class: "opp-num", text: r.sponsor }) : null,
    // A listing that states neither field gets one line, not two empty boxes (S22, audit S6).
    !deadline && (!sch || amount === NOT_STATED)
      ? h("p", { class: "hint no-size", text: sch ? "Deadline and amount: not stated in the record." : "Deadline: not stated in the record." })
      : h("dl", { class: "facts" },
        h("div", { class: "fact" }, h("dt", { text: "Deadline" }), h("dd", { text: deadline ? f.formatDate(deadline) : NOT_STATED })),
        sch ? h("div", { class: "fact" }, h("dt", { text: "Amount" }), h("dd", { text: amount })) : null),
    l.verdict_lines.length ? h("div", { class: "reason" }, h("b", { text: "Why: " }),
      l.verdict_lines.length === 1 ? h("span", { text: l.verdict_lines[0] })
        : h("ul", { class: "notes" }, l.verdict_lines.map((x) => h("li", { text: x })))) : null,
    l.gaps.length ? h("div", { class: "reason" }, h("b", { text: "Still needed: " }), h("span", { text: l.gaps.join("; ") })) : null,
    l.flagged ? h("p", { class: "notice warn" }, icon("warn"), h("span", { text: "The explanation was withheld because it failed the citation checks twice." }))
      : parsed ? h("details", { class: "why explain", open: OPEN.has(l.id),
        ontoggle: (e) => { if (e.target.open) OPEN.add(l.id); else OPEN.delete(l.id); } },
        h("summary", { "data-key": `why-${l.id}` }, h("span", { text: "Why it may fit" }), h("span", { class: "hint", text: " a model wrote this; each part cites a record" })),
        h("p", { text: plainExplanation(l.explanation) }),
        l.inference ? h("p", { class: "inference" }, h("span", { class: "tag", text: "Inference" }), h("span", { text: ` ${plainExplanation(l.inference)}` })) : null,
        h("p", { class: "cites" }, l.cited_ids.filter((c) => papers[c]).map((c) => h("button", { class: "paper-ref",
          onclick: (e) => openEvidence(c, e.currentTarget) }, icon("lock"), h("span", { text: papers[c].title }))))) : null,
    h("div", { class: "actions" },
      l.status === "dismissed"
        ? h("button", { class: "btn", "data-key": `restore-${l.id}`, onclick: () => setLead(l.id, "restore") }, icon("restore"), h("span", { text: "Restore" }))
        : [h("button", { class: `btn keep${l.status === "kept" ? " on" : ""}`, "data-key": `keep-${l.id}`, "aria-pressed": String(l.status === "kept"),
          onclick: () => setLead(l.id, l.status === "kept" ? "restore" : "keep") }, icon("keep"), h("span", { text: l.status === "kept" ? "Kept" : "Keep" })),
        l.verdict !== "not eligible" ? h("button", { class: "btn", "data-key": `dismiss-${l.id}`, onclick: () => setLead(l.id, "dismiss") }, icon("dismiss"), h("span", { text: "Dismiss" })) : null],
      h("button", { class: "btn quiet", "data-key": `evidence-${l.id}`, onclick: (e) => openEvidence(l.record_id, e.currentTarget) }, icon("evidence"), h("span", { text: "Evidence" }))));
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

const NOTE = { office: null, shown: false };

export function studentCompare(panel, { brief, goRoutes, announce }) {
  const kept = brief.leads.filter((l) => l.status === "kept");
  if (!kept.length) {
    fill(panel, h("div", { class: "empty" }, h("div", {}, h("p", { class: "lede", text: "Nothing kept yet." }),
      h("p", { class: "hint", text: "Keep fellowships or scholarships under Your options to compare them here." }),
      h("button", { class: "btn", onclick: goRoutes }, h("span", { text: "Go to Your options" })))));
    return;
  }
  const draw = () => studentCompare(panel, { brief, goRoutes, announce });
  const byOffice = { F: kept.filter((l) => l.route === "F"), S: kept.filter((l) => l.route === "S") };
  const routes = ["F", "S"].filter((r) => byOffice[r].length);
  if (!routes.includes(NOTE.office)) { NOTE.office = routes[0]; NOTE.shown = false; }
  const row = (l) => {
    const r = l.record || {};
    const sch = r.kind === "scholarship";
    const d = sch ? r.deadline : r.close_date;
    return h("tr", {},
      h("th", { scope: "row" }, h("span", { class: "row-title", text: sch ? r.name : r.title }),
        l.sample ? h("span", { class: "tag sample", text: SAMPLE }) : null,
        h("span", { class: "cell-note", text: STUDENT_ROUTES[l.route] })),
      h("td", {}, verdictChip(l.verdict)),
      h("td", { text: d ? f.formatDate(d) : "Not stated" }),
      h("td", { text: sch ? amountText(r) : "See the record" }),
      h("td", { text: l.gaps.join("; ") || "Nothing listed" }),
      h("td", { text: OFFICES[l.route].name }));
  };
  fill(panel,
    kept.some((l) => l.sample) ? h("p", { class: "notice warn sample-note", role: "note" }, h("span", { class: "tag sample", text: SAMPLE }),
      h("span", { text: " Your shortlist includes invented sample scholarships. They are not real." })) : null,
    h("div", { class: "table-wrap compare-wrap", role: "region", "aria-label": "Kept options, side by side", tabindex: "0" }, labelCells(h("table", { class: "compare stack" },
      h("thead", {}, h("tr", {}, ["Option", "Rule check", "Deadline", "Amount", "Still needed", "Temple office"].map((x) => h("th", { scope: "col", text: x })))),
      h("tbody", {}, kept.map(row))))),
    h("p", { class: "hint", text: "Each cell is copied from its record or checked against your CV by rule. “Not stated” means the listing leaves it blank." }),
    h("section", { class: "handoff" },
      h("h2", { class: "section-title", text: "Draft a note to a Temple office" }),
      h("fieldset", { class: "office-pick" }, h("legend", { text: "Office" }),
        routes.map((r) => h("label", { class: "office-opt" },
          h("input", { type: "radio", name: "st-office", checked: NOTE.office === r, onchange: () => { NOTE.office = r; NOTE.shown = false; draw(); } }),
          h("span", {}, h("b", { text: OFFICES[r].name }), h("br"),
            h("span", { class: "hint", text: r === "F" ? "For the kept fellowships" : "For the kept sample scholarships" }))))),
      h("div", { class: "go-row" },
        h("button", { class: "btn primary", type: "button", "data-key": "st-draft", onclick: () => { NOTE.shown = true; draw(); } },
          h("span", { text: NOTE.shown ? "Draft again" : "Draft the note" })),
        h("span", { class: "hint", text: "Code writes this note; no model. Perch never sends it." })),
      NOTE.shown ? note(NOTE.office, byOffice[NOTE.office], announce) : null));
}

function note(route, leads, announce) {
  const o = OFFICES[route];
  const lines = leads.map((l) => {
    const r = l.record || {};
    const name = r.kind === "scholarship" ? r.name : r.title;
    const d = r.kind === "scholarship" ? r.deadline : r.close_date;
    return `- ${name}${l.sample ? " (SAMPLE record, not real)" : ""}: ${l.verdict}${d ? `, deadline ${f.formatDate(d)}` : ""}${l.gaps.length ? `. Still needed: ${l.gaps.join("; ")}` : ""}`;
  });
  const subject = `Advice on ${route === "F" ? "fellowships" : "scholarships"}: ${leads.length} on my list`;
  const sample = leads.some((l) => l.sample);
  const body = [...(sample ? ["SAMPLE DATA, A DEMONSTRATION: DO NOT SEND. The scholarships marked SAMPLE are invented.", ""] : []),
    `Hello,`, "",
    `I am a student looking at the ${route === "F" ? "fellowships" : "scholarships"} below and would like advice on applying.`, "",
    ...lines, "",
    leads.some((l) => l.sample) ? "Note: records marked SAMPLE come from a test corpus in Perch and are not real scholarships.\n" : "",
    "Thank you."].join("\n");
  const box = h("textarea", { class: "input draft-body", rows: 10, "aria-label": `Draft to ${o.name}` });
  box.value = body;
  return h("div", { class: "draft fade-in" },
    leads.some((l) => l.sample) ? h("p", { class: "notice warn sample-note" }, h("span", { class: "tag sample", text: SAMPLE }),
      h("span", { text: " This note names invented sample scholarships." })) : null,
    h("label", { class: "field-label", for: "st-to", text: "To" }),
    h("input", { id: "st-to", class: "input", type: "text", placeholder: "Left empty for you" }),
    h("p", {}, h("b", { text: "Subject: " }), h("span", { text: subject })),
    box,
    h("p", { class: "hint" }, h("a", { href: o.url, target: "_blank", rel: "noopener", text: `${o.name} (public page)` })),
    h("div", { class: "actions" },
      h("button", { class: "btn", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(box.value); announce("Note copied."); } catch { box.select(); }
      } }, icon("paper"), h("span", { text: "Copy" })),
      // A note about invented scholarships is a demonstration: there is no mail button.
      sample ? null : h("a", { class: "btn", href: `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(box.value)}` },
        icon("download"), h("span", { text: "Open in mail" }))));
}
