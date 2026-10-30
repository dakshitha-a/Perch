// Your documents (S13, docs/design/PRIVATE_MODE.md; every brief is a session since S23):
// add private documents, build a brief on self-hosted models, export with private text withheld or masked, end the session.
// Nothing here touches browser storage: inputs live in this module and are cleared
// when the session ends.

import { fill, h, icon } from "./dom.js";

const KIND_HINTS = {
  cv: "Used only to check career-stage rules and past sponsors. It does not steer the search.",
  proposal: "Aims or a summary of an unfinished proposal. It steers the search most.",
  direction: "A few sentences on where your work is going.",
  manuscript: "An abstract or manuscript in preparation.",
};
const WARNING = "Masking hides names, contact details and identifiers, and phrases that appear only in your private documents. It cannot hide your research direction: a reader can still tell what the work is about.";

const P = { info: null, docs: [], authorId: "", busy: false, error: null, drafts: {} };

let MODE = null; // the app's private-mode state (mode.js); set by app.js

export function setMode(m) { MODE = m; }
export function privateInfo() { return P.info; }

export async function privateAvailable(api) {
  try { P.info = await api.info(); } catch { P.info = null; }
  return Boolean(P.info && P.info.enabled);
}

export function lockLabel(text = "From your private document") {
  return h("span", { class: "tag lock" }, icon("lock"), h("span", { text }));
}

function statement() {
  return h("div", { class: "notice private-statement" }, icon("lock"),
    h("p", { text: (P.info && P.info.statement) || "" }));
}

export async function renderPrivate(root, { api, go, announce, mode }) {
  document.title = "Your documents — Perch";
  if (mode) MODE = mode;
  if (!P.info) await privateAvailable(api);
  if (!P.info || !P.info.enabled) {
    fill(root, h("div", { class: "private" }, h("h1", { text: "Your documents" }),
      h("p", { class: "notice", text: "Documents are not available on this server. They need every model to run on the server itself." }),
      h("p", {}, h("a", { href: "#/", text: "Back to Find" }))));
    return;
  }
  const draw = () => renderPrivate(root, { api, go, announce, mode });
  if (MODE) {  // text moved here from a public field waits as an unsent draft
    for (const [k, v] of Object.entries(MODE.state.drafts)) {
      if (v && P.info.kinds[k] && !P.drafts[k]) { P.drafts[k] = v; delete MODE.state.drafts[k]; }
    }
  }
  const kinds = P.info.kinds;

  async function start() {
    P.busy = true; P.error = null; draw();
    try {
      if (MODE) await MODE.enable(); else await api.start();
      announce("Session started.");
    } catch (e) { P.error = e.message; }
    P.busy = false; draw();
  }

  async function addText(kind) {
    const text = (P.drafts[kind] || "").trim();
    if (!text) return;
    await send(kind, { kind, text });
  }

  async function addFile(kind, file) {
    if (!file) return;
    if (file.size > P.info.max_bytes) { P.error = `That file is larger than ${P.info.max_bytes / 1e6} MB.`; draw(); return; }
    const data = await new Promise((ok, bad) => {
      const r = new FileReader();
      r.onload = () => ok(String(r.result).split(",", 2)[1] || "");
      r.onerror = () => bad(new Error("The file could not be read."));
      r.readAsDataURL(file);
    });
    await send(kind, { kind, filename: file.name, data });
  }

  async function send(kind, body) {
    P.busy = true; P.error = null; draw();
    try {
      await api.addDocument(body);
      P.drafts[kind] = "";
      P.docs = (await api.session()).documents;
      announce(`${kinds[kind]} added.`);
    } catch (e) { P.error = e.message; }
    P.busy = false; draw();
  }

  async function remove(kind) {
    await api.removeDocument(kind);
    P.docs = (await api.session()).documents;
    draw();
  }

  async function build() {
    P.busy = true; P.error = null; draw();
    try {
      await api.create({ author_id: P.authorId.trim() || null });
      go("#/brief/private/profile");
    } catch (e) { P.error = e.message; P.busy = false; draw(); }
  }

  const have = new Set(P.docs.map((d) => d.kind));
  const body = !api.open
    ? [h("p", { class: "lede", text: "Add a CV, a draft proposal, a research direction or unpublished work, and get routes tailored to it." }),
      h("ul", { class: "plain" },
        h("li", { text: "Only models running on this server read your documents, even when Cloud is offered." }),
        h("li", { text: "Nothing you add is saved, logged or sent elsewhere. Ending the session, closing this tab for 30 minutes, or a server restart drops everything." }),
        h("li", { text: "Exports leave out anything drawn from your documents unless you choose to mask it." })),
      h("button", { class: "btn primary", disabled: P.busy, onclick: start }, icon("lock"), h("span", { text: "Start a session" }))]
    : [
      h("ol", { class: "private-docs" }, Object.entries(kinds).map(([kind, label]) => {
        const d = P.docs.find((x) => x.kind === kind);
        return h("li", { class: "card" },
          h("div", { class: "doc-head" }, h("h2", { class: "doc-title", text: label }),
            d ? h("span", { class: "tag moss", text: `Added, ${d.chars.toLocaleString("en-US")} characters` }) : null),
          h("p", { class: "hint", text: KIND_HINTS[kind] }),
          d ? h("button", { class: "btn quiet", onclick: () => remove(kind) }, icon("dismiss"), h("span", { text: "Remove" }))
            : h("div", { class: "doc-in" },
              h("label", { class: "field-label", for: `doc-${kind}`, text: "Paste text" }),
              h("textarea", { id: `doc-${kind}`, rows: 4, value: P.drafts[kind] || "",
                oninput: (e) => { P.drafts[kind] = e.target.value; } }),
              h("div", { class: "doc-actions" },
                h("button", { class: "btn", disabled: P.busy, onclick: () => addText(kind) }, h("span", { text: "Add text" })),
                h("label", { class: "btn quiet file" }, icon("paper"), h("span", { text: "Or upload a file" }),
                  h("input", { type: "file", class: "sr-only", accept: P.info.formats.join(","),
                    onchange: (e) => addFile(kind, e.target.files[0]) })))));
      })),
      h("label", { class: "field-label", for: "p-author", text: "Your OpenAlex ID (optional)" }),
      h("input", { id: "p-author", type: "text", placeholder: "For example A5026494099", value: P.authorId,
        "aria-describedby": "p-author-hint", oninput: (e) => { P.authorId = e.target.value; } }),
      h("p", { id: "p-author-hint", class: "hint", text: "With an ID, your public papers count too: they take 40% of the weight and your documents 60%. Without one, the brief runs on your documents alone." }),
      h("div", { class: "doc-actions" },
        h("button", { class: "btn primary", disabled: P.busy || !have.size || (have.size === 1 && have.has("cv")), onclick: build },
          h("span", { text: P.busy ? "Starting" : "Build brief" })),
        endButton(api, go))];

  fill(root, h("div", { class: "private" },
    h("h1", {}, icon("lock"), h("span", { text: " Your documents" })),
    statement(),
    P.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: P.error })) : null,
    ...body));
}

