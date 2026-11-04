// Student mode (S18): the start screen, the profile read from the CV, the two tabs
// (Fellowships, public; Scholarships, sample), a compare table and a code-written
// hand-off. Every verdict, gap, date and amount is written by the server's rule code or
// copied from the record; nothing here is a model's claim.

import { evMark, fill, h, icon, labelCells } from "./dom.js";
import { copy, mailto } from "./handoff.js";
import * as f from "./format.js";

// The sample tab holds fellowships and prizes as well as scholarships (S22, audit S9).
export const STUDENT_ROUTES = { F: "Temple awards and fellowships (public)", S: "Scholarships and awards (sample)" };
const SAMPLE = "Sample data";
const SAMPLE_NOTE = "These are invented records from a test corpus. They show how student mode works with a real scholarship feed; they are not real scholarships. Do not apply to them.";
const VERDICTS = { eligible: ["eligible", "✓", "Eligible"], "may be eligible": ["may", "?", "May be eligible"],
  "not eligible": ["not", "✕", "Not eligible"] };

// A verdict chip: a mark and a word, so colour is never the only signal (S24).
export function verdictChip(v) {
  const [cls, mark, word] = VERDICTS[v] || ["", "", v];
  return h("span", { class: `verdict ${cls}` }, h("span", { class: "mk", "aria-hidden": "true", text: mark }), h("span", { text: word }));
}
const D = { busy: false, error: null };
// The brief on screen is the guest's invented sample student (options.persona); the wording
// then says "the sample student" instead of "you" (S43 S8).
let SAMPLE_STUDENT = false;
const setSample = (brief) => { SAMPLE_STUDENT = Boolean(brief && brief.brief && brief.brief.options && brief.brief.options.persona); };
const cvWords = () => (SAMPLE_STUDENT ? "the sample student's CV" : "your CV");
const NOT_STATED = "Not stated in the record";
const SHUT = new Set(); // cards whose "More on why it may fit" was closed; it starts open (S27, Dakshitha)

