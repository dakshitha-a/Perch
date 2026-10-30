// Help: how to use Perch (numbered steps, some with small pictures built from the app's own
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
    h("div", { class: "pic-btn" }, icon("search"), h("span", { text: "Find" })));
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
        h("span", { class: "fit strong" }, n(1), h("span", { class: "fit-k", text: "Match" }), h("span", { text: "strong" }))),
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
      "Choose Researcher on the first screen, then type a name, an ORCID iD or an OpenAlex ID. Names are searched among authors whose latest institution in OpenAlex is Temple University; if a name is not found, paste the ORCID iD."],
    ["Confirm it is the right person", picConfirm(),
      "Check the institution, topics and paper count, then press This is the one. Nothing runs until you press Build brief. Back to the matches undoes the pick."],
    ["Watch the brief build", picWatch(),
      "The brief opens on Routes. A card at the top names the step, counts the steps and fills a bar as each one finishes; grant cards shimmer until the leads arrive. In tests on the demo models a brief with explanations took 46 to 49 seconds. The demo researchers’ default briefs are built when the server starts and held in its memory, so they open at once; each visitor gets their own copy, and nothing about the visitor is stored."],
    ["Read the routes and decide", picLead(), null],
    ["Look at industry leads", picIndustry(),
      "Routes has two parts: Grants, and Industry. Industry lists up to five companies with at least two kinds of public signal: company authors whose papers cite yours; NIH SBIR or STTR awards to the company that match your main topics; and other company papers in your main topics. Each signal shows its count, its newest date and the records behind it. The relationship type, such as sponsored research or an STTR partner, comes from a fixed rule, not a model. Your papers with more than 30 authors are left out, because citations of large consortium papers say little about your own work. Every industry lead is an inference from public signals, not a verified interest in funding you. Small-business awards cover NIH only, because the SBIR.gov API was down when this was built."],
    ["Compare the kept leads", picKeep(),
      "Once you keep a lead, it joins Your shortlist beside the list, where × takes it off again; on a phone, a bar at the bottom shows how many you kept. Compare and hand off opens the Compare tab. Compare puts your kept grants and industry leads in one table: money, close date, activity code, the funding instrument or the suggested relationship, and the evidence. Under each lead is the Temple office that handles its route. Each cell is copied from its record or counted from it by code, and pressing it opens that record. Press a column name to sort; cells with nothing in the record sort last. There is no effort or intellectual-property column, because no public record states either. Industry leads have no amount or deadline in their records."],
    ["Hand off to a Temple office", picHandoff(),
      "Under the table, pick an office: Research Development for grants, or Innovation and Technology Commercialization for industry leads, as research.temple.edu names them. Draft the email, and a model writes a short opening paragraph about your papers and the kept leads. Code writes the rest: the list of leads with dates and amounts copied from their records, your papers, and a note that industry leads are inferences. The opening is checked like every model text, and it may not say you should apply or that a company wants to fund you. If it fails twice, the draft opens with a plain sentence instead. The To line is left empty; a link opens the office’s page on research.temple.edu. Edit the draft, then copy it or open it in your mail app. Perch never sends it and does not save it. To take the whole brief with you, press Export at the top of a brief: Print or save as PDF opens the brief as a plain page, and your browser’s print dialog saves it as a PDF; Markdown downloads the same text; Records as JSON downloads every record behind it."],
    ["Tell Perch more (optional)", null,
      "After you pick the person, Tell Perch more (optional) takes a sentence on where your research is going, keywords to search for or leave out, a career stage and a smallest award ceiling, as well as your CV and a draft proposal (see Add your documents). Fill with a sample puts in invented SYNTHETIC text, marked Sample data, so you can see what helps; it leaves the CV empty, and a brief built from it carries a Sample data banner. Your sentence and keywords become one more search thread with 30% of the weight; your papers share the other 70%. Left-out keywords drop any opportunity that mentions one in its title or description. Choosing early-stage investigator keeps opportunities limited to early-stage or new investigators, marked “You said”, so you can check NIH’s definition. These fields are held with the brief in your session’s memory, shown on its Profile as “You said”, and read by the models: local ones, or the cloud provider when Cloud is on. They steer the search; no explanation cites them as a fact."],
    ["Nothing about you is stored", null,
      "Every brief runs in a session held in the server’s memory. Perch saves no brief, no lead, no list of what you looked up and no log of your session, and it keeps no history in your browser. Running the same researcher again builds a fresh brief. Ending the session with End session at the top, 30 minutes idle, or a server restart drops everything in it. Public records Perch fetches, such as a researcher’s papers and awards, stay cached on the server, because they are public and hold nothing about you. The chip at the top says this on every screen."],
    ["Local or Cloud models", null,
      "The chip at the top, “Local · nothing stored”, opens a choice of the models that write the summary, the fit explanations and the hand-off opening. Local is the default: every model runs on the Perch server. Where the server offers it, Cloud uses a cloud model instead. Before Cloud turns on, a warning names the company and says what goes to it: what you type, such as the researcher you look up and any direction or keywords, and the text of the public papers and listings in your brief. You confirm in that dialog, and the chip and the edge of the page turn amber while Cloud is on. Search, ranking, the citation checks and Scout always stay local. On this server, documents never go to the cloud: Cloud cannot turn on while a session holds documents, and adding documents turns Cloud off first. Cloud lasts for the session and the server caps cloud briefs per day."],
    ["Add your documents", null,
      "After you pick the person, the boxes for your CV and your ongoing research or draft proposal take pasted text or a file. For a brief with no public papers, More options on the first screen links to Your documents, which also takes a research direction or unpublished work. If you paste long or CV-like text into the search box, a check that runs only in your browser offers to add it as a document instead; nothing is sent until you choose. Documents are pasted or uploaded as plain text, Markdown, Word (.docx) or PDF. Documents are read only by models on the Perch server, never by a cloud model; the page names who runs that server. What you add is held in memory for the session. It is not saved to the database, logs or caches, and Perch sends it to no outside service. Ending the session, 30 minutes idle, or a server restart drops it all; if the session ends while you are away, Perch goes back to the start and says so. Your documents become search threads with 60% of the weight: the draft proposal takes half of that, the direction 30% and unpublished work 20%. Your public papers, if you give your OpenAlex ID, share the other 40%; without one, the brief runs on your documents alone. The CV does not steer the search. Code reads it for your doctoral degree year and any NIH awards: if the degree is within 10 years and no NIH award outside NIH’s list of smaller grants is listed, opportunities limited to early-stage investigators stay in, marked “may be eligible” for you to check. Past sponsors named on the CV move their own programmes up. Explanations may cite your documents, shown with a lock. Exports and hand-off drafts leave out text drawn from your documents, unless you choose to mask it. Masking replaces names, contact details, identifiers and phrases found only in your documents with labels such as [PERSON-1], and the key to undo it stays in the session. Masking cannot hide what your research is about."],
    ["Use student mode", null,
      "Choose Student on the first screen, then Start with your CV or résumé. Student mode always runs on local models, because a CV is personal, so choosing it turns Cloud off for the session. Paste or upload your CV or résumé, and add a note on your interests or up to five achievements. Fill with a sample puts in an invented SYNTHETIC student, marked Sample data. Code reads the CV by rule, never with a model: level of study, year, major, GPA, full-time or part-time, expected graduation and how many referees you list. Your interests note steers the search; your achievements are records an explanation may cite. The brief has four tabs: Your options lists the leads, What Perch read shows what the rules read from your CV, Compare holds the ones you keep, and Ask Scout answers questions about them. Your options has two lists. Fellowships (public) lists awards from Temple’s Scholar Development and Fellowships Advising list and NIH fellowships for graduate students. Those listings name who may apply, but their own pages set the full rules, so the best verdict there is “may be eligible”. When a listing states no deadline or amount, the card says so in one line. Scholarships and awards (sample) lists invented records from a test corpus, marked Sample data on the tab and on every card; they show how the mode would work with a real scholarship feed, and they are not real. Each option is checked against your CV, and its chip shows a mark and a word: ✓ Eligible, ? May be eligible or ✕ Not eligible. “not eligible” names the first rule it breaks, “may be eligible” says what your CV does not show, and a residency, citizenship or other personal criterion is quoted for you to judge; Perch never asks for it. “Still needed” lists what the record asks for that your CV does not show. Compare puts your kept options in a table. Under it, pick Scholar Development and Fellowships Advising for fellowships or Student Financial Services for scholarships, and Draft the note. Code writes these drafts, the To line is yours to fill, and Perch sends nothing. “Back to your documents” at the top of the brief goes back to the form without ending the session."],
    ["Ask Scout a follow-up", picScout(),
      "Once a brief has finished, the Ask Scout tab takes plain questions, such as “only R21s that close by March” or “why does the top lead fit?”. Scout picks one of Perch’s own tools: a search with filters for agency, award ceiling, close date, activity code and words to include or leave out; the industry leads, with their signals and records; a record; the public awards; the research profile; a fit explanation; a comparison of chosen or kept leads; or a hand-off draft, shown in full on its card to copy. Each tool is a card. By default Scout asks before each step, and you approve or skip it; switch to “Run and show me” to let the steps run while you watch. Scout’s answer cites records, and a date or amount that is not in a cited record gets the answer rewritten once, then withheld. Scout stops after eight model calls for one question. It cannot browse the web, send anything or change a record; a hand-off draft from Scout is only text for you to copy. Scout always runs on a local model. On a student brief Scout has its own tools: search your options with filters, check one against your CV by rule, explain a verdict, what Perch read from your CV, compare kept options, and a note to a Temple office, written by code. It never reads your CV text, and sample records stay marked. Conversations are not saved: they end with the session."],
  ];
  const legend = h("ol", { class: "callouts" },
    h("li", { text: "Match is how closely the listing’s text matches the papers, from 0 to 100. Leads are sorted by it, highest first; Closing date sorts them by deadline instead. It is not the odds of funding." }),
    h("li", { text: "The title, like Evidence, opens the record inside Perch, with a link to Grants.gov." }),
    h("li", { text: "Dates and amounts are copied from the record. Amber means it closes within 30 days. When a close date is more than ten years away, the card shows the record’s own words on the deadline instead, such as “Proposals accepted anytime”: NSF gives such programs a close date decades out. The record view always shows those words." }),
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
      "Each thread is matched against opportunities posted on Grants.gov by every federal agency, such as NIH, NSF, the Department of Defense and the Department of Energy, by meaning and by shared words. The search uses the thread's paper titles, its main words and the topic names OpenAlex gives its papers. Forecasted calls are not shown yet."],
    ["filter", "Drop what a university cannot apply to", ["rules"],
      "Rules drop anything closed, without a close date, or not open to universities. They also drop what this version leaves out: fellowships, postdoc and dissertation awards, small-business programs and limited competitions. Programs for primarily undergraduate institutions are dropped, because Temple is a doctoral university, and so are EPSCoR programs, which are open only in listed states that do not include Pennsylvania. When a record says only “Others” may apply, it counts as open to universities if its eligibility text names them. Calls restricted by career stage, such as early-career, young investigator or young faculty awards, are dropped too, unless you say you are an early-stage investigator or a CV you add suggests it."],
    ["rank", "Rank the rest", ["model"],
      "A ranking model reads the 100 best matches against the research thread they fit and puts the closest first. Its score, on a scale from 0 to 100, is the Match on each card."],
    ["search2", "Find industry leads", ["record", "code"],
      "Perch looks up company-authored papers that cite the researcher’s papers or share their main topics (OpenAlex), and NIH small-business awards in those topics (NIH RePORTER). Code counts each company’s signals, weighs recent ones more, and keeps companies with at least two kinds of signal. No model is used."],
    ["threads", "Summarise the profile", ["model"],
      "A language model writes topic labels and a two-sentence summary of the papers."],
    ["pen", "Explain each lead", ["model"],
      "A language model writes what the opportunity funds and what the cited papers did. It does not change the order."],
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
    ["Rank", "The best 100 left are scored by a ranking model, each against the thread it matched best. The 10 with the highest score are the leads, highest first: the default “Score” order on Routes."],
    ["Match", "The ranking model’s score, put on a scale from 0 to 100 by a fixed formula: strong is 80 or more, good 60 to 79, partial 40 to 59, weak below 40. It is the only score Perch shows, and the list is sorted by it. The scale was set on the NIH back-test: every funded announcement Perch placed in the top 10 scored 80 or more. It measures how closely the listing’s text matches the papers, so a short, general listing, such as many NSF programmes, can score lower than its real fit. It is not the odds of funding. Code computes it; no model writes it. Student options get the same score, against your interests and CV."],
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
      row(h("span", { class: "fit strong" }, h("span", { class: "fit-k", text: "Match" }), h("span", { text: "strong" })),
        "How closely the listing’s text matches the papers. Strong is 80 or more out of 100, good 60 to 79, partial 40 to 59, weak below 40."),
      row(h("span", { class: "missing", text: "Not stated in the record" }),
        "The source leaves this blank. Perch never fills a gap with a guess."),
      row(h("span", { class: "notice warn sample-warn" }, icon("warn"), h("span", { text: "Withheld" })),
        "An explanation failed the citation check twice and is withheld, or a statement could not be matched to its source and is flagged. The record fields still show."),
      row(h("span", { class: "tag lock" }, icon("lock"), h("span", { text: "From your private document" })),
        "Only on a brief with your documents. The text cites a document you added in this session. It never leaves Perch unless you mask it."),
      row(h("span", { class: "big-date", text: "Award horizon" }),
        "The end date of the last public NIH or NSF award found. Perch infers nothing about lab finances. Awards are found by name. When the full name finds none, Perch searches by last name at Temple and keeps awards whose first initial matches; those are marked “Matched by initial”, so check that each is yours.")));
}

