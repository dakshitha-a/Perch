// Help: how to use Perch (four steps with small pictures built from the app's own
// parts) and how it works (the pipeline, marking which steps are rules and which are
// models). Every claim here describes code in this repo; see docs/design/UI.md §7.

import { h, icon } from "./dom.js";
import { owl } from "./owl.js";

function bar(w) {
  return h("span", { class: "ph", style: `width:${w}%` });
}

// ----- step pictures (decorative; the step text says the same thing) -----

function picFind() {
  return h("div", { class: "pic", "aria-hidden": "true" },
    h("div", { class: "pic-field" }, h("span", { class: "pic-ph-text", text: "Name, ORCID iD or OpenAlex ID" })),
    h("div", { class: "pic-btn" }, icon("search"), h("span", { text: "Find researcher" })));
}

function picConfirm() {
  return h("div", { class: "pic", "aria-hidden": "true" },
    h("div", { class: "pic-card" },
      h("div", { class: "pic-row" }, icon("person"), bar(46), h("span", { class: "tag moss", text: "Temple University" })),
      h("div", { class: "pic-row" }, bar(30), bar(24)),
      h("div", { class: "pic-btn", text: "Build brief" })));
}

function picWatch() {
  const knots = ["done", "done", "done", "running", "pending", "pending", "pending"];
  return h("div", { class: "pic", "aria-hidden": "true" },
    h("div", { class: "pic-branch" },
      h("div", { class: "branch-line" }), h("div", { class: "branch-fill", style: "width:50%" }),
      h("div", { class: "knots" }, knots.map((s) => h("span", { class: "knot", "data-status": s }))),
      h("div", { class: "rider", style: "left:50%" }, owl("work", "owl-rider"))),
    h("p", { class: "pic-cap" }, h("b", { text: "Mapping research threads" }), h("span", { text: "Profile first, then leads" })));
}

function picLead() {
  const n = (i) => h("span", { class: "callout", text: String(i) });
  return h("div", { class: "pic pic-lead", "aria-hidden": "true" },
    h("div", { class: "pic-card" },
      h("div", { class: "pic-row between" },
        h("span", { class: "tags" }, h("span", { class: "tag", text: "NIH" }), h("span", { class: "tag", text: "R01" })),
        h("span", { class: "fit strong" }, n(1), h("span", { class: "fit-k", text: "Fit estimate" }), h("span", { text: "strong" }))),
      h("div", { class: "pic-row" }, n(2), h("span", { class: "pic-title" }, bar(92), bar(64))),
      h("div", { class: "fact close soon pic-fact" }, n(3), h("span", {}, h("b", { text: "Closes" }), h("span", { class: "rel", text: " date from the record" }))),
      h("div", { class: "pic-row" }, n(4), h("span", { class: "tag model", text: "Model text" }), bar(50)),
      h("div", { class: "pic-actions" }, n(5),
        h("span", { class: "pic-btn ghost" }, icon("keep"), h("span", { text: "Keep" })),
        h("span", { class: "pic-btn ghost" }, icon("dismiss"), h("span", { text: "Dismiss" })),
        h("span", { class: "pic-btn ghost" }, icon("evidence"), h("span", { text: "Evidence" })))));
}

// ----- sections -----

function steps() {
  const items = [
    ["Find the researcher", picFind(),
      "Type a name, an ORCID iD or an OpenAlex ID. Names are searched among Temple University authors."],
    ["Confirm it is the right person", picConfirm(),
      "Check the institution, topics and paper count. Nothing runs until you press Build brief."],
    ["Watch the brief build", picWatch(),
      "Scout moves along the branch as each step finishes. The profile is ready in seconds; cited explanations take a minute or two."],
    ["Read the routes and decide", picLead(), null],
  ];
  const legend = h("ol", { class: "callouts" },
    h("li", { text: "The fit estimate is a model’s judgment of how well the opportunity matches the papers. It is not the odds of funding." }),
    h("li", { text: "The title opens the full record, as Grants.gov lists it." }),
    h("li", { text: "Dates and amounts are copied from the record. Amber means it closes within 30 days." }),
    h("li", { text: "Text a model wrote is tagged. Open “Why it fits” to see which papers it cites." }),
    h("li", { text: "Keep what is worth a closer look, dismiss what is not. Evidence opens the record behind the lead." }));
  return h("section", { class: "help-block", "aria-labelledby": "h-use" },
    h("h2", { id: "h-use", class: "section-title", text: "How to use Perch" }),
    h("ol", { class: "how-steps" }, items.map(([title, pic, text], i) => h("li", { class: "how-step" },
      h("div", { class: "how-text" },
        h("span", { class: "step-n", "aria-hidden": "true", text: String(i + 1) }),
        h("h3", { text: title }),
        text ? h("p", { text }) : legend),
      pic))));
}

