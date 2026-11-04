// The public lists (S43): Temple awards for students (#/awards), funding for researchers
// (#/funding) and the sample records on their own screen (#/samples/student). One list
// module serves both sides; only the card's fields differ. Nothing here needs a session.
//
// Rules kept here:
//   3: an amount, a deadline or a date is rendered from the record's own field; a field the
//      record does not state reads "not stated".
//   4: every card shows its source and links to the record's source_url.
//  11: samples come only from GET /samples, never from the two public lists, and every
//      sample card carries the "Sample data" badge.
// Counts on the school tags come from GET /filters, never from anywhere else.

import { evMark, fill, h, icon } from "./dom.js";
import * as f from "./format.js";

const SOURCE_WORDS = { temple_pages: "Temple public page", temple_sdfa: "Temple Scholar Development and Fellowships Advising list",
  grants_gov: "Grants.gov", nih_reporter: "NIH RePORTER", nsf: "NSF Award Search", synthetic: "SYNTHETIC sample corpus (invented)" };
const LEVEL_WORDS = { undergraduate: "Undergraduate", graduate: "Graduate", faculty: "Faculty", mixed: "Several levels" };
const NOT_STATED = "not stated";
const SAMPLE_NOTE = "These are invented records from a test corpus. They show how Perch works; they are not real awards. Do not apply to them.";

// The levels come from the server; a value this file has no word for shows as the server gave it.
const levelWord = (v) => LEVEL_WORDS[v] || String(v).replace(/(^|[\s,/])(\p{L})/gu, (m, a, b) => a + b.toUpperCase());

// What each side's list remembers while the visitor stays in the app.
const L = {
  student: { temple: true, school: null, allTemple: false, level: "", q: "" },
  researcher: { temple: false, school: null, allTemple: false, level: "", q: "" },
};

// ---------- the card ----------

const firstQuote = (r) => {
  const q = (r.field_quotes || {}).eligibility;
  return q ? q.split(" | ")[0].trim() : null;
};

function amountText(r) {
  if (r.kind === "opportunity") {
    if (r.award_floor != null && r.award_floor === r.award_ceiling) return f.money(r.award_ceiling);
    return f.awardSize({ award_floor: r.award_floor, award_ceiling: r.award_ceiling }) || NOT_STATED;
  }
  if (r.amount_min != null && r.amount_max != null && r.amount_min !== r.amount_max) return `${f.money(r.amount_min)} to ${f.money(r.amount_max)}`;
  if (r.amount_max != null) return r.amount_min == null ? `Up to ${f.money(r.amount_max)}` : f.money(r.amount_max);
  return NOT_STATED;
}

// DRAFT copy: "Closed" is written by code when the record's own date, with its year, is before
// today. A record with no full date gets no marker; nothing is inferred (S43 S4, rule 3).
function isPast(r) {
  const d = r.kind === "opportunity" ? r.close_date : r.deadline;
  if (!/^\d{4}-\d{2}-\d{2}/.test(String(d || ""))) return false;
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  return String(d).slice(0, 10) < today;
}

function deadlineText(r) {
  if (r.kind === "opportunity") {
    if (r.close_date_note && f.standardDates(r)) return r.close_date_note;
    if (!r.close_date) return r.close_date_note || NOT_STATED;
    return `${f.expiresOnly(r) ? "Expires " : ""}${f.formatDate(r.close_date)}`;
  }
  return r.deadline ? f.formatDate(r.deadline) : NOT_STATED;
}

// The scope line says honestly what the page does and does not say (fork F2).
function scopeLine(r) {
  if (r.scope === "school") return "Open to one school";
  if (r.scope === "temple_wide") return "Open across Temple";
  if (r.scope_not_stated) return "Scope not stated on the page";
  return null;
}

