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
import { owl } from "./owl.js";

const SOURCE_WORDS = { temple_pages: "Temple public page", temple_sdfa: "Temple Scholar Development and Fellowships Advising list",
  grants_gov: "Grants.gov", nih_reporter: "NIH RePORTER", nsf: "NSF Award Search", synthetic: "SYNTHETIC sample corpus (invented)" };
const LEVEL_WORDS = { undergraduate: "Undergraduate", graduate: "Graduate", faculty: "Faculty", mixed: "Several levels" };
const NOT_STATED = "not stated";
const FAR_DAYS = 3650; // a close date this far out is a placeholder; the page's own words replace it (G8)
const SAMPLE_PAGE = 12; // the samples screen loads a dozen, then Show more (S14)
const SAMPLE_NOTE = "These are invented records from a test corpus. They show how Perch works; they are not real awards. Do not apply to them.";

// The levels come from the server; a value this file has no word for shows as the server gave it.
const levelWord = (v) => LEVEL_WORDS[v] || String(v).replace(/(^|[\s,/])(\p{L})/gu, (m, a, b) => a + b.toUpperCase());

// What each side's list remembers while the visitor stays in the app. Funding opens sorted by
// the soonest close date with closed calls hidden; the awards list opens A to Z, because most
// awards state no date and a date sort would bury them (S49 decisions).
const SORTS = {
  student: [["name", "A to Z"], ["closing", "Deadline soonest"], ["amount", "Largest amount"]],
  researcher: [["closing", "Closing soonest"], ["name", "A to Z"], ["amount", "Largest award"]],
};
const L = {
  student: { temple: true, school: null, allTemple: false, level: "", q: "", sort: "name", closed: false },
  researcher: { temple: false, school: null, allTemple: false, level: "", q: "", sort: "closing", closed: false },
};

// ---------- the row ----------

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

// "Past" is written by code when the record's own date, with its year, is before today. A
// record with no full date gets no marker; nothing is inferred (rule 3).
function isPast(r) {
  const d = r.kind === "opportunity" ? r.close_date : r.deadline;
  if (!/^\d{4}-\d{2}-\d{2}/.test(String(d || ""))) return false;
  return String(d).slice(0, 10) < f.localToday();
}

const farOff = (r) => {
  const days = r.close_date ? f.daysBetween(f.localToday(), r.close_date) : null;
  return days !== null && days > FAR_DAYS;
};

function deadlineText(r) {
  if (r.kind === "opportunity") {
    if (r.close_text) return r.close_text;  // the server's words for the close date; a placeholder date never shows
    if (r.close_date_note && (f.standardDates(r) || farOff(r))) return r.close_date_note;
    if (!r.close_date) return NOT_STATED; // the page's own words, if any, show as a quote (V29)
    return `${f.expiresOnly(r) ? "Expires " : ""}${f.formatDate(r.close_date)}`;
  }
  return r.deadline ? f.formatDate(r.deadline) : NOT_STATED;
}

// The scope words say honestly what the page does and does not say (fork F2). A page that
// does not state a scope says nothing here; Evidence still shows the field (U25).
function scopeLine(r) {
  if (r.scope === "school") return "Open to one school";
  if (r.scope === "temple_wide") return "Open across Temple";
  return null;
}

// The line under the title: schools, level words, scope, sponsor or agency, in one muted line.
function subParts(r) {
  const opp = r.kind === "opportunity";
  const out = [];
  const schools = [...new Set(r.schools || [])];
  if (schools.length) out.push(schools.join(", "));
  const levels = (r.levels ? [r.levels] : []).flat().map(levelWord);
  if (levels.length) out.push(levels.join(", "));
  const scope = opp ? null : scopeLine(r);
  if (scope) out.push(scope);
  if (opp) {
    const short = r.agency ? f.agencyShort(r.agency, r.parent_agency) : null;
    if (short && !schools.includes(short) && !schools.includes(r.agency)) out.push(short);
    if (r.source === "grants_gov" && r.opportunity_number) out.push(r.opportunity_number);
  } else if (r.sponsor) out.push(r.sponsor);
  return out;
}