// Forget what this module held for the brief that was on screen (S27).
export function resetStudent() {
  Object.assign(D, { busy: false, error: null });
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

// ----- start -----

// The start screen. A signed-in student adds a CV (and optionally interests and
// achievements); they are stored encrypted and the brief reads them. A visitor without an
// account gets the built-in SYNTHETIC sample student; using a CV of their own needs an account.
export async function renderStudentStart(root, { api, go, announce, session, signIn, refresh }) {
  document.title = "Check my fit — Perch";
  const sess = session || { signed_in: false };
  const draw = () => renderStudentStart(root, { api, go, announce, session, signIn, refresh });
  async function sample() {
    D.busy = true; D.error = null; draw();
    try {
      const r = await api.create({}, "student");
      D.busy = false;
      if (refresh) await refresh();
      go(`#/brief/${encodeURIComponent(r.id)}/routes`);
    } catch (e) {
      D.error = e.message; D.busy = false; draw();
      const b = root.querySelector('[data-key="st-build"]'); if (b) b.focus();
      announce(e.message);
    }
  }
  if (!sess.signed_in) {
    // DRAFT copy (S43): the start screen for a visitor without an account.
    fill(root, h("div", { class: "screen student-start" },
      h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
      h("div", {}, h("h1", { class: "page", text: "Check my fit." }),
        h("p", { class: "page-sub", text: "Perch checks each option against a student's CV by rule and shows what is still needed. Sign in to use your own CV, or try the sample student to see how it works." })),
      h("div", { class: "sample-row" },
        h("span", { text: "The sample is an invented student, labelled SYNTHETIC. Nothing in it is about you. Its sample scholarships are invented; the fellowships it checks are real public listings." }),
        h("button", { class: "btn primary", type: "button", "data-key": "st-build", disabled: D.busy, onclick: sample },
          h("span", { text: D.busy ? "Starting" : "Try a sample student" })),
        sess.guest ? h("a", { class: "btn", href: signIn(), text: "Sign in to use your own CV" }) : null,
        !sess.guest ? h("a", { class: "btn", href: signIn(), text: "Sign in" }) : null),
      D.error ? h("p", { class: "notice error go-error", id: "st-error", role: "alert" }, icon("warn"), h("span", { text: D.error })) : null));
    return;
  }

  let docs = [];
  try {
    docs = await api.docs("student");
  } catch (e) {
    if (e.code === "consent_required") { go("#/welcome"); return; }
    D.error = e.message;
  }
  const cv = docs.find((d) => d.kind === "cv");
  const ready = Boolean(cv);
  const provider = (sess.consent && sess.consent.provider_name) || "the model provider";
  const field = { text: "", label: "", interests: "" };

  async function add(kind, body) {
    D.busy = true; D.error = null;
    try {
      await api.addDoc({ kind, ...body }, "student");
      announce("Saved.");
    } catch (e) { D.error = e.message; announce(e.message); }
    D.busy = false;
    draw();
  }
  async function remove(d) {
    try { await api.removeDoc(d.id); announce("Removed."); } catch (e) { D.error = e.message; }
    draw();
  }
  function upload(file) {
    const rd = new FileReader();
    rd.onload = () => add("cv", { filename: file.name, data: String(rd.result).split(",")[1] || "" });
    rd.readAsDataURL(file);
  }
  async function build() {
    D.busy = true; D.error = null; draw();
    try {
      if (sess.audience !== "student") {  // a dual-role account: the brief is built on the side it is on
        await api.setAudience("student");
        if (refresh) await refresh();
      }
      const r = await api.create({ doc_ids: docs.map((d) => d.id) }, "student");
      D.busy = false;
      go(`#/brief/${encodeURIComponent(r.id)}/routes`);
    } catch (e) {
      D.error = e.message; D.busy = false; draw();
      announce(e.message);
    }
  }
  // DRAFT copy (S43): the headings, labels and privacy line on this screen.
  fill(root, h("div", { class: "screen student-start" },
    h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
    h("div", {}, h("h1", { class: "page", id: "st-title", tabindex: "-1", text: "Tell Perch about you." }),
      h("p", { class: "page-sub", text: "Perch checks each award against your CV by rule and shows what is still needed." })),
    h("section", { class: "box", "aria-labelledby": "cv-h" },
      h("h2", { class: "section-title", id: "cv-h", text: "Your CV" }),
      cv ? h("div", { class: "added" }, h("span", { text: `${cv.name || "Your CV"} is stored.` }),
        h("button", { class: "btn", type: "button", "data-key": "rm-cv", onclick: () => remove(cv) }, h("span", { text: "Remove" })))
        : [h("label", { class: "big", for: "cv-text", text: "Paste your CV text" }),
          h("textarea", { id: "cv-text", rows: 6, maxlength: 60000, value: field.text, oninput: (e) => { field.text = e.target.value; } }),
          h("div", { class: "file-row" },
            h("button", { class: "btn", type: "button", "data-key": "cv-save", disabled: D.busy,
              onclick: () => { const t = root.querySelector("#cv-text").value.trim(); if (t) add("cv", { text: t, filename: "cv.txt" }); else announce("Paste your CV text first."); } },
            h("span", { text: "Save my CV" })),
            h("label", { class: "btn", for: "cv-file" }, h("span", { text: "Or upload a file" })),
            h("input", { id: "cv-file", class: "sr-only", type: "file", accept: ".pdf,.docx,.txt,.md",
              onchange: (e) => { if (e.target.files[0]) upload(e.target.files[0]); } }))],
      h("p", { class: "hint", text: `Your CV is stored encrypted. Contact details are blanked before ${provider} reads it.` })),
    h("section", { class: "box", "aria-labelledby": "more-h" },
      h("h2", { class: "section-title", id: "more-h", text: "Interests and achievements (optional)" }),
      docs.filter((d) => d.kind !== "cv").length ? h("ul", { class: "docs" }, docs.filter((d) => d.kind !== "cv").map((d) => h("li", { class: "doc" },
        h("span", { class: "doc-name", text: d.label || d.kind }),
        h("button", { class: "btn", type: "button", "data-key": `rm-${d.id}`, onclick: () => remove(d), "aria-label": `Remove ${d.label || d.kind}` }, h("span", { text: "Remove" }))))) : null,
      h("label", { class: "big", for: "st-interests", text: "What you are interested in" }),
      h("textarea", { id: "st-interests", rows: 3, maxlength: 4000 }),
      h("button", { class: "btn", type: "button", disabled: D.busy, onclick: () => { const t = root.querySelector("#st-interests").value.trim(); if (t) add("interests", { text: t }); } },
        h("span", { text: "Save interests" })),
      h("label", { class: "big", for: "st-ach", text: "An achievement" }),
      h("textarea", { id: "st-ach", rows: 3, maxlength: 4000 }),
      h("button", { class: "btn", type: "button", disabled: D.busy, onclick: () => { const t = root.querySelector("#st-ach").value.trim(); if (t) add("entry", { text: t, label: "Achievement" }); } },
        h("span", { text: "Add achievement" }))),
    D.error ? h("p", { class: "notice error go-error", id: "st-error", role: "alert" }, icon("warn"), h("span", { text: D.error })) : null,
    h("div", { class: "welcome-go" },
      h("button", { class: "btn primary big", type: "button", "data-key": "st-build", disabled: !ready || D.busy, onclick: build },
        h("span", { text: D.busy ? "Working" : "Find awards that fit" })),
      !ready ? h("p", { class: "hint", text: "Save your CV first." }) : null)));
  const t = root.querySelector("#st-title");
  if (t && !D.busy) t.focus({ preventScroll: true });
}

// ----- profile -----

export function studentProfile(d, { openEvidence }) {
  const rows = d.student || [];
  const mine = Object.entries(d.papers || {}).filter(([id, w]) => w.source === "user" || w.kind === "user");
  const interests = mine.filter(([id]) => /interests/.test(id));
  const achievements = mine.filter(([id]) => /achievement-/.test(id)); // one row per achievement
  // The documents the options cite: the interests note and the achievements.
  const ref = ([id, w]) => h("li", { class: "fade-in" }, h("button", { class: "paper", type: "button", onclick: (e) => openEvidence(id, e.currentTarget) },
    h("span", { class: "paper-title", text: w.title }),
    w.text ? h("span", { class: "paper-meta", text: w.text.replace(/^#.*$/gm, "").replace(/\s+/g, " ").trim().slice(0, 220) }) : null));
  return [h("div", { class: "prof-cols" },
    h("div", { class: "left" }, h("section", { class: "pblock" },
      h("h2", { class: "section-title", text: "What the rules read from your CV" }),
      rows.length ? h("dl", { class: "fields" }, rows.map(([k, v]) => h("div", { class: "field" }, h("dt", { text: k }), h("dd", { text: v }))))
        : h("div", { class: "skeleton" }, h("span", { style: "width:80%" }), h("span", { style: "width:60%" })),
      h("p", { class: "hint", text: "Read by code, not by a model." }))),
    h("div", { class: "right" }, h("section", { class: "pblock" },
      h("h2", { class: "section-title", text: "What steers the search" }),
      interests.length ? h("ul", { class: "papers" }, interests.map(ref)) : h("p", { class: "hint", text: "No interests note." }),
      h("h3", { class: "mini", text: "Your achievements" }),
      achievements.length ? h("ul", { class: "papers" }, achievements.map(ref)) : h("p", { class: "hint", text: "None added." }),
      h("p", { class: "hint", text: "Explanations may cite these." }))),
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

export function studentRoutes(panel, ctx) {
  const { brief, setRoute, openEvidence, setLead } = ctx;
  setSample(brief);
  // Only the guest's sample persona has a sample route; a signed-in student's brief holds
  // public records only and links to the samples screen (S43 M4, fork F6).
  const hasS = SAMPLE_STUDENT;
  const route = hasS ? ctx.route : "F";
  const leads = brief.leads.filter((l) => l.route === route);
  const done = (name) => {
    const s = brief.brief.stages.find((x) => x.name === name);
    return s && ["done", "skipped"].includes(s.status);
  };
  const ready = done(route === "F" ? "fellowships" : "scholarships");
  const n = (r) => brief.leads.filter((l) => l.route === r && l.verdict !== "not eligible" && l.status !== "dismissed").length;
  const sw = h("div", { class: "route-switch", role: "group", "aria-label": "Route" },
    (hasS ? ["F", "S"] : ["F"]).map((r) => h("button", { class: "route-btn", "data-key": `route-${r}`, "aria-pressed": String(route === r),
      "aria-label": `${STUDENT_ROUTES[r]}${r === "S" ? ", sample data" : ""}${done(r === "F" ? "fellowships" : "scholarships") ? `, ${n(r)}` : ""}`,
      onclick: () => setRoute(r) },
    // Shorter visible names keep the sort switch on this row at laptop width; the aria-label
    // keeps the full name, and the Sample data tag marks the sample route (S27).
    h("span", { class: "lbl-long", "aria-hidden": "true", text: r === "F" ? "Fellowships" : "Scholarships and awards" }), h("span", { class: "lbl-short", "aria-hidden": "true", text: r === "F" ? "Fellowships" : "Samples" }),
    r === "S" ? h("span", { class: "tag sample lbl-long", text: SAMPLE }) : null,
    done(r === "F" ? "fellowships" : "scholarships") ? h("span", { class: "route-n", text: String(n(r)) }) : null)));
  // DRAFT copy
  const samplesLink = hasS ? null : h("p", { class: "hint" }, h("a", { href: "#/samples/student", text: "See how Perch works with sample records" }),
    h("span", { text: ". They are invented and open on their own screen." }));
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
    // DRAFT copy: the sources are the ones the Fellowships stage reads (_run_fellowships):
    // every public scholarship row in the store (Temple's public award pages and the
    // Scholar Development and Fellowships Advising list) and NIH fellowships.
    h("p", { class: "hint", text: route === "F"
      ? "Public listings: Temple's public award pages, Temple's Scholar Development and Fellowships Advising list and NIH fellowships. Their own pages set the full rules, so the best verdict here is “may be eligible”."
      : `Checked against ${cvWords()} by rule. “May be eligible” means the record asks for something ${SAMPLE_STUDENT ? "that CV does" : "your CV does"} not show.` }),
    samplesLink,
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
// A public fellowship's deadline or amount was copied by code from the award's own page.
const FROM_PAGE = "from the award's page";
const fromPage = (r) => r.kind === "scholarship" && ["temple_sdfa", "temple_pages"].includes(r.source) && Boolean(r.details_url);
const withHint = (text, r) => (fromPage(r) && text !== NOT_STATED ? `${text} (${FROM_PAGE})` : text);
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
        h("div", { class: "fact" }, h("dt", { text: !sch && f.expiresOnly(r) && !f.standardDates(r) ? "Announcement" : "Deadline" }), h("dd", {}, dueText(r, deadline), deadline && fromPage(r) ? h("span", { class: "from-page", text: ` ${FROM_PAGE}` }) : null)),
        sch ? h("div", { class: "fact" }, h("dt", { text: "Amount" }), h("dd", {}, amount, amount !== NOT_STATED && fromPage(r) ? h("span", { class: "from-page", text: ` ${FROM_PAGE}` }) : null)) : null),
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
  const items = (work || "").split(/;\s*/).map((x) => plainExplanation(x.replace(/^\s*(?:user:)?(?:achievement-[a-e]|interests)\s*/, ""))
    .replace(/\.$/, "")).filter(Boolean);
  const reason = l.inference ? plainExplanation(you(f.ownInPlace(l.inference, own))) : null;
  // In the weak band the model's sentence may say it does not fit, so the label does not
  // promise a fit: "How it relates", as on the researcher's weak cards (Q17, T15: one
  // rule on both paths, the band's).
  const weak = (f.fitBand(l.match_score) || {}).key === "weak";
  const label = weak ? "How it relates" : "Why it may fit";
  return h("div", { class: "fit-reason" },
    reason ? h("p", { class: "fit-why" }, h("b", { text: `${label}: ` }), h("span", { text: reason }),
      h("span", { class: "tag model", text: "Model text" })) : null,
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

// Citation brackets go; a document's id reads as "your achievement A".
function plainExplanation(text) {
  const who = SAMPLE_STUDENT ? "the sample student's" : "your";
  return String(text || "").replace(/\s*\[[^\]]*\]/g, "")
    .replace(/\b(?:user:)?achievement-([a-e])\b/g, (_, c) => `${who} achievement ${c.toUpperCase()}`)
    .replace(/\b(?:user:)?interests\b/g, `${who} interests note`)
    .replace(/\bCited work:/, "Your work:").trim()
    .replace(/^./, (c) => c.toUpperCase());
}

function amountText(r) {
  if (r.amount_min != null && r.amount_max != null && r.amount_min !== r.amount_max) return `${f.money(r.amount_min)} to ${f.money(r.amount_max)}`;
  if (r.amount_max != null) return r.source === "temple_sdfa" && r.amount_min == null ? `Up to ${f.money(r.amount_max)}` : f.money(r.amount_max);
  return NOT_STATED;
}

// ----- compare and hand-off (code-written; nothing is sent) -----

// The office picked, and the note as edited, per office, for the kept set it was written for.
// The office picked; per office, the note the server wrote and the note as edited, for the
// kept set they were written for.
const NOTE = { office: null, edits: {}, subjects: {}, got: {}, keptSig: "" };

export function studentCompare(panel, ctx) {
  const { brief, goRoutes, announce, api } = ctx;
  setSample(brief);
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
    const ask = api && api.studentNote ? api.studentNote(ctx.briefId, route) : Promise.reject(new Error("The note needs the live app."));
    ask.then((n) => { NOTE.got[route] = { note: n }; }, (e) => { NOTE.got[route] = { error: e.message }; })
      .then(() => { if (NOTE.keptSig === keptSig && panel.querySelector(".st-note-wait")) draw(); });
  }
  const got = NOTE.got[route];
  const officeName = (r) => (offices[r] || {}).name || ((NOTE.got[r] || {}).note || {}).office || "The Temple office for this route";
  const row = (l) => {
    const r = l.record || {};
    const sch = r.kind === "scholarship";
    const d = sch ? r.deadline : r.close_date;
    return h("tr", {},
      h("th", { scope: "row" }, h("span", { class: "row-title", text: sch ? r.name : r.title }),
        l.sample ? h("span", { class: "tag sample", text: SAMPLE }) : null),
      h("td", {}, verdictChip(l.verdict)),
      // G17: under the Deadline column an expiry says it is none
      h("td", { text: !sch && f.expiresOnly(r) && !f.standardDates(r) ? `None stated; the announcement expires ${f.formatDate(d)}` : withHint(dueText(r, d), r) }),
      h("td", { text: sch ? withHint(amountText(r), r) : "See the record" }),
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
    h("p", { class: "hint", text: `Each cell is copied from its record or checked against ${cvWords()} by rule. “Not stated in the record” means the listing leaves it blank.` }));
}

// The note as the server wrote it (GET /briefs/{id}/student/note), editable here.
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
