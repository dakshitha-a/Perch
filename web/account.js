// Account screens (S43): the welcome step after a first sign-in (#/welcome), the account
// page with the delete-my-data dialog (#/account) and My Perch with the past briefs (#/me).
// The consent text is whatever the server sends, shown as written (GET /auth/session).

import { fill, h, icon } from "./dom.js";
import * as f from "./format.js";

const needSignIn = (ctx, what) => h("div", { class: "screen" },
  h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
  h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: what }),
    h("p", { class: "page-sub", text: "Sign in to see this page." })),
  h("p", {}, h("a", { class: "btn primary", href: ctx.signIn(), text: "Sign in" })));

const KIND_WORDS = { cv: "CV", interests: "Interests note", entry: "Entry", proposal: "Proposal",
  direction: "Research direction", manuscript: "Manuscript" };

// ---------- welcome ----------

export function renderWelcome(root, ctx, returnTo) {
  const sess = ctx.session();
  document.title = "Welcome — Perch";
  if (!sess.signed_in) {
    fill(root, needSignIn(ctx, "Welcome to Perch"));
    return;
  }
  const c = sess.consent || {};
  const held = new Set((sess.roles || []).filter((r) => r === "student" || r === "researcher"));
  const state = { student: held.has("student"), researcher: held.has("researcher"),
    agreed: c.required === false, oa: "", busy: false, error: null };
  const alreadyAgreed = c.required === false;
  const draw = () => {
    const a = document.activeElement;
    const key = a && a.dataset ? a.dataset.key : null;
    paint();
    if (key) { const t = root.querySelector(`[data-key="${key}"]`); if (t) t.focus({ preventScroll: true }); }
  };
  const row = (key, label, hint) => h("label", { class: "check-row" },
    h("input", { type: "checkbox", "data-key": `role-${key}`, checked: state[key],
      onchange: (e) => { state[key] = e.target.checked; draw(); } }),
    h("span", {}, h("b", { text: label }), hint ? h("span", { class: "hint", text: ` ${hint}` }) : null));
  async function submit() {
    state.busy = true; state.error = null; draw();
    try {
      const roles = ["student", "researcher"].filter((r) => state[r]);
      await ctx.api.setRoles(roles);
      if (state.researcher && state.oa.trim()) await ctx.api.linkOpenAlex(state.oa.trim());
      if (!alreadyAgreed || !c.accepted_version || c.accepted_version < c.current_version) await ctx.api.consent(c.current_version);
      await ctx.refresh();
      ctx.announce("Welcome to Perch.");
      const next = returnTo && returnTo.startsWith("/#/") ? returnTo.slice(1) : "#/";
      ctx.go(next);
    } catch (e) {
      state.busy = false; state.error = e.message; draw();
    }
  }

  function paint() {
    const sidesDone = state.student || state.researcher;
    const ready = sidesDone && state.agreed && !state.busy;
    // DRAFT copy (S43): the screen's headings and field labels, for Dakshitha to review.
    // The consent text itself is the server's, shown as sent.
    fill(root, h("div", { class: "screen welcome" },
      h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: "Welcome to Perch" }),
        h("p", { class: "page-sub", text: "Two short steps, then you are in." })),
      h("section", { class: "box", "aria-labelledby": "w1" },
        h("h2", { class: "section-title", id: "w1", text: "1. What brings you here?" }),
        row("student", "I am a student"), row("researcher", "I am a researcher"),
        h("p", { class: "hint", text: "You can pick both." }),
        state.researcher ? h("div", { class: "oa-field" },
          h("label", { for: "oa-id", class: "big", text: "Your OpenAlex author id (optional)" }),
          h("input", { id: "oa-id", type: "text", value: state.oa, autocomplete: "off", placeholder: "A5023888391",
            "aria-describedby": "oa-hint", oninput: (e) => { state.oa = e.target.value; } }),
          h("p", { class: "note", id: "oa-hint", text: "An OpenAlex author id is an A followed by at least eight digits. You can leave this empty." })) : null),
      h("section", { class: "box", "aria-labelledby": "w2" },
        h("h2", { class: "section-title", id: "w2", text: "2. How Perch uses your CV" }),
        h("div", { class: "consent-text", tabindex: "0", role: "region", "aria-label": "Consent text" },
          h("p", { text: c.text || "" })),
        h("p", { class: "hint", text: `Consent text, version ${c.current_version ?? ""}.` }),
        h("label", { class: "check-row" },
          h("input", { type: "checkbox", "data-key": "agree", checked: state.agreed,
            onchange: (e) => { state.agreed = e.target.checked; draw(); } }),
          h("span", {}, h("b", { text: "I agree" })))),
      state.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: state.error })) : null,
      h("div", { class: "welcome-go" },
        h("button", { class: "btn primary big", type: "button", "data-key": "continue", disabled: !ready,
          "aria-busy": state.busy ? "true" : null, onclick: submit }, h("span", { text: state.busy ? "Saving" : "Continue" })),
        !ready && !state.busy ? h("p", { class: "hint", text: !sidesDone ? "Choose at least one side to continue." : "Tick “I agree” to continue." }) : null)));
  }
  paint();
  const t = document.getElementById("acct-title");
  if (t) t.focus({ preventScroll: true });
}

