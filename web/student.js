// Student mode (S18): the start form, the profile read from the CV, the two tabs
// (Fellowships, public; Scholarships, sample), a compare table and a code-written
// hand-off. Student mode exists only inside private mode: a student's input is always
// personal. Every verdict, gap, date and amount is written by the server's rule code or
// copied from the record; nothing here is a model's claim.

import { fill, h, icon } from "./dom.js";
import * as f from "./format.js";

export const STUDENT_ROUTES = { F: "Fellowships (public)", S: "Scholarships (sample)" };
const SAMPLE = "Sample data";
const SAMPLE_NOTE = "These are invented records from a test corpus. They show how student mode works with a real scholarship feed; they are not real scholarships. Do not apply to them.";
const VERDICT_CLASS = { eligible: "moss", "may be eligible": "amber", "not eligible": "ember" };
const OFFICES = {
  F: { name: "Scholar Development and Fellowships Advising", url: "https://undergraduate.temple.edu/fellowships" },
  S: { name: "Student Financial Services", url: "https://sfs.temple.edu/" },
};
const HINTS = {
  cv: "Read by rule only: level, year, major, GPA, enrolment, expected graduation and referees. It is never sent to a model.",
  interests: "A few sentences on what you want to study or work on. This steers the search.",
  achievements: "Up to five, one per line or numbered. Explanations may cite them.",
};
const D = { drafts: {}, busy: false, error: null };

export function isStudent(brief) {
  return Boolean(brief && brief.brief && brief.brief.options && brief.brief.options.student);
}

// ----- start: CV, interests, achievements -----

export async function renderStudentStart(root, { api, mode, go, announce, info }) {
  document.title = "Student — Perch";
  const draw = () => renderStudentStart(root, { api, mode, go, announce, info });
  if (!mode.state.available) {
    fill(root, h("div", { class: "private" }, h("h1", { text: "Student mode" }),
      h("p", { class: "notice", text: `Student mode needs private mode, which is not available here. ${mode.state.reason}` }),
      h("p", {}, h("a", { href: "#/", text: "Back to Find" }))));
    return;
  }
  if (!api.open) {
    fill(root, h("div", { class: "private" }, h("h1", {}, icon("lock"), h("span", { text: " Student mode" })),
      h("p", { class: "lede", text: "Student mode runs in a private session, because a CV is personal." }),
      h("button", { class: "btn primary", onclick: async () => { await mode.enable(); draw(); } },
        icon("lock"), h("span", { text: "Start a private session" }))));
    return;
  }
  for (const [k, v] of Object.entries(mode.state.drafts)) if (v && !D.drafts[k]) D.drafts[k] = v;
  const docs = (await api.session()).documents;
  const have = new Set(docs.map((d) => d.kind));
  const kinds = info.student_kinds || { cv: "Your CV", interests: "Your interests", achievements: "Your achievements" };

  async function add(kind, body) {
    D.busy = true; D.error = null; draw();
    try {
      await mode.send(body);
      D.drafts[kind] = "";
      delete mode.state.drafts[kind];
      announce(`${kinds[kind]} added.`);
    } catch (e) { D.error = e.message; }
    D.busy = false; draw();
  }
  async function build() {
    D.busy = true; D.error = null; draw();
    try {
      await api.createStudent({});
      go("#/brief/private/profile");
    } catch (e) { D.error = e.message; D.busy = false; draw(); }
  }
  const ready = have.has("cv") && (have.has("interests") || have.has("achievements"));
  fill(root, h("div", { class: "private student" },
    h("h1", {}, icon("lock"), h("span", { text: " Student mode" })),
    h("p", { class: "lede", text: "Paste your CV, a note on your interests and a few achievements. Perch lists fellowships from public records and scholarships from a sample database, checks each one against your CV by rule, and lists what you would still need." }),
    h("p", { class: "notice sample-note" }, h("span", { class: "tag sample", text: SAMPLE }),
      h("span", { text: " The scholarships tab uses invented sample records. Fellowships are real public listings." })),
    D.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: D.error })) : null,
    h("ol", { class: "private-docs" }, Object.entries(kinds).map(([kind, label]) => {
      const d = docs.find((x) => x.kind === kind);
      return h("li", { class: "card" },
        h("div", { class: "doc-head" }, h("h2", { class: "doc-title", text: label }),
          d ? h("span", { class: "tag moss", text: `Added, ${d.chars.toLocaleString("en-US")} characters` }) : null),
        h("p", { class: "hint", text: HINTS[kind] }),
        d ? h("button", { class: "btn quiet", onclick: async () => { await api.removeDocument(kind); draw(); } },
          icon("dismiss"), h("span", { text: "Remove" }))
          : h("div", { class: "doc-in" },
            h("label", { class: "field-label", for: `st-${kind}`, text: "Paste text" }),
            h("textarea", { id: `st-${kind}`, rows: kind === "cv" ? 8 : 4, value: D.drafts[kind] || "",
              oninput: (e) => { D.drafts[kind] = e.target.value; } }),
            h("div", { class: "doc-actions" },
              h("button", { class: "btn", disabled: D.busy, onclick: () => {
                const text = (D.drafts[kind] || "").trim();
                if (text) add(kind, { kind, text });
              } }, h("span", { text: "Add text" })))));
    })),
    h("div", { class: "doc-actions" },
      h("button", { class: "btn primary", disabled: D.busy || !ready, onclick: build },
        h("span", { text: D.busy ? "Starting" : "Find fellowships and scholarships" })),
      ready ? null : h("p", { class: "hint", text: "Add your CV and either your interests or your achievements." }))));
}