export function endButton(api, go) {
  return h("button", { class: "btn", onclick: async () => {
    if (MODE) await MODE.disable(null); else await api.end();
    Object.assign(P, { docs: [], authorId: "", drafts: {}, error: null, busy: false, unmasked: "" });
    go("#/private");
  } }, icon("dismiss"), h("span", { text: "End session" }));
}

// The bar on a private brief: lock, end, exports (withheld by default, masked on opt-in)
// and the unmask view.
export function privateBar(api, go, briefId) {
  let mask = false;
  const warn = h("p", { class: "hint mask-warn", hidden: true, text: WARNING });
  const out = h("textarea", { rows: 4, "aria-label": "Masked text to unmask" });
  const shown = h("p", { class: "unmasked" });
  async function download(kind) {
    const blob = await api.exportFile(kind, mask);
    const url = URL.createObjectURL(blob);
    const a = h("a", { href: url, download: `perch-private-brief.${kind}` });
    if (kind === "html") { a.removeAttribute("download"); a.target = "_blank"; a.rel = "noopener"; }
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  return h("section", { class: "private-bar card" },
    h("div", { class: "private-bar-head" }, lockLabel("Session in memory"), endButton(api, go)),
    h("p", { class: "hint", text: "Exports leave out text drawn from your documents. Mask it instead to keep that text with names, identifiers and private phrases replaced." }),
    h("label", { class: "check" }, h("input", { type: "checkbox", onchange: (e) => { mask = e.target.checked; warn.hidden = !mask; } }),
      h("span", { text: "Mask private text in exports and hand-offs" })),
    warn,
    h("p", { class: "export" },
      h("button", { class: "btn quiet", onclick: () => download("html") }, icon("paper"), h("span", { text: "Print or save as PDF" })),
      h("button", { class: "btn quiet", onclick: () => download("md") }, icon("download"), h("span", { text: "Markdown" })),
      h("button", { class: "btn quiet", onclick: () => download("json") }, icon("download"), h("span", { text: "Records as JSON" }))),
    h("details", { class: "unmask" }, h("summary", { text: "Unmask text on this screen" }),
      h("p", { class: "hint", text: "Paste masked text from an export. The key stays in this session's memory and ends with it." }),
      out, h("button", { class: "btn", onclick: async () => {
        try { shown.textContent = (await api.unmask(out.value)).text; } catch (e) { shown.textContent = e.message; }
      } }, h("span", { text: "Unmask" })), shown),
    briefId ? null : null);
}

export function maskOn() {
  const box = document.querySelector(".private-bar input[type=checkbox]");
  return Boolean(box && box.checked);
}