function limits() {
  return h("section", { class: "help-block", "aria-labelledby": "h-limits" },
    h("h2", { id: "h-limits", class: "section-title", text: "What Perch does not do" }),
    h("ul", { class: "plain-list" },
      h("li", { text: "It sends no email and writes to no outside system. Hand-offs are drafts for you to copy." }),
      h("li", { text: "It does not confirm your personal eligibility, such as career stage, citizenship or internal limited-submission rules. When it keeps a call limited by career stage, it marks it for you to check. Read each record." }),
      h("li", { text: "It does not tell you to apply, or predict whether you would win. A brief is a starting point." }),
      h("li", { text: "It covers federal opportunities posted on Grants.gov, and industry leads from public papers and NIH small-business awards. Foundations are not covered yet." }),
      h("li", { text: "It does not know whether a company wants to fund research. Industry leads are inferences from public signals." }),
      h("li", { text: "It reads public records only: papers, public federal awards and posted opportunities." }),
      h("li", { text: "It keeps nothing about you, so it cannot watch for changes or show you a brief again later. Save an export if you want to keep one." })));
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
        h("p", { class: "lede", text: "Perch reads a researcher’s public papers, or a student’s CV, finds funding that fits, and shows the record behind every claim." })),
      hello),
    // Jump links (S25 review): the page is long, so each section is one press away.
    h("nav", { class: "help-jump", "aria-label": "Jump to" }, h("span", { class: "hint", text: "Jump to:" }),
      [["h-use", "How to use Perch"], ["h-how", "How it works"], ["h-score", "How leads are ordered"],
        ["h-labels", "Reading the labels"], ["h-limits", "What Perch does not do"]].map(([id, text]) =>
        h("button", { class: "btn quiet", type: "button", onclick: () => {
          const t = document.getElementById(id); t.setAttribute("tabindex", "-1"); t.scrollIntoView({ block: "start" }); t.focus({ preventScroll: true });
        } }, h("span", { text })))),
    steps(), pipeline(), scoring(), labels(), limits(),
    h("p", { class: "help-scout" }, h("span", { text: "Scout the owl moves while Perch works. Tap Scout to say hello." }))));
}