export function recordRow(r, { openEvidence }, keep = null) {
  const opp = r.kind === "opportunity";
  const name = opp ? r.title : r.name;
  const quote = firstQuote(r);
  const amount = amountText(r), due = deadlineText(r);
  const noDate = due === NOT_STATED;
  const words = opp ? r.close_date_note : r.deadline_quote;
  const pageSays = noDate && words ? `The page says: “${words}”` : null;
  const tid = `t-${String(r.id).replace(/[^A-Za-z0-9_-]/g, "_")}`;
  const sub = subParts(r);
  const past = isPast(r);
  const bothMissing = amount === NOT_STATED && noDate && !pageSays;
  const dateLabel = opp ? "Closes" : "Deadline";
  const src = f.safeUrl(r.source_url);
  const sample = Boolean(r.sample);
  const subKids = [];
  if (sample) subKids.push(h("span", { class: "tag sample", text: "Sample data" }));
  if (r.temple_funded === true) subKids.push(h("span", { class: "tag ember", text: "Temple-funded" }));
  sub.forEach((t, i) => subKids.push(h("span", { text: (i || subKids.length ? " · " : "") + t })));
  return h("li", { class: `award-row award${sample ? " is-sample" : ""}`, "data-id": r.id, "data-sample": sample ? "true" : null },
    h("div", { class: "ar-main" },
      h("h3", { class: "ar-title" }, h("button", { class: "title-btn", id: tid, type: "button",
        onclick: (e) => openEvidence(r, e.currentTarget) }, h("span", { text: name || (opp ? "Untitled opportunity" : "Untitled award") }), evMark())),
      subKids.length ? h("p", { class: "ar-sub" }, ...subKids) : null,
      quote ? h("blockquote", { class: "ar-quote", text: `“${quote}”` }) : null),
    h("div", { class: "ar-facts" },
      bothMissing ? h("p", { class: "missing", text: "Not on the page" })
        : h("dl", {},
          h("dt", { text: "Amount" }), h("dd", { class: "amt" }, h("span", { class: amount === NOT_STATED ? "missing" : null, text: amount === NOT_STATED ? "Not stated" : amount })),
          h("dt", { text: dateLabel }), h("dd", {},
            pageSays ? h("span", { class: "quote-date", title: pageSays, text: pageSays })
              : h("span", { class: noDate ? "missing" : null, text: noDate ? "Not stated" : due }),
            past ? h("span", { class: `tag ${opp ? "closed" : "past"}`, text: opp ? "Closed" : "Past date on the page" }) : null)),
      h("p", { class: "ar-src", text: `Source: ${SOURCE_WORDS[r.source] || r.source}` })),
    h("div", { class: "ar-acts" },
      keep && !sample ? keepButton(r, keep) : null,
      src ? h("a", { class: "btn icon-only", href: src, target: "_blank", rel: "noopener", "aria-label": `Open at source: ${name || r.id}`,
        title: "Open at source" }, icon("external")) : null));
}

// Keep on a row: signed in, not a sample. `keep` is { saved: Map(record_id -> saved_id), side, api, announce }.
function keepButton(r, keep) {
  const btn = h("button", { class: "btn keep", type: "button", "data-key": `keep-${r.id}` });
  const paint = () => {
    const on = keep.saved.has(r.id);
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", String(on));
    btn.replaceChildren(icon("keep"), h("span", { text: on ? "Kept" : "Keep" }));
    btn.setAttribute("aria-label", `${on ? "Kept" : "Keep"}: ${r.kind === "opportunity" ? r.title : r.name}`);
  };
  btn.onclick = async () => {
    if (btn.getAttribute("aria-busy") === "true") return;
    const was = keep.saved.get(r.id);
    btn.setAttribute("aria-busy", "true");
    if (was) keep.saved.delete(r.id); else keep.saved.set(r.id, "pending");  // shown at once; reverted on an error
    paint();
    try {
      if (was) await keep.api.unsave(was);
      else keep.saved.set(r.id, (await keep.api.save(r.id, keep.side)).saved_id);
      keep.announce(was ? "Removed from My Perch." : "Kept. It shows on My Perch.");
    } catch (e) {
      if (was) keep.saved.set(r.id, was); else keep.saved.delete(r.id);
      keep.announce(e.code === "consent_required" ? "Agree to the consent first." : e.message);
    }
    btn.removeAttribute("aria-busy");
    paint();
  };
  paint();
  return btn;
}

// ---------- the list screens ----------

const labelOf = (aud) => (aud === "student" ? { noun: "awards", title: "Temple awards", keepNoun: "awards" } : { noun: "opportunities", title: "Research funding", keepNoun: "calls" });

function params(aud, st, filters, extra = {}) {
  const showToggle = aud === "researcher" || filters.total !== filters.temple_total;
  const temple = showToggle ? st.temple : true;
  const tags = temple || aud === "student";
  return {
    temple_only: temple, school: tags && st.school ? st.school : null,
    scope: tags && st.allTemple && !st.school ? "temple_wide,unstated" : null,
    level: st.level || null, q: st.q.trim() || null, sort: st.sort,
    open_only: aud === "researcher" && !st.closed, limit: 25, ...extra,
  };
}