export function recordCard(r, { openEvidence }) {
  const opp = r.kind === "opportunity";
  const name = opp ? r.title : r.name;
  const quote = firstQuote(r);
  const scope = scopeLine(r);
  const amount = amountText(r), due = deadlineText(r);
  const tid = `t-${String(r.id).replace(/[^A-Za-z0-9_-]/g, "_")}`;
  return h("li", { class: `card lead award${r.sample ? " is-sample" : ""}`, "data-id": r.id, "data-sample": r.sample ? "true" : null },
    h("div", { class: "lead-head" }, h("span", { class: "tags" },
      r.sample ? h("span", { class: "tag sample", text: "Sample data" }) : null,
      ...[...new Set(r.schools || [])].map((s) => h("span", { class: "tag moss", text: s })),
      opp && r.agency && !(r.schools || []).includes(f.agencyShort(r.agency, r.parent_agency)) && !(r.schools || []).includes(r.agency)
        ? h("span", { class: "tag", text: f.agencyShort(r.agency, r.parent_agency) }) : null,
      ...(r.levels ? [r.levels] : []).flat().map((v) => h("span", { class: "tag", text: levelWord(v) })),
      scope && !opp ? h("span", { class: "tag", text: scope }) : null,
      r.temple_funded === true ? h("span", { class: "tag ember", text: "Temple-funded" }) : null)),
    h("h3", { class: "lead-title" }, h("button", { class: "title-btn", id: tid, type: "button",
      onclick: (e) => openEvidence(r, e.currentTarget) }, h("span", { text: name || r.id }), evMark())),
    // A Temple page has no opportunity number; its record id is not one, so it is not shown.
    r.sponsor || (opp && r.source === "grants_gov") ? h("p", { class: "opp-num", text: opp ? (r.opportunity_number || "") : r.sponsor }) : null,
    quote ? h("blockquote", { class: "quote", text: `“${quote}”` }) : null,
    h("dl", { class: "facts" },
      h("div", { class: "fact" }, h("dt", { text: "Amount" }), h("dd", {}, h("span", { class: amount === NOT_STATED ? "missing" : null, text: amount === NOT_STATED ? "Not stated" : amount }))),
      h("div", { class: "fact" }, h("dt", { text: opp ? "Closes" : "Deadline" }), h("dd", {}, h("span", { class: due === NOT_STATED ? "missing" : null, text: due === NOT_STATED ? "Not stated" : due }),
        isPast(r) ? h("span", { class: "tag closed", text: "Closed" }) : null))),
    h("div", { class: "acts" },
      h("span", { class: "src-line", text: `Source: ${SOURCE_WORDS[r.source] || r.source}` }),
      f.safeUrl(r.source_url) ? h("a", { class: "btn", href: f.safeUrl(r.source_url), target: "_blank", rel: "noopener", "aria-describedby": tid },
        icon("external"), h("span", { text: "Open at source" })) : null));
}

// ---------- the list screens ----------

const labelOf = (aud) => (aud === "student" ? { noun: "awards", title: "Temple awards" } : { noun: "opportunities", title: "Research funding" });

function params(aud, st, filters, extra = {}) {
  const showToggle = aud === "researcher" || filters.total !== filters.temple_total;
  const temple = showToggle ? st.temple : true;
  const tags = temple || aud === "student";
  return {
    temple_only: temple, school: tags && st.school ? st.school : null,
    scope: tags && st.allTemple && !st.school ? "temple_wide,unstated" : null,
    level: st.level || null, q: st.q.trim() || null, limit: 25, ...extra,
  };
}

