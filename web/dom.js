// Tiny DOM helpers shared by the app's modules. Values go in through textContent;
// icons are static paths.

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "value" && tag === "textarea") el.value = v; // a textarea has no value attribute
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") el.style.cssText = v; // CSSOM: the CSP blocks style attributes
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  add(el, kids);
  return el;
}

export function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

export function fill(el, ...kids) {
  el.replaceChildren();
  return add(el, kids);
}


// Copies each column name onto its cells, so a table can stack into labelled cards on a
// phone (S25 review).
export function labelCells(table) {
  const names = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
  for (const tr of table.querySelectorAll("tbody tr")) {
    [...tr.children].forEach((cell, i) => { if (names[i]) cell.dataset.label = names[i]; });
  }
  return table;
}

export function icon(name) {
  const paths = {
    keep: "M5 12.5l4.5 4.5L19 7.5",
    dismiss: "M6.5 6.5l11 11M17.5 6.5l-11 11",
    restore: "M4 12a8 8 0 1 0 2.4-5.7M4 4v4.5h4.5",
    evidence: "M4.5 5h15v14h-15zM14 5v14M7 9h4M7 12.5h4",
    external: "M10.5 4.5h-5v14h13v-5M13.5 4.5h6v6M19.5 4.5l-9 9",
    search: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM15.5 15.5l4.5 4.5",
    back: "M14.5 5.5l-6.5 6.5 6.5 6.5",
    warn: "M12 4l9 16H3zM12 10v4.5M12 17.2v.3",
    clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2",
    close: "M6.5 6.5l11 11M17.5 6.5l-11 11",
    help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.6 9.3a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .9-1 1.6v.6M12 17v.2",
    paper: "M7 3.5h7l4 4v13H7zM14 3.5v4h4M9.5 12h6M9.5 15.5h6",
    threads: "M5 7h14M5 12h10M5 17h12",
    search2: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM15.5 15.5l4.5 4.5M8 10.5h5",
    filter: "M4 5h16l-6 7.5V19l-4-2v-4.5z",
    rank: "M6 18V11M12 18V6M18 18v-4",
    pen: "M4 20l4-1 10.5-10.5-3-3L5 16zM14 7l3 3",
    check: "M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6zM8.8 12l2.3 2.3 4.2-4.6",
    person: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20.5c1-3.8 4-5.5 7.5-5.5s6.5 1.7 7.5 5.5",
    theme: "M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z",
    download: "M12 4v11M7 10.5l5 5 5-5M5 19.5h14",
    lock: "M6.5 10.5h11v9h-11zM8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5M12 14v2",
    stop: "M7 7h10v10H7z",
  };
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("class", "icon");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", paths[name]);
  s.append(p);
  return s;
}
