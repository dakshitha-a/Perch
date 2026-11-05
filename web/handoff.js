// Hand off: a draft email to one Temple office about the kept leads (POST
// /briefs/{id}/handoff). A model writes the opening paragraph; code writes the list with
// dates and amounts copied from the records. Perch never sends it. Signed in, the draft is
// made by a job on the worker (S48): the POST answers {job_id} and draftOf polls GET
// /briefs/{id}/handoff until the draft is stored, encrypted, in the account. Without
// accounts the POST answers the draft itself.

import { h, fill, icon } from "./dom.js";

const WHAT = { A: "grants", B: "industry leads" };
// Mirrors perch/offices.py (a test checks they match): the ERA step before anything goes out.
const SUBMISSION_URL = "https://research.temple.edu/researchadministration/contact-us/find-your-res-administrator";
const SUBMISSION_NOTE = "Before anything goes to a sponsor, Temple routes it through ERA for institutional review and approval. That covers every grant proposal and any company agreement that brings Temple funding. Your assigned research administrator supports that step.";
const MAILTO_MAX = 1800; // longer mailto links get cut off by some mail apps

// Per brief: the chosen office, and per office the draft as the user has edited it.
const H = { briefId: null, office: null, drafts: {}, busy: null, error: null, keptSig: "" };

function reset(briefId) {
  Object.assign(H, { briefId, office: null, drafts: {}, busy: null, error: null, keptSig: "" });
}

const POLL_MS = 1500;
const POLL_MAX_MS = 120000;

// The draft from the POST, or, when the POST queued a job, from polling the stored draft.
export async function draftOf(api, briefId, office, sleep = (ms) => new Promise((r) => setTimeout(r, ms))) {
  const d = await api.handoff(briefId, { office });
  if (!d.job_id || d.subject !== undefined) return d;
  const end = Date.now() + POLL_MAX_MS;
  for (;;) {
    await sleep(POLL_MS);
    const got = await api.handoffGet(briefId, office, d.job_id);
    const state = got.job && got.job.state;
    if (state === "succeeded" && got.result) return got.result;
    if (!got.job || state === "succeeded" || ["failed", "dead", "cancelled"].includes(state)) {
      throw new Error(got.job && got.job.error === "consent_required"
        ? "accept the current consent first, in Account and data." : "the job did not finish. Try again.");
    }
    if (Date.now() > end) throw new Error("it is taking longer than usual. Try again in a minute.");
  }
}

// The box fits the draft: 80 characters to a line, at least 8 rows and at most 18 (U12).
export function bodyRows(text) {
  const lines = String(text || "").split("\n").reduce((n, l) => n + Math.max(1, Math.ceil(l.length / 80)), 0);
  return Math.min(18, Math.max(8, lines + 1));
}

function draftText(d) {
  return `Subject: ${d.subject}\n\n${d.body}`;
}

export async function copy(text, announce) {
  try {
    await navigator.clipboard.writeText(text);
    announce("The draft is copied. Paste it into your email.");
    return true;
  } catch {
    announce("Copying was blocked by the browser. Select the text and copy it by hand.");
    return false;
  }
}

export function mailto(d) {
  const subject = encodeURIComponent(d.subject);
  const body = encodeURIComponent(d.body);
  if (subject.length + body.length <= MAILTO_MAX) return `mailto:?subject=${subject}&body=${body}`;
  return `mailto:?subject=${subject}&body=${encodeURIComponent("(The draft from Perch is copied. Paste it here.)")}`;
}

