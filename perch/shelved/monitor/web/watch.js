// What changed (S16): the latest weekly run per watched researcher (GET /watch). The job
// refreshes open NIH funding from Grants.gov, re-runs each brief and compares it with the
// last run. Every date shown is copied from a record. The email draft is written by code
// and is never sent.

import { h, fill, icon } from "./dom.js";
import { copy } from "./handoff.js";
import * as f from "./format.js";

const TRIGGERS = {
  award_ending: "A public award ends within 12 months",
  new_lead: "New in the top 10",
};
const OTHER = {
  award_ending: "Still ending within 12 months (already reported)",
  close_date: "Close date changed",
  dropped_lead: "No longer in the leads",
  new_industry_lead: "New industry lead (inferred)",
};

function change(c) {
  let detail = "";
  if (c.kind === "award_ending") detail = `Ends ${f.formatDate(c.after)}`;
  else if (c.kind === "new_lead") detail = c.after ? `Closes ${f.formatDate(c.after)}` : "Close date not stated in the record";
  else if (c.kind === "close_date") detail = `Was ${c.before ? f.formatDate(c.before) : "not stated"}, now ${c.after ? f.formatDate(c.after) : "not stated"}`;
  else if (c.kind === "dropped_lead") detail = c.after ? `Closed ${f.formatDate(c.after)}` : "Ranked out of the top 10";
  return h("li", { class: "change" },
    h("span", { class: `tag ${c.trigger ? "ember" : "moss"}`, text: c.trigger ? TRIGGERS[c.kind] : OTHER[c.kind] }),
    h("a", { href: c.source_url, target: "_blank", rel: "noopener", text: c.title }),
    detail ? h("span", { class: "hint", text: detail }) : null);
}

function digestCard(d, announce) {
  const fired = d.changes.filter((c) => c.trigger);
  const rest = d.changes.filter((c) => !c.trigger);
  const name = d.researcher.name || f.shortId(d.researcher.id);
  const when = d.baseline
    ? `Run for ${f.formatDate(d.as_of)}, compared with the run for ${f.formatDate(d.baseline.as_of)}.`
    : `First run, for ${f.formatDate(d.as_of)}. It is the baseline for next week.`;
  const parts = [
    h("h2", { class: "section-title", text: name }),
    h("p", { class: "hint", text: when }),
    d.award_horizon ? h("p", { class: "hint", text: `Award horizon: ${f.formatDate(d.award_horizon)}.` }) : null,
  ];
  if (!d.changes.length) parts.push(h("p", { text: "Nothing changed since the last run." }));
  if (fired.length) parts.push(h("h3", { class: "mini", text: "Why Perch drafted an email" }), h("ul", { class: "changes" }, fired.map(change)));
  if (rest.length) parts.push(h("h3", { class: "mini", text: "Also changed" }), h("ul", { class: "changes" }, rest.map(change)));
  if (d.draft) {
    const text = `Subject: ${d.draft.subject}\n\n${d.draft.body}`;
    const body = h("textarea", { class: "input draft-body", rows: "14", readonly: true, "aria-label": `Email draft for ${name}` });
    body.value = text;
    parts.push(h("details", { class: "watch-draft" },
      h("summary", { text: "Email draft, not sent" }),
      h("p", { class: "hint", text: "Written by code from the records. No model wrote any of it. Perch never sends it." }),
      body,
      h("div", { class: "actions" }, h("button", { class: "btn", type: "button", onclick: () => copy(text, announce) },
        h("span", { text: "Copy the draft" })))));
  } else {
    parts.push(h("p", { class: "hint", text: "No email drafted: nothing fired." }));
  }
  parts.push(h("p", {}, h("a", { class: "btn quiet", href: `#/brief/${encodeURIComponent(d.brief_id)}/routes` },
    h("span", { text: "Open this week’s brief" }))));
  return h("li", { class: "card watch-card" }, ...parts);
}

export async function renderWatch(container, { api, announce }) {
  document.title = "What changed — Perch";
  const head = [h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Find" })),
    h("h1", { class: "who", text: "What changed" }),
    h("p", { class: "lede", text: "Each week Perch refreshes open NIH funding from Grants.gov, re-runs the brief for each watched researcher and compares it with the last run." }),
    h("p", { class: "hint", text: "It drafts an email when a public award ends within 12 months, or when an opportunity enters the top 10. Perch never sends it." })];
  fill(container, h("div", { class: "watch" }, ...head, h("p", { class: "hint", role: "status", text: "Loading…" })));
  let data;
  try {
    data = await api.watch();
  } catch (e) {
    fill(container, h("div", { class: "watch" }, ...head,
      h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: `This could not be loaded: ${e.message}` }))));
    return;
  }
  const list = data.digests || [];
  fill(container, h("div", { class: "watch" }, ...head,
    list.length ? h("ul", { class: "watch-list" }, list.map((d) => digestCard(d, announce)))
      : h("p", { class: "empty", text: data.replay ? "The weekly watch runs on the live server only." : "The weekly job has not run on this server yet." })));
}