// ---------- account and data ----------

export async function renderAccount(root, ctx) {
  const sess = ctx.session();
  document.title = "Account and data — Perch";
  if (!sess.signed_in) { fill(root, needSignIn(ctx, "Account and data")); return; }
  const roles = (sess.roles || []).filter((r) => r === "student" || r === "researcher");
  const docsEl = h("div", { class: "doc-list", "aria-busy": "true" }, h("div", { class: "shimmer-card" }));
  let docs = [], docError = null;

  const sideWord = (s) => (s === "student" ? "Student" : "Researcher");
  async function loadDocs() {
    try {
      const out = [];
      for (const side of roles) for (const d of await ctx.api.docs(side)) out.push({ ...d, side });
      docs = out; docError = null;
    } catch (e) { docError = e; }
    drawDocs();
  }
  function drawDocs() {
    docsEl.setAttribute("aria-busy", "false");
    if (docError) {
      fill(docsEl, h("p", { class: "notice warn" }, icon("warn"), h("span", { text: docError.code === "consent_required" || docError.status === 403
        ? "Your documents show here once you have agreed to the consent." : `Your documents could not be loaded. ${docError.message}` })));
      return;
    }
    fill(docsEl, docs.length ? h("ul", { class: "docs" }, docs.map((d) => h("li", { class: "doc" },
      h("span", { class: "doc-name" }, h("b", { text: d.name || d.label || KIND_WORDS[d.kind] || d.kind }),
        h("span", { class: "hint", text: ` ${KIND_WORDS[d.kind] || d.kind}${roles.length > 1 ? `, ${sideWord(d.side)} side` : ""}` })),
      h("button", { class: "btn", type: "button", "data-key": `rm-${d.id}`, onclick: () => removeDoc(d),
        "aria-label": `Remove ${d.name || d.label || d.kind}` }, h("span", { text: "Remove" })))))
      : h("p", { class: "hint", text: "You have no stored documents." }));
  }
  async function removeDoc(d) {
    try {
      await ctx.api.removeDoc(d.id);
      docs = docs.filter((x) => x.id !== d.id);
      drawDocs();
      ctx.announce("Removed.");
      const t = document.getElementById("docs-h"); if (t) t.focus();
    } catch (e) { ctx.announce(e.message); }
  }

  // ----- the delete dialog: a real <dialog>, guarded by typing the word -----
  const word = h("input", { id: "del-word", type: "text", autocomplete: "off", autocapitalize: "off", spellcheck: "false",
    "aria-describedby": "del-help" });
  const go = h("button", { class: "btn danger", type: "button", id: "del-go", disabled: true }, h("span", { text: "Delete my data" }));
  const err = h("p", { class: "notice error", role: "alert", hidden: true });
  const dlg = h("dialog", { class: "del-dialog", "aria-labelledby": "del-title" },
    h("form", { method: "dialog", onsubmit: (e) => e.preventDefault() },
      h("h2", { id: "del-title", class: "section-title", text: "Delete my data" }),
      // DRAFT copy (S43): the dialog text, for Dakshitha to review. It follows the consent
      // text and the delete route: CV and entries, briefs, account and key, 35-day backups.
      h("p", { id: "del-help", text: "This deletes your CV and entries, your briefs and your account. Your key is destroyed, so nothing stored under it can be read again. After you delete your data, backups clear within 35 days. If you do nothing for 12 months, Perch deletes your data anyway." }),
      h("label", { for: "del-word", class: "big", text: "Type delete to confirm" }), word, err,
      h("div", { class: "dlg-actions" },
        h("button", { class: "btn", type: "button", id: "del-cancel", onclick: () => dlg.close() }, h("span", { text: "Cancel" })), go)));
  const opener = h("button", { class: "btn danger", type: "button", id: "del-open", "data-key": "del-open",
    onclick: () => { word.value = ""; go.disabled = true; err.hidden = true; dlg.showModal(); word.focus(); } },
  h("span", { text: "Delete my data…" }));
  dlg.addEventListener("close", () => { if (document.contains(opener)) opener.focus(); });
  word.addEventListener("input", () => { go.disabled = word.value !== "delete"; });
  go.addEventListener("click", async () => {
    if (word.value !== "delete") return;
    go.disabled = true;
    try {
      await ctx.api.deleteMe();
      dlg.close();
      await ctx.refresh();
      ctx.flash("Your data was deleted.", "#/");
      ctx.go("#/");
    } catch (e) {
      err.hidden = false; err.textContent = e.message; go.disabled = word.value !== "delete";
    }
  });

  fill(root, h("div", { class: "screen account" },
    h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
    h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: "Account and data" })),
    h("dl", { class: "fields acct-facts" },
      h("div", { class: "field" }, h("dt", { text: "Signed in as" }), h("dd", { text: sess.display_name || "your account" })),
      h("div", { class: "field" }, h("dt", { text: "Your sides" }), h("dd", { text: roles.map(sideWord).join(" and ") || "None chosen" })),
      sess.consent ? h("div", { class: "field" }, h("dt", { text: "Consent" }),
        h("dd", { text: sess.consent.required ? "Not agreed to the current text" : `Version ${sess.consent.accepted_version}, agreed` })) : null),
    h("section", { class: "box", "aria-labelledby": "docs-h" },
      h("h2", { class: "section-title", id: "docs-h", tabindex: "-1", text: "Your documents" }), docsEl),
    h("section", { class: "box danger-zone", "aria-labelledby": "del-h" },
      h("h2", { class: "section-title", id: "del-h", text: "Delete my data" }),
      h("p", { text: "Delete your CV and entries, your briefs and your account. Perch also deletes your data after 12 months without use." }),
      opener),
    dlg));
  document.getElementById("acct-title").focus({ preventScroll: true });
  await loadDocs();
}