export async function renderList(root, ctx) {
  const { api, announce } = ctx;
  const aud = ctx.audience;
  const kind = aud === "student" ? "awards" : "opportunities";
  const st = L[aud], word = labelOf(aud);
  document.title = `${word.title} — Perch`;
  let filters = null, results = null, error = null, busy = true, gen = 0;
  const groupsEl = h("div", { class: "groups", "aria-busy": "true" });
  const barEl = h("div", { class: "filter-bar" });
  const countEl = h("span", { class: "list-count", "aria-hidden": "true" });
  const showToggle = () => filters && (aud === "researcher" || filters.total !== filters.temple_total);
  const total = () => (results ? results.reduce((n, g) => n + g.total, 0) : 0);

  const keep = (fn) => {  // redraw and put focus back on the control that had it
    const a = document.activeElement;
    const key = a && a.dataset ? a.dataset.key : null;
    fn();
    if (key) { const t = root.querySelector(`[data-key="${CSS.escape(key)}"]`); if (t && t !== document.activeElement) t.focus({ preventScroll: true }); }
  };

  async function load() {
    const mine = ++gen;
    busy = true; error = null;
    drawResults();
    try {
      const data = await api.list(kind, params(aud, st, filters));
      if (mine !== gen) return;
      results = data.groups;
    } catch (e) {
      if (mine !== gen) return;
      error = e;
      results = null;
    }
    busy = false;
    keep(drawResults);
    if (!error) announce(`${total()} ${word.noun} match.`);
  }

  function clearAll() {
    Object.assign(st, { temple: aud === "student", school: null, allTemple: false, level: "", q: "" });
    keep(drawBar);
    load();
  }

  async function more(g) {
    const btn = groupsEl.querySelector(`[data-key="more-${g.key}"]`);
    if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
    try {
      const data = await api.list(kind, params(aud, st, filters, { group: g.key === "all" ? null : g.key, cursor: g.next_cursor }));
      const next = data.groups.find((x) => x.key === g.key) || data.groups[0];
      g.items.push(...next.items);
      g.next_cursor = next.next_cursor;
      keep(drawResults);
      announce(`${next.items.length} more shown.`);
    } catch (e) {
      error = e;
      keep(drawResults);
    }
  }

  function drawResults() {
    groupsEl.setAttribute("aria-busy", String(busy));
    countEl.textContent = results && !busy ? `${total()} ${total() === 1 ? "match" : "matches"}` : "";
    if (busy && !results) { fill(groupsEl, h("div", { class: "shimmer-card" }), h("div", { class: "shimmer-card" }), h("div", { class: "shimmer-card" })); return; }
    if (error) {
      fill(groupsEl, h("div", { class: "notice error", role: "alert" }, icon("warn"),
        h("div", {}, h("p", { text: "Perch could not load the list. Try again." }),
          h("button", { class: "btn", type: "button", "data-key": "retry", onclick: () => (filters ? load() : start()) }, h("span", { text: "Retry" })))));
      return;
    }
    if (!results || !total()) {
      fill(groupsEl, h("div", { class: "empty-list" }, h("p", { class: "lede", text: `No ${word.noun} match these filters.` }),
        h("button", { class: "btn", type: "button", "data-key": "clear", onclick: clearAll }, h("span", { text: "Clear filters" }))));
      return;
    }
    fill(groupsEl, results.map((g) => h("section", { class: "group", "aria-labelledby": `g-${g.key}` },
      g.label ? h("h2", { class: "section-title group-title", id: `g-${g.key}`, text: `${g.label} (${g.total})` })
        : h("h2", { class: "sr-only", id: `g-${g.key}`, text: word.title }),
      g.items.length ? h("ul", { class: "leads", "aria-labelledby": `g-${g.key}` }, g.items.map((r) => recordCard(r, ctx)))
        : h("p", { class: "hint", text: `No ${word.noun} in this group.` }),
      g.next_cursor ? h("button", { class: "btn more", type: "button", "data-key": `more-${g.key}`, onclick: () => more(g) },
        h("span", { text: "Show more" })) : null)));
  }

  function chip(key, label, count, on, pick) {
    return h("button", { type: "button", role: "radio", class: "tag-chip", "data-key": `tag-${key}`, "aria-checked": String(on),
      tabindex: on ? "0" : "-1", onclick: pick, onfocus: (e) => e.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" }) },
    h("span", { text: label }), count != null ? h("span", { class: "n", text: String(count) }) : null);
  }

  function drawBar() {
    const temple = showToggle() ? st.temple : true;
    const tagsOn = aud === "student" || temple;
    const sel = st.school ? `s:${st.school}` : st.allTemple ? "t" : "a";
    const opts = [["a", "All", null, () => { st.school = null; st.allTemple = false; }],
      ["t", "Open across Temple", null, () => { st.school = null; st.allTemple = true; }],
      ...((filters && filters.schools) || []).map((s) => [`s:${s.name}`, s.name, s.count, () => { st.school = s.name; st.allTemple = false; }])];
    const pick = (o) => { o[3](); keep(drawBar); load(); };
    const tagRow = h("div", { class: "tag-row", role: "radiogroup", "aria-label": "School",
      onkeydown: (e) => {
        if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
        e.preventDefault();
        const i = opts.findIndex((o) => o[0] === sel);
        const j = (i + (e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : opts.length - 1)) % opts.length;
        pick(opts[j]);
        const t = root.querySelector(`[data-key="tag-${opts[j][0]}"]`); if (t) t.focus();
      } }, opts.map((o) => chip(o[0], o[1], o[2], o[0] === sel, () => pick(o))));
    fill(barEl,
      h("div", { class: "filter-row" },
        showToggle() ? h("button", { type: "button", role: "switch", class: "switch", "data-key": "temple", "aria-checked": String(st.temple),
          onclick: () => { st.temple = !st.temple; keep(drawBar); load(); } },
        h("span", { class: "knob", "aria-hidden": "true" }), h("span", { text: "Temple only" })) : null,
        h("form", { class: "searchbox small", role: "search", onsubmit: (e) => { e.preventDefault(); st.q = e.currentTarget.q.value; load(); } },
          h("label", { for: "list-q", class: "sr-only", text: `Search the ${word.noun}` }),
          h("input", { id: "list-q", name: "q", type: "search", value: st.q, placeholder: `Search ${word.noun}`, autocomplete: "off",
            oninput: (e) => { st.q = e.target.value; clearTimeout(drawBar.t); drawBar.t = setTimeout(load, 400); } }),
          h("button", { class: "btn", type: "submit", text: "Search" })),
        h("div", { class: "level-pick" },
          h("label", { for: "list-level", class: "sr-only", text: "Level" }),
          h("select", { id: "list-level", "data-key": "level", onchange: (e) => { st.level = e.target.value; load(); } },
            h("option", { value: "", text: "Any level" }),
            ...((filters && filters.levels) || []).map((v) => h("option", { value: v, selected: st.level === v, text: levelWord(v) }))))),
      tagsOn ? tagRow : h("p", { class: "hint", text: "Turn on Temple only to choose a school." }));
  }

  const page = h("div", { class: "screen list-screen" },
    h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
    h("div", { class: "title-row" },
      h("div", {}, h("h1", { class: "page", id: "list-title", tabindex: "-1", text: word.title }), countEl)),
    barEl, groupsEl,
    h("p", { class: "samples-link" }, h("a", { href: `#/samples/${aud}`, text: "See how Perch works with sample records" })));
  fill(root, page);
  drawResults();
  // The whole start: filters, then the bar, then the list. Retry after a failed /filters
  // runs it again, so the bar comes back too (S43 M7).
  async function start() {
    busy = true; error = null;
    drawResults();
    try {
      filters = await api.filters(aud);
    } catch (e) {
      error = e; busy = false;
      drawResults();
      return;
    }
    if (aud === "student" && filters.total === filters.temple_total) st.temple = true;
    drawBar();
    await load();
    const t = document.getElementById("list-title");
    if (t && (document.activeElement === document.body || root.contains(document.activeElement))) t.focus({ preventScroll: true });
  }
  await start();
}

// ---------- the sample screen ----------

export async function renderSamples(root, ctx) {
  const { api, announce } = ctx;
  const aud = ctx.audience;
  document.title = "Sample records — Perch";
  const listEl = h("div", { class: "groups", "aria-busy": "true" }, h("div", { class: "shimmer-card" }));
  let items = [], next = null, total = 0, notice = SAMPLE_NOTE;

  function draw() {
    listEl.setAttribute("aria-busy", "false");
    fill(listEl,
      items.length ? h("h2", { class: "sr-only", text: "Sample records" }) : null,
      items.length ? h("ul", { class: "leads", "aria-label": "Sample records" }, items.map((r) => recordCard(r, ctx)))
        : h("p", { class: "lede", text: aud === "student" ? "There are no sample records." : "There are no sample funding opportunities. The sample records are scholarships." }),
      next ? h("button", { class: "btn more", type: "button", "data-key": "more-samples", onclick: more }, h("span", { text: "Show more" })) : null);
  }
  async function more() {
    try {
      const data = await api.samples(aud, next);
      items.push(...data.items);
      next = data.next_cursor;
      draw();
      announce(`${data.items.length} more shown.`);
    } catch (e) {
      fill(listEl, h("div", { class: "notice error", role: "alert" }, icon("warn"), h("p", { text: e.message })));
    }
  }
  fill(root, h("div", { class: "screen list-screen samples" },
    h("a", { class: "back", href: aud === "student" ? "#/awards" : "#/funding" }, icon("back"), h("span", { text: aud === "student" ? "Back to Temple awards" : "Back to funding" })),
    h("div", {}, h("h1", { class: "page", id: "list-title", tabindex: "-1", text: "Sample records" })),
    listEl));
  const title = document.getElementById("list-title");
  try {
    const data = await api.samples(aud);
    items = data.items; next = data.next_cursor; total = data.total || items.length; notice = data.notice ? `${data.notice}` : SAMPLE_NOTE;
  } catch (e) {
    fill(listEl, h("div", { class: "notice error", role: "alert" }, icon("warn"), h("p", { text: e.message })));
    return;
  }
  // The note leads the screen: these records are invented (standing rule 11).
  title.after(h("p", { class: "notice warn sample-note", role: "note" }, h("span", { class: "tag sample", text: "Sample data" }),
    h("span", { text: ` ${notice} Source: ${SOURCE_WORDS.synthetic}.` })),
  h("p", { class: "hint", text: `${total} sample ${total === 1 ? "record" : "records"}. They never count toward the awards or funding lists.` }));
  draw();
  title.focus({ preventScroll: true });
}