export function renderHandoff(box, { api, briefId, kept, offices, announce, redraw, guest, signIn }) {
  if (!box || !offices) return;
  const OFFICES = offices.map((o) => ({ ...o, what: WHAT[o.route] }));
  if (H.briefId !== briefId) reset(briefId);
  const keptSig = kept.map((l) => l.id).sort().join(",");
  if (H.keptSig !== keptSig) { H.drafts = {}; H.error = null; H.keptSig = keptSig; }
  const count = (route) => kept.filter((l) => (l.route || "A") === route).length;
  const usable = OFFICES.filter((o) => count(o.route));
  if (!usable.length) { box.replaceChildren(); return; }
  if (!H.office || !count(OFFICES.find((o) => o.key === H.office).route)) H.office = usable[0].key;
  const office = OFFICES.find((o) => o.key === H.office);
  const draft = H.drafts[office.key];

  const choices = h("fieldset", { class: "office-pick" },
    h("legend", { text: "Which office?" }),
    ...OFFICES.map((o) => {
      const n = count(o.route);
      return h("label", { class: `office-opt${n ? "" : " off"}` },
        h("input", { type: "radio", name: "office", value: o.key, "data-key": `office-${o.key}`,
          checked: o.key === H.office, disabled: !n,
          onchange: () => { H.office = o.key; H.error = null; redraw(`office-${o.key}`); } }),
        h("span", {}, h("b", { text: o.name }),
          h("span", { class: "hint", text: n ? ` · ${n} kept ${n === 1 ? o.what.replace(/s$/, "") : o.what}`
            : ` · no kept ${o.what}` })));
    }));

  // While the model writes, the box names the office and the kept leads that go in the note.
  // It uses what the page already holds; nothing is asked of the server (P7).
  const titleOf = (l) => (l.opportunity && l.opportunity.title) || (l.organisation && l.organisation.name) || l.title
    || (l.record && (l.record.title || l.record.name)) || "Untitled lead";
  const inNote = kept.filter((l) => (l.route || "A") === office.route).map(titleOf);
  const status = H.busy === office.key
    ? h("div", { class: "handoff-progress" },
      h("p", { class: "hint", text: `Writing to ${office.name}.` }),
      inNote.length ? h("div", {}, h("p", { class: "hint", text: "Leads in this note:" }),
        h("ul", { class: "progress-leads" }, ...inNote.slice(0, 6).map((t) => h("li", { text: t })),
          inNote.length > 6 ? h("li", { text: `and ${inNote.length - 6} more` }) : null)) : null,
      h("p", { class: "hint", role: "status", text: "A model is writing the opening paragraph. This can take up to two minutes…" }))
    : H.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: H.error })) : null;

  async function makeDraft(focusKey = "handoff-subject") {
    H.busy = office.key; H.error = null; redraw("handoff-make");
    try {
      const d = await draftOf(api, briefId, office.key);
      H.drafts[office.key] = { subject: d.subject, body: d.body, flagged: d.flagged, model: d.model,
        n: d.lead_ids.length };
      announce("The draft is ready below. You can edit it.");
    } catch (e) {
      H.error = `The draft could not be made: ${e.message}`;
    }
    H.busy = null;
    redraw(H.drafts[office.key] ? focusKey : "handoff-make");
  }
  // A draft needs an account, so a guest gets a link, not a button that fails. Once a draft
  // exists, Draft again sits under it with the other actions (U13).
  const make = guest
    ? h("a", { class: "btn primary", href: signIn, "data-key": "handoff-signin", text: "Sign in to draft a note to the office" })
    : h("button", { class: `btn ${draft ? "quiet" : "primary"}`, type: "button", "data-key": "handoff-make",
      disabled: H.busy !== null, onclick: () => makeDraft() },
    icon("pen"), h("span", { text: draft ? "Draft again" : "Draft the email" }));

  const parts = [h("h2", { class: "section-title", id: "handoff-title", text: "Hand off" }),
    h("p", { class: "hint", text: "Perch drafts an email to the Temple office for these leads. "
      + "You edit it and send it yourself. Perch never sends it." }),
    choices,
    h("p", { class: "office-link" }, h("span", { text: "To: add the address yourself. " }),
      h("a", { href: office.url, target: "_blank", rel: "noopener",
      text: `${office.name} contacts on research.temple.edu` })),
    h("p", { class: "hint submission-note", "data-key": "submission-note" }, h("span", { text: SUBMISSION_NOTE + " " }),
      h("a", { href: SUBMISSION_URL, target: "_blank", rel: "noopener", text: "Find your research administrator" })),
    draft ? null : h("div", { class: "actions" }, make), draft ? null : status];

  if (draft) {
    const subject = h("input", { id: "handoff-subject", "data-key": "handoff-subject", class: "input", value: draft.subject,
      oninput: (e) => { draft.subject = e.target.value; } });
    const body = h("textarea", { id: "handoff-body", "data-key": "handoff-body", class: "input draft-body", rows: String(bodyRows(draft.body)),
      oninput: (e) => { draft.body = e.target.value; } });
    body.value = draft.body;
    const tag = draft.flagged
      ? h("p", { class: "notice" }, icon("warn"), h("span", { text: "The model’s opening failed the checks twice, so this draft "
        + "opens with a plain sentence instead. Everything else is written by code from the records." }))
      : h("p", { class: "hint model-note" }, h("span", { class: "tag model", text: "Model text" }),
        h("span", { text: ` The opening paragraph was written by ${draft.model || "a model"} and checked against the records it cites. `
          + "The list of leads, dates, amounts and papers is written by code." }));
    parts.push(h("div", { class: "draft" }, tag,
      h("label", { class: "field-label", for: "handoff-subject", text: "Subject" }), subject,
      h("label", { class: "field-label", for: "handoff-body", text: "Email" }), body,
      h("div", { class: "actions" },
        h("button", { class: "btn primary", type: "button", "data-key": "handoff-copy",
          onclick: () => copy(draftText(draft), announce) }, h("span", { text: "Copy the draft" })),
        h("a", { class: "btn", href: "#", "data-key": "handoff-mail",
          onclick: async (e) => { e.currentTarget.href = mailto(draft); await copy(draftText(draft), announce); } },
        h("span", { text: "Open in my mail app" })), make),
      status,
      h("p", { class: "hint", text: "Open in my mail app also copies the draft. A long draft is too long for a mail link: paste it into the new message." })));
  }
  fill(box, h("section", { class: "handoff", "aria-labelledby": "handoff-title" }, ...parts));
}