// ---------- My Perch: past briefs ----------

export async function renderMyPerch(root, ctx) {
  const sess = ctx.session();
  document.title = "My Perch — Perch";
  if (sess.guest) {
    fill(root, h("div", { class: "screen" },
      h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
      h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: "My Perch" }),
        h("p", { class: "page-sub", text: "Sign in to keep briefs and saved awards." })),
      h("p", {}, h("a", { class: "btn primary", href: ctx.signIn(), text: "Sign in" }))));
    return;
  }
  if (!sess.signed_in) { fill(root, needSignIn(ctx, "My Perch")); return; }
  const roles = (sess.roles || []).filter((r) => r === "student" || r === "researcher");
  const both = roles.length > 1;
  const side = sess.audience || roles[0] || "student";
  const listEl = h("div", { class: "brief-list", "aria-busy": "true" }, h("div", { class: "shimmer-card" }));
  const sideWord = side === "student" ? "student" : "researcher";
  fill(root, h("div", { class: "screen my-perch" },
    h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
    h("div", { class: "title-row" },
      h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: "My Perch" }),
        h("p", { class: "page-sub", text: `Your past ${sideWord} briefs.` })),
      both ? h("div", { class: "seg", role: "group", "aria-label": "Side" },
        roles.map((r) => h("button", { type: "button", "aria-pressed": String(r === side), "data-key": `side-${r}`,
          onclick: async () => { if (r === side) return; try { await ctx.api.setAudience(r); await ctx.refresh(); renderMyPerch(root, ctx); } catch (e) { ctx.announce(e.message); } } },
        h("span", { text: r === "student" ? "Student" : "Researcher" })))) : null),
    h("h2", { class: "section-title", text: "Briefs" }), listEl));
  document.getElementById("acct-title").focus({ preventScroll: true });
  try {
    const rows = await ctx.api.myBriefs(side);
    rows.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    listEl.setAttribute("aria-busy", "false");
    fill(listEl, rows.length ? h("ul", { class: "leads" }, rows.map((b) => h("li", { class: "card lead brief-row", "data-id": b.id },
      h("div", {}, h("p", { class: "lead-title", text: side === "student" ? "Student brief" : (b.topics && b.topics.length ? b.topics.slice(0, 3).join(", ") : "Researcher brief") }),
        h("p", { class: "hint", text: `Built ${f.formatDate(b.created_at)} · ${f.plural(b.leads, "lead")} · ${b.status}` })),
      h("a", { class: "btn", href: `#/brief/${encodeURIComponent(b.id)}/routes` },
        h("span", { text: "Open" }), h("span", { class: "sr-only", text: ` the brief built ${f.formatDate(b.created_at)}` })))))
      : h("div", { class: "empty-list" }, h("p", { class: "lede", text: "No briefs yet." }),
        h("a", { class: "btn", href: side === "student" ? "#/student" : "#/" }, h("span", { text: side === "student" ? "Check my fit" : "Find a researcher" }))));
  } catch (e) {
    listEl.setAttribute("aria-busy", "false");
    fill(listEl, h("p", { class: "notice warn" }, icon("warn"), h("span", { text: e.code === "consent_required" ? "Agree to the consent first." : `Your briefs could not be loaded. ${e.message}` })));
  }
}