// ----- profile -----

export function studentProfile(d, { briefId }) {
  const rows = d.student || [];
  return [
    h("section", { class: "card" },
      h("h2", { class: "section-title" }, icon("lock"), h("span", { text: " What Perch read from your CV" })),
      h("p", { class: "hint", text: "Read by rule, not by a model, and kept in this session only. If something is missing or wrong, edit your CV and build again." }),
      rows.length ? h("dl", { class: "fields" }, rows.map(([k, v]) => h("div", { class: "field" }, h("dt", { text: k }), h("dd", { text: v }))))
        : h("p", { class: "hint", text: "Nothing read yet." })),
    h("p", { class: "next" }, h("a", { class: "btn primary", href: `#/brief/${encodeURIComponent(briefId)}/routes` },
      h("span", { text: "See fellowships and scholarships" })))];
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
    h("span", { text: STUDENT_ROUTES[r] }), r === "S" ? h("span", { class: "tag sample", text: SAMPLE }) : null,
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
      text: `${f.plural(ok.length, "lead")} you may apply for` }),
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
      h("span", { class: `tag ${VERDICT_CLASS[l.verdict] || ""}`, text: l.verdict }),
      sch && r.award_type ? h("span", { class: "tag", text: r.award_type }) : null,
      !sch && r.activity_code ? h("span", { class: "tag", text: `NIH ${r.activity_code}` }) : null,
      l.status === "kept" ? h("span", { class: "tag moss", text: "Kept" }) : null)),
    h("h3", { class: "lead-title" }, h("button", { class: "title-btn", onclick: (e) => openEvidence(l.record_id, e.currentTarget) },
      h("span", { text: name || l.record_id }))),
    sch && r.sponsor ? h("p", { class: "opp-num", text: r.sponsor }) : null,
    h("dl", { class: "facts" },
      h("div", { class: "fact" }, h("dt", { text: "Deadline" }), h("dd", { text: deadline ? f.formatDate(deadline) : "Not stated in the record" })),
      sch ? h("div", { class: "fact" }, h("dt", { text: "Amount" }), h("dd", { text: amount })) : null),
    h("ul", { class: "notes" }, l.verdict_lines.map((x) => h("li", { text: x }))),
    l.gaps.length ? h("div", { class: "gaps" }, h("h4", { class: "mini", text: "Still needed" }),
      h("ul", {}, l.gaps.map((g) => h("li", { text: g })))) : null,
    l.flagged ? h("p", { class: "notice warn" }, icon("warn"), h("span", { text: "The explanation was withheld because it failed the citation checks twice." }))
      : parsed ? h("div", { class: "explain" }, h("p", { class: "hint", text: "Why it may fit (a model wrote this; each part cites a record)" }),
        h("p", { text: plainExplanation(l.explanation) }),
        l.inference ? h("p", { class: "inference" }, h("span", { class: "tag", text: "Inference" }), h("span", { text: ` ${plainExplanation(l.inference)}` })) : null,
        h("p", { class: "cites" }, l.cited_ids.filter((c) => papers[c]).map((c) => h("button", { class: "paper-ref",
          onclick: (e) => openEvidence(c, e.currentTarget) }, icon("lock"), h("span", { text: papers[c].title }))))) : null,
    h("div", { class: "actions" },
      l.status === "dismissed"
        ? h("button", { class: "btn", onclick: () => setLead(l.id, "restore") }, icon("restore"), h("span", { text: "Restore" }))
        : [h("button", { class: `btn keep${l.status === "kept" ? " on" : ""}`, "aria-pressed": String(l.status === "kept"),
          onclick: () => setLead(l.id, l.status === "kept" ? "restore" : "keep") }, icon("keep"), h("span", { text: l.status === "kept" ? "Kept" : "Keep" })),
        l.verdict !== "not eligible" ? h("button", { class: "btn", onclick: () => setLead(l.id, "dismiss") }, icon("dismiss"), h("span", { text: "Dismiss" })) : null],
      h("button", { class: "btn quiet", onclick: (e) => openEvidence(l.record_id, e.currentTarget) }, icon("evidence"), h("span", { text: "Evidence" }))));
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
  return "Not stated in the record";
}