export async function renderList(root, ctx) {
  const { api, announce } = ctx;
  const aud = ctx.audience;
  const kind = aud === "student" ? "awards" : "opportunities";
  const st = L[aud], word = labelOf(aud);
  document.title = `${word.title} — Perch`;
  const sess = ctx.session ? ctx.session() : {};
  const signedIn = Boolean(sess.signed_in && !sess.guest);
  const roles = (sess.roles || []).filter((r) => r === "student" || r === "researcher");
  // Saving goes to the list's own side when the account has that role; else the session's side.
  const keepState = signedIn ? { saved: new Map(), side: roles.includes(aud) ? aud : (sess.audience || roles[0] || aud), api, announce } : null;
  let filters = null, results = null, error = null, busy = true, gen = 0, folded = true;  // the filters start folded on a phone
  const groupsEl = h("div", { class: "groups", "aria-busy": "true" });
  const barEl = h("div", { class: "filter-bar" });
  const countEl = h("span", { class: "list-count", "aria-hidden": "true" });
  const showToggle = () => filters && (aud === "researcher" || filters.total !== filters.temple_total);
  const total = () => (results ? results.reduce((n, g) => n + g.total, 0) : 0);
  // The school counts describe the whole list; while a search or level is set they would be wrong (U1).
  const syncCounts = () => {
    const hide = Boolean(st.q.trim() || st.level);
    barEl.querySelectorAll(".tag-chip .n").forEach((n) => { n.hidden = hide; });
  };

  const keep = (fn) => {  // redraw and put focus back on the control that had it
    const a = document.activeElement;
    const key = a && a.dataset ? a.dataset.key : null;
    fn();
    if (key) { const t = root.querySelector(`[data-key="${CSS.escape(key)}"]`); if (t && t !== document.activeElement) t.focus({ preventScroll: true }); }
  };

  async function load() {
    const mine = ++gen;
    busy = true; error = null;
    syncCounts();
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
      fill(groupsEl, h("div", { class: "empty-list" }, owl("look", "owl-md"),
        h("div", { class: "notice error", role: "alert" }, icon("warn"),
          h("div", {}, h("p", { text: "Perch could not load the list. Try again." }),
            h("button", { class: "btn", type: "button", "data-key": "retry", onclick: () => (filters ? load() : start()) }, h("span", { text: "Retry" }))))));
      return;
    }
    if (!results || !total()) {
      fill(groupsEl, h("div", { class: "empty-list" }, owl("look", "owl-md"), h("p", { class: "lede", text: `No ${word.noun} match these filters.` }),
        h("button", { class: "btn", type: "button", "data-key": "clear", onclick: clearAll }, h("span", { text: "Clear filters" }))));
      return;
    }
    fill(groupsEl, results.map((g) => h("section", { class: "group", "aria-labelledby": `g-${g.key}` },
      g.label ? h("h2", { class: "section-title group-title", id: `g-${g.key}`, text: `${g.label} (${g.total})` })
        : h("h2", { class: "sr-only", id: `g-${g.key}`, text: word.title }),
      g.items.length ? h("ul", { class: "award-list", "aria-labelledby": `g-${g.key}` }, g.items.map((r) => recordRow(r, ctx, keepState)))
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
    const toggles = [
      showToggle() ? h("button", { type: "button", role: "switch", class: "switch", "data-key": "temple", "aria-checked": String(st.temple),
        onclick: () => { st.temple = !st.temple; keep(drawBar); load(); } },
      h("span", { class: "knob", "aria-hidden": "true" }), h("span", { text: "Temple only" })) : null,
      aud === "researcher" ? h("button", { type: "button", role: "switch", class: "switch", "data-key": "show-closed", "aria-checked": String(st.closed),
        onclick: () => { st.closed = !st.closed; keep(drawBar); load(); } },
      h("span", { class: "knob", "aria-hidden": "true" }), h("span", { text: "Show closed calls" })) : null].filter(Boolean);
    const set = [st.school, st.level, st.sort !== SORTS[aud][0][0] ? 1 : 0, st.closed, st.allTemple].filter(Boolean).length;
    const searchField = h("input", { id: "list-q", name: "q", type: "search", value: st.q, placeholder: `Search ${word.noun}`, autocomplete: "off",
      oninput: (e) => { st.q = e.target.value; clear.hidden = !st.q; syncCounts(); clearTimeout(drawBar.t); drawBar.t = setTimeout(load, 400); } });
    const clear = h("button", { class: "btn quiet icon-only search-clear", type: "button", "aria-label": "Clear the search", hidden: !st.q,
      onclick: () => { st.q = ""; searchField.value = ""; clear.hidden = true; searchField.focus(); syncCounts(); load(); } }, icon("close"));
    const body = h("div", { id: "filter-body", class: `filter-body${folded ? " is-folded" : ""}` },
      h("div", { class: "filter-row" },
        aud === "student" ? h("div", { class: "field-pick level-pick" },
          h("label", { for: "list-level", text: "Level of study" }),
          h("select", { id: "list-level", "data-key": "level", onchange: (e) => { st.level = e.target.value; keep(drawBar); load(); } },
            h("option", { value: "", text: "Any level" }),
            ...((filters && filters.levels) || []).map((v) => h("option", { value: v, selected: st.level === v, text: levelWord(v) })))) : null,
        h("div", { class: "field-pick sort-pick" },
          h("label", { for: "list-sort", text: "Sort by" }),
          h("select", { id: "list-sort", "data-key": "sort", onchange: (e) => { st.sort = e.target.value; keep(drawBar); load(); } },
            ...SORTS[aud].map(([v, label]) => h("option", { value: v, selected: st.sort === v, text: label }))))),
      toggles.length ? h("div", { class: "switch-row" }, ...toggles) : null,
      tagsOn ? tagRow : h("p", { class: "hint", text: "Turn on Temple only to choose a school." }));
    const toggle = h("button", { class: "btn filter-toggle", type: "button", "data-key": "filters", "aria-expanded": String(!folded), "aria-controls": "filter-body",
      onclick: () => { folded = !folded; body.classList.toggle("is-folded", folded); toggle.setAttribute("aria-expanded", String(!folded)); } },
    icon("filter"), h("span", { text: "Filters" }), h("span", { class: "filter-n", hidden: !set, text: set ? ` · ${set}` : "" }));
    fill(barEl,
      h("div", { class: "search-row" },
        h("form", { class: "searchbox small", role: "search", onsubmit: (e) => { e.preventDefault(); st.q = e.currentTarget.q.value; load(); } },
          h("label", { for: "list-q", class: "sr-only", text: `Search the ${word.noun}` }),
          h("div", { class: "search-field" }, searchField, clear),
          h("button", { class: "btn", type: "submit", text: "Search" }))),
      toggle, body);
    syncCounts();
  }

  const page = h("div", { class: "screen list-screen" },
    h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
    h("div", { class: "title-row" },
      h("div", {}, h("h1", { class: "page", id: "list-title", tabindex: "-1", text: word.title }), countEl)),
    barEl,
    // The link is the sentence's own first words, so it reads once and sits inside the text (S49 QA).
    signedIn ? null : h("p", { class: "hint keep-line" }, icon("keep"),
      h("span", {}, h("a", { href: ctx.signIn ? ctx.signIn() : "#/", text: "Sign in" }),
        ` to keep ${word.keepNoun}. What you keep, with its date, collects on My Perch.`)),
    groupsEl,
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
    if (keepState) {
      try {
        const got = await api.saved(keepState.side);
        for (const it of got.items) if (it.saved_id) keepState.saved.set(it.record_id, it.saved_id);
      } catch { /* no saved list: the buttons start unpressed */ }
    }
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
      items.length ? h("ul", { class: "award-list", "aria-label": "Sample records" }, items.map((r) => recordRow(r, ctx)))
        : h("p", { class: "lede", text: aud === "student" ? "There are no sample records." : "There are no sample funding opportunities. The sample records are scholarships." }),
      next ? h("button", { class: "btn more", type: "button", "data-key": "more-samples", onclick: more }, h("span", { text: "Show more" })) : null);
  }
  async function more() {
    try {
      const data = await api.samples(aud, next, SAMPLE_PAGE);
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
    const data = await api.samples(aud, null, SAMPLE_PAGE);
    items = data.items; next = data.next_cursor; total = data.total || items.length; notice = data.notice ? `${data.notice}` : SAMPLE_NOTE;
  } catch (e) {
    fill(listEl, h("div", { class: "notice error", role: "alert" }, icon("warn"), h("p", { text: e.message })));
    return;
  }
  // The note leads the screen: these records are invented (standing rule 11).
  title.parentNode.after(h("p", { class: "notice warn sample-note", role: "note" }, h("span", { class: "tag sample", text: "Sample data" }),
    h("span", { text: ` ${notice} Source: ${SOURCE_WORDS.synthetic}.` })),
  h("p", { class: "hint", text: `${total} sample ${total === 1 ? "record" : "records"}. They never count toward the awards or funding lists.` }));
  draw();
  title.focus({ preventScroll: true });
}