function pipeline() {
  const stages = [
    ["paper", "Read the papers", "record",
      "Perch fetches the researcher’s public papers from OpenAlex, and their public awards from NIH RePORTER and NSF."],
    ["threads", "Group them into threads", "code",
      "Papers are grouped by what they are about, with recent work counting for more."],
    ["search2", "Search open funding", "code",
      "Each thread is matched against open and forecasted opportunities from Grants.gov, by meaning and by shared words."],
    ["filter", "Drop what you cannot apply to", "rules",
      "Fixed rules read each record’s applicant types and title, and drop opportunities a university applicant is not eligible for."],
    ["rank", "Rank the rest", "model",
      "A ranking model puts the opportunities closest to the papers first."],
    ["pen", "Explain each lead", "model",
      "A language model writes what the opportunity funds and what the cited papers did, plus a fit estimate."],
    ["check", "Check every claim", "rules",
      "Code checks that each citation, date and number is in a cited record. A second model checks each statement against its source. Text that fails is rewritten once, then withheld."],
    ["person", "You decide", "you",
      "You keep or dismiss leads and open any record. Perch sends nothing."],
  ];
  const kinds = { record: "Public records", code: "Code", rules: "Fixed rules", model: "Model", you: "You" };
  return h("section", { class: "help-block", "aria-labelledby": "h-how" },
    h("h2", { id: "h-how", class: "section-title", text: "How Perch works" }),
    h("p", { class: "lede", text: "The same steps run the same way every time. Models do two bounded jobs, ranking and writing, and everything they write is checked against the records." }),
    h("p", { class: "flow-key", "aria-hidden": "true" },
      ...["record", "code", "rules", "model"].map((k) => h("span", { class: `kind ${k}`, text: kinds[k] }))),
    h("ol", { class: "flow" }, stages.map(([ic, title, kind, text]) => h("li", { class: `flow-step ${kind}` },
      h("span", { class: "flow-icon", "aria-hidden": "true" }, icon(ic)),
      h("div", {},
        h("h3", {}, h("span", { text: title }), h("span", { class: `kind ${kind}`, text: kinds[kind] })),
        h("p", { text }))))));
}

function labels() {
  const row = (sample, text) => h("li", {}, h("div", { class: "sample", "aria-hidden": "true" }, sample), h("p", { text }));
  return h("section", { class: "help-block", "aria-labelledby": "h-labels" },
    h("h2", { id: "h-labels", class: "section-title", text: "Reading the labels" }),
    h("ul", { class: "label-list" },
      row(h("span", { class: "tag model", text: "Model text" }),
        "A model wrote this. It passed the citation checks, but read it as a summary, not as the record."),
      row(h("span", { class: "inference mini-inf" }, h("span", { class: "tag model", text: "Inference" })),
        "A model’s reading of why the work fits. A judgment, never a fact."),
      row(h("span", { class: "fit strong" }, h("span", { class: "fit-k", text: "Fit estimate" }), h("span", { text: "strong" })),
        "Strong is 80 or more out of 100, good 60 to 79, partial 40 to 59, weak below 40."),
      row(h("span", { class: "missing", text: "Not stated in the record" }),
        "The source leaves this blank. Perch never fills a gap with a guess."),
      row(h("span", { class: "notice warn sample-warn" }, icon("warn"), h("span", { text: "Withheld" })),
        "An explanation or statement failed the checks, so it is withheld or flagged. The record fields still show."),
      row(h("span", { class: "big-date", text: "Award horizon" }),
        "The end date of the last public NIH or NSF award found. Perch infers nothing about lab finances.")));
}

function limits() {
  return h("section", { class: "help-block", "aria-labelledby": "h-limits" },
    h("h2", { id: "h-limits", class: "section-title", text: "What Perch does not do" }),
    h("ul", { class: "plain-list" },
      h("li", { text: "It does not send anything. Nothing leaves the app unless you copy or download it." }),
      h("li", { text: "It does not tell you to apply, or predict whether you would win. A brief is a starting point." }),
      h("li", { text: "It reads public records only: papers, public federal awards and posted opportunities." }),
      h("li", { text: "It does not yet cover foundations, industry partners or hand-offs to Temple offices. Those are being built." })));
}

function sources() {
  return h("section", { class: "help-block", "aria-labelledby": "h-src" },
    h("h2", { id: "h-src", class: "section-title", text: "Where the data comes from" }),
    h("dl", { class: "fields" },
      h("div", { class: "field" }, h("dt", { text: "Papers and authors" }), h("dd", { text: "OpenAlex" })),
      h("div", { class: "field" }, h("dt", { text: "Public awards" }), h("dd", { text: "NIH RePORTER, NSF Award Search" })),
      h("div", { class: "field" }, h("dt", { text: "Open opportunities" }), h("dd", { text: "Grants.gov" }))),
    h("p", { class: "hint", text: "Each record shows its source, a link to it, and when Perch fetched it. The Grants.gov notice is at the foot of every page." }));
}

export function renderHelp(container, { back }) {
  const hello = owl("idle", "owl-md help-owl", { button: true });
  container.replaceChildren(h("article", { class: "help" },
    h("a", { class: "back", href: back, "data-key": "help-back" }, icon("back"), h("span", { text: "Back" })),
    h("header", { class: "help-head" },
      h("div", {},
        h("h1", { class: "who", text: "Help" }),
        h("p", { class: "lede", text: "Perch reads a researcher’s public papers, finds open federal funding that fits, and shows the record behind every claim." })),
      hello),
    steps(), pipeline(), labels(), limits(), sources(),
    h("p", { class: "help-scout" }, h("span", { text: "Scout the owl moves while Perch works. Tap Scout to say hello." }))));
}
