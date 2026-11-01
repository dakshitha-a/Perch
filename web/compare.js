// Compare tab: kept leads in one sortable table (GET /briefs/{id}/compare). Every cell
// is copied from a record or computed from one by code, and opens that record in the
// evidence panel. A cell with nothing behind it says so; it never guesses.

import { h, fill, icon, labelCells } from "./dom.js";
import { formatDate } from "./format.js";

const C = { data: null, briefId: null, sig: "", sort: { key: null, dir: 1 }, error: null };

// Load the compare rows when the kept set changes. `kept` is the kept lead ids, sorted.
export async function loadCompare(api, briefId, kept, redraw) {
  const sig = `${briefId}:${kept.join(",")}`;
  if (C.sig === sig && (C.data || C.error)) return;
  C.sig = sig;
  C.briefId = briefId;
  C.error = null;
  try {
    const got = await api.compare(briefId);
    if (C.sig !== sig) return;
    C.data = got;
  } catch (e) {
    if (C.sig !== sig) return;
    C.data = null;
    C.error = e.message;
  }
  redraw();
}

function sorted(rows) {
  const { key, dir } = C.sort;
  if (!key) return rows;
  const v = (r) => (key === "lead" ? r.title.toLowerCase() : r.cells[key].sort);
  return [...rows].sort((a, b) => {
    const x = v(a), y = v(b);
    if (x === null && y === null) return 0;
    if (x === null) return 1; // nothing in the record: always last
    if (y === null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * dir;
  });
}

function sortButton(col, redraw) {
  const on = C.sort.key === col.key;
  return h("button", { class: "th-sort", type: "button", "data-key": `sort-${col.key}`,
    onclick: () => {
      C.sort = on ? { key: col.key, dir: -C.sort.dir } : { key: col.key, dir: 1 };
      redraw(`sort-${col.key}`);
    } }, h("span", { text: col.label }),
  // A neutral mark says the column sorts before it is pressed (U15).
  h("span", { class: `sort-mark${on ? " on" : ""}`, "aria-hidden": "true", text: on ? (C.sort.dir > 0 ? "▲" : "▼") : "↕" }));
}

// On a phone the table stacks into cards with no column names, so a select sorts (U15).
function sortSelect(columns, redraw) {
  const cols = [{ key: "lead", label: "Lead" }, ...columns];
  const value = C.sort.key ? `${C.sort.key}:${C.sort.dir}` : "";
  return h("label", { class: "compare-sort-row" }, h("span", { text: "Sort by" }),
    h("select", { class: "compare-sort", "data-key": "compare-sort",
      onchange: (e) => {
        const [key, dir] = e.target.value.split(":");
        C.sort = key ? { key, dir: Number(dir) } : { key: null, dir: 1 };
        redraw("compare-sort");
      } },
    h("option", { value: "", selected: !value, text: "Perch’s order" }),
    ...cols.flatMap((c) => [1, -1].map((d) => h("option", { value: `${c.key}:${d}`, selected: value === `${c.key}:${d}`,
      text: `${c.label}, ${d > 0 ? "A to Z or low to high" : "Z to A or high to low"}` })))));
}

function cellView(key, cell, rowTitle, label, openEvidence) {
  // A date is formatted; the record's own words for a placeholder date stay as they are (U3).
  const text = key === "closes" && /^\d{4}-\d{2}-\d{2}$/.test(cell.text) ? formatDate(cell.text) : cell.text;
  const body = [h("span", { class: cell.sort === null ? "cell-none" : "cell-text", text }),
    cell.note ? h("span", { class: "cell-note", text: cell.note }) : null];
  if (!cell.record_id) return h("td", { class: `col-${key}` }, ...body);
  return h("td", { class: `col-${key}` }, h("button", { class: "cell-btn", type: "button",
    "aria-label": `${label} for ${rowTitle}: ${text}. Open the record.`,
    onclick: (e) => openEvidence(cell.record_id, e.currentTarget) }, ...body));
}

export function renderCompare(panel, { keptCount, openEvidence, goRoutes, redraw, handoff }) {
  if (!keptCount) {
    fill(panel, h("div", { class: "empty" }, h("div", {},
      h("p", { class: "lede", text: "Keep a lead to compare it here." }),
      h("p", { class: "hint", text: "On the Routes tab, press Keep on the grants and industry "
        + "leads you want to weigh up." }),
      h("button", { class: "btn", type: "button", onclick: goRoutes, text: "Go to Routes" }))));
    return;
  }
  if (C.error) {
    fill(panel, h("p", { class: "notice error" }, icon("warn"),
      h("span", { text: `The comparison could not be loaded: ${C.error}` })));
    return;
  }
  if (!C.data) {
    fill(panel, h("p", { class: "hint", text: "Loading the comparison…" }));
    return;
  }
  const { rows } = C.data;
  const columns = C.data.columns.filter((c) => c.key !== "office"); // shown in the row heading
  const sortAria = (key) => (C.sort.key === key ? (C.sort.dir > 0 ? "ascending" : "descending") : null);
  const head = h("tr", {}, h("th", { scope: "col", "aria-sort": sortAria("lead") }, sortButton({ key: "lead", label: "Lead" }, redraw)),
    ...columns.map((c) => h("th", { scope: "col", "aria-sort": C.sort.key === c.key
      ? (C.sort.dir > 0 ? "ascending" : "descending") : null }, sortButton(c, redraw))));
  const body = sorted(rows).map((r) => h("tr", { class: r.route === "B" ? "row-b" : null },
    h("th", { scope: "row" }, h("span", { class: "route-tag", text: r.route === "B" ? "Industry" : "Grant" }),
      h("span", { class: "row-title", text: r.title }),
      h("span", { class: "cell-note", text: `Office: ${r.cells.office.text}` })),
    ...columns.map((c) => cellView(c.key, r.cells[c.key], r.title, c.label, openEvidence))));
  const hasB = rows.some((r) => r.route === "B");
  fill(panel,
    h("div", { class: "routes-bar" }, h("div", {},
      h("h2", { class: "section-title", id: "compare-title", text: `Compare ${rows.length} kept ${rows.length === 1 ? "lead" : "leads"}` }),
      h("p", { class: "hint" }, h("span", { text: "Every cell is copied from its record or counted from it by code. Press a cell to see the record." }),
        h("span", { class: "sort-hint-wide", text: " Press a column name to sort." })),
      sortSelect(columns, redraw))),
    // The hand-off comes before the table, so drafting needs no scroll (review W2).
    handoff ? h("div", { class: "handoff-box" }) : null,
    hasB ? h("p", { class: "notice" }, icon("warn"), h("span", { text: "Industry leads are inferred "
      + "from public signals and not verified. Their records hold no amount or deadline." })) : null,
    // The table scrolls sideways only when it is a table; stacked into cards on a phone it
    // does not, so it is no tab stop there (F13).
    h("div", { class: "compare-wrap", role: "region", "aria-labelledby": "compare-title",
      tabindex: window.matchMedia("(max-width: 600px)").matches ? null : "0" },
      labelCells(h("table", { class: "compare stack" }, h("thead", {}, head), h("tbody", {}, ...body)))),
    h("p", { class: "hint", text: "Money and dates are as each record states them. "
      + "The office under each lead is the Temple office that handles that route." }));
}

export function compareOffices() {
  return C.data ? C.data.offices : null;
}
