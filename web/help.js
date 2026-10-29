// Help: how to use Perch (eight steps with small pictures built from the app's own
// parts) and how it works (the pipeline, marking which steps are rules and which are
// models). Every claim here describes code in this repo; see docs/design/UI.md §7.

import { h, icon } from "./dom.js";
import { owl } from "./owl.js";

function example(...kids) {
  return h("figure", { class: "pic", "aria-hidden": "true" },
    h("figcaption", { class: "pic-label", text: "Example" }), ...kids);
}

function bar(w) {
  return h("span", { class: "ph", style: `width:${w}%` });
}

// ----- step pictures (decorative; the step text says the same thing) -----

function picFind() {
  return example(
    h("div", { class: "pic-field" }, h("span", { class: "pic-ph-text", text: "Name, ORCID iD or OpenAlex ID" })),
    h("div", { class: "pic-btn" }, icon("search"), h("span", { text: "Find researcher" })));
}

function picConfirm() {
  return example(
    h("div", { class: "pic-card" },
      h("div", { class: "pic-row" }, icon("person"), bar(46), h("span", { class: "tag moss", text: "Temple University" })),
      h("div", { class: "pic-row" }, bar(30), bar(24)),
      h("div", { class: "pic-btn", text: "Build brief" })));
}

function picWatch() {
  const knots = ["done", "done", "done", "running", "pending", "pending", "pending"];
  return example(
    h("div", { class: "pic-branch" },
      h("div", { class: "branch-line" }), h("div", { class: "branch-fill", style: "width:50%" }),
      h("div", { class: "knots" }, knots.map((s) => h("span", { class: "knot", "data-status": s }))),
      h("div", { class: "rider", style: "left:50%" }, owl("work", "owl-rider"))),
    h("p", { class: "pic-cap" }, h("b", { text: "Mapping research threads" }), h("span", { text: "Profile first, then leads" })));
}

