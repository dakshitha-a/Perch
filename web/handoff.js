// Hand off: a draft email to one Temple office about the kept leads (POST
// /briefs/{id}/handoff). A model writes the opening paragraph; code writes the list with
// dates and amounts copied from the records. Perch never sends it and does not save it.

import { maskOn, maskToggle, onMaskChange } from "./private.js";
import { h, fill, icon } from "./dom.js";

const WHAT = { A: "grants", B: "industry leads" };
const MAILTO_MAX = 1800; // longer mailto links get cut off by some mail apps

// Per brief: the chosen office, and per office the draft as the user has edited it.
const H = { briefId: null, office: null, drafts: {}, busy: null, error: null, keptSig: "" };

function reset(briefId) {
  Object.assign(H, { briefId, office: null, drafts: {}, busy: null, error: null, keptSig: "" });
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

export function renderHandoff(box, { api, briefId, kept, offices, announce, redraw, docs = true }) {
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

  const status = H.busy === office.key
    ? h("p", { class: "hint", role: "status", text: "A model is writing the opening paragraph. This takes a few seconds…" })
    : H.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: H.error })) : null;

  async function makeDraft(focusKey = "handoff-subject") {
    H.busy = office.key; H.error = null; redraw(focusKey === "handoff-mask" ? focusKey : "handoff-make");
    try {
      const mask = api.mode === "private" ? maskOn() : false;
      const d = await api.handoff(briefId, { office: office.key, ...(api.mode === "private" ? { mask } : {}) });
      H.drafts[office.key] = { subject: d.subject, body: d.body, flagged: d.flagged, model: d.model,
        withheld: d.withheld || null, n: d.lead_ids.length, mask };
      announce(focusKey === "handoff-mask" ? "The draft was made again with the new mask setting." : "The draft is ready below. You can edit it.");
    } catch (e) {
      H.error = `The draft could not be made: ${e.message}`;
    }
    H.busy = null;
    redraw(H.drafts[office.key] ? focusKey : "handoff-make");
  }
  // A change of the mask setting makes the shown draft again at once (Q25); so does
  // coming back to a draft made before the Export menu's box changed it.
  if (api.mode === "private" && draft && draft.mask !== maskOn() && H.busy === null && !H.error) setTimeout(() => makeDraft("handoff-stale"), 0);
  onMaskChange((on) => {
    const d = H.drafts[office.key];
    if (H.briefId === briefId && d && d.mask !== on && H.busy === null && document.body.contains(box)) makeDraft("handoff-mask");
  });
  const make = h("button", { class: `btn ${draft ? "" : "primary"}`, type: "button", "data-key": "handoff-make",
    disabled: H.busy !== null, onclick: () => makeDraft() },
  icon("pen"), h("span", { text: draft ? "Draft again" : "Draft the email" }));

  const parts = [h("h2", { class: "section-title", id: "handoff-title", text: "Hand off" }),
    h("p", { class: "hint", text: "Perch drafts an email to the Temple office for these leads. "
      + "You edit it and send it yourself. Perch never sends it and does not save it." }),
    choices,
    h("p", { class: "office-link" }, h("span", { text: "To: left blank for you. " }),
      h("a", { href: office.url, target: "_blank", rel: "noopener",
      text: `${office.name} contacts on research.temple.edu` })),
    // The mask setting this draft uses, the same one as the Export menu's (review W6).
    api.mode === "private" && docs ? maskToggle("handoff-mask") : null, // nothing to mask without documents (U12)
    h("div", { class: "actions" }, make), status];

  if (draft) {
    const subject = h("input", { id: "handoff-subject", "data-key": "handoff-subject", class: "input", value: draft.subject,
      oninput: (e) => { draft.subject = e.target.value; } });
    const body = h("textarea", { id: "handoff-body", "data-key": "handoff-body", class: "input draft-body", rows: "18",
      oninput: (e) => { draft.body = e.target.value; } });
    body.value = draft.body;
    const tag = draft.withheld
      ? h("p", { class: "notice" }, icon("lock"), h("span", { text: `${draft.withheld} `
        + "Everything else is written by code from the records." }))
      : draft.flagged
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
        h("span", { text: "Open in my mail app" }))),
      h("p", { class: "hint", text: "Open in my mail app also copies the draft, in case your mail app shortens a long one." })));
  }
  fill(box, h("section", { class: "handoff", "aria-labelledby": "handoff-title" }, ...parts));
}