// ----- compare and hand-off (code-written; nothing is sent) -----

export function studentCompare(panel, { brief, goRoutes, announce }) {
  const kept = brief.leads.filter((l) => l.status === "kept");
  if (!kept.length) {
    fill(panel, h("div", { class: "empty" }, h("div", {}, h("p", { class: "lede", text: "Nothing kept yet." }),
      h("p", { class: "hint", text: "Keep fellowships or scholarships on the Routes tab to compare them here." }),
      h("button", { class: "btn", onclick: goRoutes }, h("span", { text: "Go to Routes" })))));
    return;
  }
  const rows = kept.map((l) => {
    const r = l.record || {};
    const sch = r.kind === "scholarship";
    return [sch ? r.name : r.title, STUDENT_ROUTES[l.route], l.verdict,
      (sch ? r.deadline : r.close_date) ? f.formatDate(sch ? r.deadline : r.close_date) : "Not stated",
      sch ? amountText(r) : "See the record", l.gaps.join("; ") || "Nothing listed", OFFICES[l.route].name];
  });
  const byOffice = { F: kept.filter((l) => l.route === "F"), S: kept.filter((l) => l.route === "S") };
  fill(panel,
    kept.some((l) => l.sample) ? h("p", { class: "notice warn sample-note" }, h("span", { class: "tag sample", text: SAMPLE }), h("span", { text: ` ${SAMPLE_NOTE}` })) : null,
    h("div", { class: "table-wrap", role: "region", "aria-label": "Kept options, side by side", tabindex: "0" }, h("table", { class: "compare" },
      h("thead", {}, h("tr", {}, ["Lead", "Route", "Verdict", "Deadline", "Amount", "Still needed", "Office"].map((x) => h("th", { scope: "col", text: x })))),
      h("tbody", {}, rows.map((row) => h("tr", {}, row.map((x, i) => h(i ? "td" : "th", { scope: i ? null : "row", text: x }))))))),
    ["F", "S"].filter((r) => byOffice[r].length).map((r) => handoff(r, byOffice[r], announce)));
}

function handoff(route, leads, announce) {
  const o = OFFICES[route];
  const lines = leads.map((l) => {
    const r = l.record || {};
    const name = r.kind === "scholarship" ? r.name : r.title;
    const d = r.kind === "scholarship" ? r.deadline : r.close_date;
    return `- ${name}${l.sample ? " (SAMPLE record, not real)" : ""}: ${l.verdict}${d ? `, deadline ${f.formatDate(d)}` : ""}${l.gaps.length ? `. Still needed: ${l.gaps.join("; ")}` : ""}`;
  });
  const body = [`Hello,`, "",
    `I am a student looking at the ${route === "F" ? "fellowships" : "scholarships"} below and would like advice on applying.`, "",
    ...lines, "",
    leads.some((l) => l.sample) ? "Note: records marked SAMPLE come from a test corpus in Perch and are not real scholarships.\n" : "",
    "Thank you."].join("\n");
  const box = h("textarea", { rows: 10, "aria-label": `Draft to ${o.name}` });
  box.value = body;
  return h("section", { class: "card handoff" },
    h("h2", { class: "section-title", text: `Draft to ${o.name}` }),
    h("p", { class: "hint" }, h("span", { text: "Written by code from the kept leads. The To line is yours to fill. Nothing is sent from Perch. " }),
      h("a", { href: o.url, target: "_blank", rel: "noopener", text: `${o.name} (public page)` })),
    h("label", { class: "field-label", text: "To" }), h("input", { type: "text", placeholder: "Fill in the address yourself", "aria-label": "To" }),
    box,
    h("button", { class: "btn", onclick: async () => {
      try { await navigator.clipboard.writeText(box.value); announce("Draft copied."); } catch { box.select(); }
    } }, icon("paper"), h("span", { text: "Copy draft" })));
}