function picLead() {
  const n = (i) => h("span", { class: "callout", text: String(i) });
  return example(
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

function picIndustry() {
  return example(
    h("div", { class: "pic-card" },
      h("div", { class: "pic-row" }, h("span", { class: "pic-btn ghost", text: "Grants" }), h("span", { class: "pic-btn", text: "Industry" })),
      h("div", { class: "pic-row between" }, bar(46), h("span", { class: "evidence-level", text: "Two kinds of signal" })),
      h("div", { class: "pic-row" }, h("span", { class: "tag model", text: "Inference" }), bar(56)),
      h("div", { class: "pic-row" }, h("b", { text: "They cite your papers" }), bar(30))));
}

function picKeep() {
  return example(
    h("div", { class: "pic-card pic-row between" },
      h("span", {}, h("b", { text: "2 leads kept" }), bar(60)),
      h("span", { class: "pic-btn" }, h("span", { text: "Compare them" }))));
}

function picHandoff() {
  return example(
    h("div", { class: "pic-card" },
      h("div", { class: "pic-row" }, h("b", { text: "Dear Research Development team," })),
      h("div", { class: "pic-row" }, h("span", { class: "tag model", text: "Model" }), bar(70)),
      h("div", { class: "pic-row" }, bar(85)),
      h("div", { class: "pic-row" }, h("span", { class: "pic-btn", text: "Copy the draft" }),
        h("span", { class: "pic-btn", text: "Open in my mail app" }))));
}

function picScout() {
  return example(
    h("div", { class: "pic-card" },
      h("div", { class: "pic-row between" }, h("b", { text: "Search opportunities" }), h("span", { class: "tag", text: "Waiting for you" })),
      h("div", { class: "pic-row" }, h("span", { class: "chip", text: "Activity codes: R21" }), h("span", { class: "chip", text: "Closes by: 2027-03-01" })),
      h("div", { class: "pic-row" }, h("span", { class: "pic-btn", text: "Approve" }), h("span", { class: "pic-btn", text: "Skip" }))));
}

// ----- sections -----

function steps() {
  const items = [
    ["Find the researcher", picFind(),
      "Type a name, an ORCID iD or an OpenAlex ID. Names are searched among authors whose latest institution in OpenAlex is Temple University; if a name is not found, paste the ORCID iD."],
    ["Confirm it is the right person", picConfirm(),
      "Check the institution, topics and paper count. Nothing runs until you press Build brief."],
    ["Watch the brief build", picWatch(),
      "Scout moves along the branch as each step finishes. In tests on the local model, the profile was ready in about 10 seconds and a full brief with explanations took about a minute and a half."],
    ["Read the routes and decide", picLead(), null],
    ["Look at industry leads", picIndustry(),
      "Routes has two parts: Grants, and Industry. Industry lists up to five companies with at least two kinds of public signal: company authors whose papers cite yours; NIH SBIR or STTR awards to the company that match your main topics; and other company papers in your main topics. Each signal shows its count, its newest date and the records behind it. The relationship type, such as sponsored research or an STTR partner, comes from a fixed rule, not a model. Your papers with more than 30 authors are left out, because citations of large consortium papers say little about your own work. Every industry lead is an inference from public signals, not a verified interest in funding you. Small-business awards cover NIH only, because the SBIR.gov API was down when this was built."],
    ["Compare the kept leads", picKeep(),
      "Once you keep a lead, a bar at the bottom of Routes shows how many you kept, and its button opens the Compare tab. Compare puts your kept grants and industry leads in one table: money, close date, activity code, the funding instrument or the suggested relationship, and the evidence. Under each lead is the Temple office that handles its route. Each cell is copied from its record or counted from it by code, and pressing it opens that record. Press a column name to sort; cells with nothing in the record sort last. There is no effort or intellectual-property column, because no public record states either. Industry leads have no amount or deadline in their records."],
    ["Hand off to a Temple office", picHandoff(),
      "Under the table, pick an office: Research Development for grants, or Innovation and Technology Commercialization for industry leads, as research.temple.edu names them. Draft the email, and a model writes a short opening paragraph about your papers and the kept leads. Code writes the rest: the list of leads with dates and amounts copied from their records, your papers, and a note that industry leads are inferences. The opening is checked like every model text, and it may not say you should apply or that a company wants to fund you. If it fails twice, the draft opens with a plain sentence instead. The To line is left empty; a link opens the office’s page on research.temple.edu. Edit the draft, then copy it or open it in your mail app. Perch never sends it and does not save it. To take the whole brief with you, use the links at the bottom of a brief: Print or save as PDF opens the brief as a plain page, and your browser’s print dialog saves it as a PDF; Markdown downloads the same text; Records as JSON downloads every record behind it."],
    ["Tell Perch more (optional)", null,
      "Under Options on the Find screen you can add a sentence on where your research is going, keywords to search for or leave out, and a career stage. Your sentence and keywords become one more search thread with 30% of the weight; your papers share the other 70%. Left-out keywords drop any opportunity that mentions one in its title or description. Choosing early-stage investigator keeps opportunities limited to early-stage or new investigators, marked “You said”, so you can check NIH’s definition. These fields are saved with the brief, shown on its Profile as “You said”, and may be read by the configured model. They steer the search; no explanation cites them as a fact."],
    ["Use private mode", null,
      "Where the server offers it, the Private mode link on the Find screen takes a CV, a draft proposal, a research direction or unpublished work, pasted or uploaded as plain text, Markdown, Word (.docx) or PDF. It runs only when every model is on the Perch server; the page names who runs that server. What you add is held in memory for the session. It is not saved to the database, logs or caches, and Perch sends it to no outside service. Ending the session, 30 minutes idle, or a server restart drops it all. Your documents become search threads with 60% of the weight: the draft proposal takes half of that, the direction 30% and unpublished work 20%. Your public papers, if you give your OpenAlex ID, share the other 40%; without one, the brief runs on your documents alone. The CV does not steer the search. Code reads it for your doctoral degree year and any NIH awards: if the degree is within 10 years and no NIH award outside NIH’s list of smaller grants is listed, opportunities limited to early-stage investigators stay in, marked “may be eligible” for you to check. Past sponsors named on the CV move their own programmes up. Explanations may cite your documents, shown with a lock. Exports and hand-off drafts leave out text drawn from your documents, unless you choose to mask it. Masking replaces names, contact details, identifiers and phrases found only in your documents with labels such as [PERSON-1], and the key to undo it stays in the session. Masking cannot hide what your research is about."],
    ["Ask Scout a follow-up", picScout(),
      "Once a brief has finished, the Ask Scout tab takes plain questions, such as “only R21s that close by March” or “why does the top lead fit?”. Scout picks one of Perch’s own tools: a search with filters for agency, award ceiling, close date, activity code and words to include or leave out; the industry leads, with their signals and records; a record; the public awards; the research profile; a fit explanation; a comparison of chosen or kept leads; or a hand-off draft, shown in full on its card to copy. Each tool is a card. By default Scout asks before every step, and you approve or skip it; switch to “Run and show me” to let the steps run while you watch. Scout’s answer cites records, and a date or amount that is not in a cited record gets the answer rewritten once, then withheld. Scout stops after eight model calls for one question. It cannot browse the web, send anything or change a record; a hand-off draft from Scout is only text for you to copy. Conversations are not saved: a server restart ends them."],
  ];
  const legend = h("ol", { class: "callouts" },
    h("li", { text: "The fit estimate is a model’s judgment of how well the opportunity matches the papers. It is not the odds of funding." }),
    h("li", { text: "The title, like Evidence, opens the record inside Perch, with a link to Grants.gov." }),
    h("li", { text: "Dates and amounts are copied from the record. Amber means it closes within 30 days." }),
    h("li", { text: "Text a model wrote is tagged. Open “Why it fits” to see which papers it cites." }),
    h("li", { text: "Keep what is worth a closer look; dismiss what is not. Dismissed leads can be restored." }));
  return h("section", { class: "help-block", "aria-labelledby": "h-use" },
    h("h2", { id: "h-use", class: "section-title", text: "How to use Perch" }),
    h("ol", { class: "how-steps" }, items.map(([title, pic, text], i) => h("li", { class: "how-step" },
      h("div", { class: "how-text" },
        h("span", { class: "step-n", "aria-hidden": "true", text: String(i + 1) }),
        h("h3", { text: title }),
        text ? h("p", { text }) : null),
      pic, text ? null : legend))));
}

function pipeline() {
  const stages = [
    ["paper", "Read the papers", ["record"],
      "Perch fetches the researcher’s public papers from OpenAlex, and public awards from NIH RePORTER and NSF Award Search. Every record keeps its source, a link to it and when it was fetched."],
    ["threads", "Group them into threads", ["code", "model"],
      "An embedding model turns each paper into numbers that capture its meaning. Code groups the papers by topic, with recent work counting for more."],
    ["search2", "Search open funding", ["code", "model"],
      "Each thread is matched against opportunities posted on Grants.gov, by meaning and by shared words. Forecasted calls are not shown yet."],
    ["filter", "Drop what a university cannot apply to", ["rules"],
      "Rules drop anything closed, without a close date, or not open to universities. They also drop what this version leaves out: fellowships, postdoc and dissertation awards, small-business programs and limited competitions. Calls restricted by career stage are dropped too, unless you say you are an early-stage investigator or your CV in private mode suggests it."],
    ["rank", "Rank the rest", ["model"],
      "A ranking model puts the closest matches to the papers first."],
    ["search2", "Find industry leads", ["record", "code"],
      "Perch looks up company-authored papers that cite the researcher’s papers or share their main topics (OpenAlex), and NIH small-business awards in those topics (NIH RePORTER). Code counts each company’s signals, weighs recent ones more, and keeps companies with at least two kinds of signal. No model is used."],
    ["threads", "Summarise the profile", ["model"],
      "A language model writes topic labels and a two-sentence summary of the papers."],
    ["pen", "Explain each lead", ["model"],
      "A language model writes what the opportunity funds and what the cited papers did, plus a fit estimate."],
    ["check", "Check every claim", ["rules", "model"],
      "Code checks that each citation, date and number is in a cited record; text that fails is rewritten once, then withheld. A second model checks each statement against its source; one it cannot match is shown with a warning."],
    ["person", "You decide", ["you"],
      "You keep or dismiss leads, compare them and open any record."],
    ["pen", "Draft the hand-off", ["model", "code"],
      "On request, a language model writes the opening paragraph of an email to a Temple office; code writes the list of leads, dates, amounts and papers. The paragraph is checked like every other model text. You edit and send it; Perch sends no email and writes to no outside system."],
  ];
  const kinds = { record: "Public records", code: "Code", rules: "Rules", model: "Model", you: "You" };
  return h("section", { class: "help-block", "aria-labelledby": "h-how" },
    h("h2", { id: "h-how", class: "section-title", text: "How Perch works" }),
    h("p", { class: "lede", text: "The steps run the same way every time. Models turn text into numbers, rank and write; a separate model checks the writing; rules and code do the rest." }),
    h("ol", { class: "flow" }, stages.map(([ic, title, ks, text]) => h("li", { class: `flow-step ${ks[ks.length - 1]}` },
      h("span", { class: "flow-icon", "aria-hidden": "true" }, icon(ic)),
      h("div", {},
        h("h3", { text: title }),
        h("p", { class: "kinds" }, h("span", { class: "sr-only", text: "Done by: " }),
          ks.map((k, n) => [n ? h("span", { class: "sr-only", text: " and " }) : null,
            h("span", { class: `kind ${k}`, text: kinds[k] })])),
        h("p", { text }))))));
}

// The big picture of how a lead's place in the list is decided. Numbers are the constants
// in perch/profile.py, perch/retrieve.py, perch/brief.py, perch/private/ and perch/service.py.
function scoring() {
  const steps = [
    ["Threads", "Each paper counts for half as much every 5 years since it came out. Papers that are about the same thing form a thread: one to four in all, and one when there are fewer than 8 papers. A thread’s weight is its share of that recency-weighted work."],
    ["Search", "For each thread, Perch takes the 100 closest opportunities by meaning and the 100 best by shared words. The two lists are merged by rank, and each thread’s results count in proportion to its weight. The top 200 go on."],
    ["Rules", "Anything a university cannot apply to, or that is closed, is removed. Rules never score; they only remove."],
    ["Rank", "The best 50 left are scored by a ranking model, each against the thread it matched best, from 0 to 1. The top 10 by that score are the leads, in that order. This is the “Best match” order."],
    ["Fit estimate", "A language model then gives each lead a fit estimate from 0 to 100. It is shown, and you can sort by it, but it does not change the default order."],
    ["What you add", "A sentence or keywords you give on Find are one more thread with 30% of the weight. Private documents are threads with 60% (all of it when there are no public papers): proposal half, direction 30%, unpublished work 20%. A past sponsor on your CV adds 0.05 to its programmes’ ranking score when the leads are put in order. These shares are starting values, not measured ones."],
    ["Industry", "Industry leads are not scored by a model. Code counts each company’s signals, weighs recent ones more, and keeps up to five companies with at least two kinds of signal."],
  ];
  return h("section", { class: "help-block", "aria-labelledby": "h-score" },
    h("h2", { id: "h-score", class: "section-title", text: "How leads are ordered" }),
    h("p", { class: "lede", text: "The big picture: your papers decide what to look for, the search finds candidates, rules remove what does not apply, and a ranking model orders the rest." }),
    h("ol", { class: "plain-list score-steps" }, steps.map(([k, t]) => h("li", {}, h("b", { text: `${k}. ` }), h("span", { text: t })))));
}

function labels() {
  const row = (sample, text) => h("li", {}, h("div", { class: "sample", "aria-hidden": "true" }, sample), h("p", { text }));
  return h("section", { class: "help-block", "aria-labelledby": "h-labels" },
    h("h2", { id: "h-labels", class: "section-title", text: "Reading the labels" }),
    h("ul", { class: "label-list" },
      row(h("span", { class: "inference mini-inf" }, h("span", { class: "tag model", text: "Inference" })),
        "A model’s reading of why the work fits. A judgment, not a fact."),
      row(h("span", { class: "fit strong" }, h("span", { class: "fit-k", text: "Fit estimate" }), h("span", { text: "strong" })),
        "Strong is 80 or more out of 100, good 60 to 79, partial 40 to 59, weak below 40."),
      row(h("span", { class: "missing", text: "Not stated in the record" }),
        "The source leaves this blank. Perch never fills a gap with a guess."),
      row(h("span", { class: "notice warn sample-warn" }, icon("warn"), h("span", { text: "Withheld" })),
        "An explanation failed the citation check twice and is withheld, or a statement could not be matched to its source and is flagged. The record fields still show."),
      row(h("span", { class: "tag lock" }, icon("lock"), h("span", { text: "From your private document" })),
        "Private mode only. The text cites a document you added in this session. It never leaves Perch unless you mask it."),
      row(h("span", { class: "big-date", text: "Award horizon" }),
        "The end date of the last public NIH or NSF award found. Perch infers nothing about lab finances.")));
}

function limits() {
  return h("section", { class: "help-block", "aria-labelledby": "h-limits" },
    h("h2", { id: "h-limits", class: "section-title", text: "What Perch does not do" }),
    h("ul", { class: "plain-list" },
      h("li", { text: "It sends no email and writes to no outside system." }),
      h("li", { text: "It does not confirm your personal eligibility, such as career stage, citizenship or internal limited-submission rules. When it keeps a call limited by career stage, it marks it for you to check. Read each record." }),
      h("li", { text: "It does not tell you to apply, or predict whether you would win. A brief is a starting point." }),
      h("li", { text: "It covers federal opportunities posted on Grants.gov, and industry leads from public papers and NIH small-business awards. Foundations are not covered yet." }),
      h("li", { text: "It does not know whether a company wants to fund research. Industry leads are inferences from public signals." }),
      h("li", { text: "It reads public records only: papers, public federal awards and posted opportunities." }),
      h("li", { text: "It keeps your list of recent briefs only in this browser. Clear history on the Find screen forgets the list; the briefs themselves stay on the server, and anyone with a brief’s link can open it." })));
}

export function renderHelp(container, { back }) {
  const hello = owl("idle", "owl-md help-owl", { button: true });
  container.replaceChildren(h("article", { class: "help" },
    h("a", { class: "back", href: back, "data-key": "help-back", onclick: (e) => {
      if (back !== "#/" && history.length > 1) { e.preventDefault(); history.back(); }
    } }, icon("back"), h("span", { text: "Back" })),
    h("header", { class: "help-head" },
      h("div", {},
        h("h1", { class: "who", text: "Help" }),
        h("p", { class: "lede", text: "Perch reads a researcher’s public papers, finds open federal funding that fits, and shows the record behind every claim." })),
      hello),
    steps(), pipeline(), scoring(), labels(), limits(),
    h("p", { class: "help-scout" }, h("span", { text: "Scout the owl moves while Perch works. Tap Scout to say hello." }))));
}
