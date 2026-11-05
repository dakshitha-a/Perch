// Account screens (S43): the welcome step after a first sign-in (#/welcome), the account
// page with the delete-my-data dialog (#/account) and My Perch with the past briefs (#/me).
// The consent text is whatever the server sends, shown as written (GET /auth/session).

import { evMark, fill, h, icon, sharedWarn } from "./dom.js";
import { owl } from "./owl.js";
import { profilePicks } from "./profile_picks.js";
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
    fill(root, h("div", { class: "screen welcome" },
      h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: "Welcome to Perch" }),
        h("p", { class: "page-sub", text: "Two short steps, then you are in." })),
      h("section", { class: "box", "aria-labelledby": "w1" },
        h("h2", { class: "section-title", id: "w1", text: "1. What brings you here?" }),
        row("student", "I am a student"), row("researcher", "I am a researcher"),
        h("p", { class: "hint", text: "You can pick both. Graduate students: pick Student for fellowships, and Researcher too if you have published papers." }),
        state.researcher ? h("div", { class: "oa-field" },
          h("label", { for: "oa-id", class: "big", text: "Your OpenAlex author id (optional)" }),
          h("input", { id: "oa-id", type: "text", value: state.oa, autocomplete: "off", placeholder: "A5023888391",
            "aria-describedby": "oa-hint", oninput: (e) => { state.oa = e.target.value; } }),
          h("p", { class: "note", id: "oa-hint", text: "An OpenAlex author id is an A followed by at least eight digits. You can leave this empty." })) : null),
      h("section", { class: "box", "aria-labelledby": "w2" },
        h("h2", { class: "section-title", id: "w2", text: "2. How Perch uses your CV" }),
        h("div", { class: "consent-text", tabindex: "0", role: "region", "aria-label": "Consent text" },
          // One paragraph per sentence, so it reads in steps; the words are the server's, unchanged.
          ...String(c.text || "").split(/(?<=[.!?])\s+/).filter(Boolean).map((t) => h("p", { text: t }))),
        h("label", { class: "check-row" },
          h("input", { type: "checkbox", "data-key": "agree", checked: state.agreed,
            onchange: (e) => { state.agreed = e.target.checked; draw(); } }),
          h("span", {}, h("b", { text: "I agree" })))),
      state.error ? h("p", { class: "notice error", role: "alert" }, icon("warn"), h("span", { text: state.error })) : null,
      h("div", { class: "welcome-go" },
        h("button", { class: "btn primary big", type: "button", "data-key": "continue", disabled: !ready,
          "aria-busy": state.busy ? "true" : null, onclick: submit }, h("span", { text: state.busy ? "Saving" : "Continue" })),
        !ready && !state.busy ? h("p", { class: "hint", text: !sidesDone ? "Choose at least one side to continue." : "Tick “I agree” to continue." }) : null),
      h("p", { class: "hint welcome-out" },
        h("a", { href: "#/awards", text: "Not now: browse Temple awards" }), h("span", { text: " · " }),
        h("button", { class: "linklike", type: "button", "data-key": "welcome-signout", onclick: async () => {
          try {
            const out = await ctx.api.logout();
            if (out && out.end_session_url) { location.assign(out.end_session_url); return; }
            location.assign("/");
          } catch (e) { ctx.announce(e.message); }
        }, text: "Sign out" }))));
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
  // S53: the optional picks, one block per side the account uses. Saving with both blank
  // removes the stored row.
  const picksEl = h("div", { class: "picks-list" });
  async function loadPicks() {
    let first = true;  // the legend is said once, not under each side heading
    for (const side of roles) {
      const value = { citizenship: null, residency_state: null };
      let err = null;
      try { Object.assign(value, await ctx.api.profile(side)); } catch (e) { err = e; }
      const status = h("p", { class: "hint", role: "status" });
      const save = h("button", { class: "btn", type: "button", "data-key": `picks-save-${side}`, text: "Save", onclick: async () => {
        try {
          await ctx.api.saveProfile({ citizenship: value.citizenship || null, residency_state: value.residency_state || null }, side);
          status.textContent = value.citizenship || value.residency_state ? "Saved." : "Nothing is stored.";
          ctx.announce(status.textContent);
        } catch (e) { status.textContent = e.code === "consent_required" || e.status === 403 ? "Agree to the consent first." : e.message; }
      } });
      picksEl.append(h("div", { class: "picks-side" },
        roles.length > 1 ? h("h3", { class: "mini", text: sideWord(side) }) : null,
        err ? h("p", { class: "notice warn" }, icon("warn"), h("span", { text: `These could not be loaded. ${err.message}` }))
          : [profilePicks({ prefix: `acct-${side}`, value, legend: first }), save, status]));
      first = false;
    }
  }

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
      h("p", { id: "del-help", text: "This deletes your CV and entries, your briefs, your saved awards and leads, your hand-off drafts and cover points, and your account. You will be signed out. Your key is destroyed, so nothing stored under it can be read again. After you delete your data, backups clear within 35 days. If you do nothing for 12 months, Perch deletes your data anyway." }),
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

  // ----- withdraw consent: a confirm that says what it blocks (S43 M6) -----
  const wdErr = h("p", { class: "notice error", role: "alert", hidden: true });
  const wdGo = h("button", { class: "btn danger", type: "button", id: "wd-go" }, h("span", { text: "Withdraw consent" }));
  const wdDlg = h("dialog", { class: "del-dialog", "aria-labelledby": "wd-title" },
    h("form", { method: "dialog", onsubmit: (e) => e.preventDefault() },
      h("h2", { id: "wd-title", class: "section-title", text: "Withdraw consent" }),
      h("p", { text: "Perch will stop using your CV and entries. That means no new briefs, no new documents and no model jobs on your text." }),
      h("p", { text: "It does not delete anything. You can still browse Temple awards and research funding, see what is stored and delete it. You can agree again at any time." }),
      wdErr,
      h("div", { class: "dlg-actions" },
        h("button", { class: "btn", type: "button", onclick: () => wdDlg.close() }, h("span", { text: "Cancel" })), wdGo)));
  wdDlg.addEventListener("close", () => { const o = document.getElementById("wd-open"); if (o) o.focus(); });
  wdGo.addEventListener("click", async () => {
    wdGo.disabled = true;
    try {
      await ctx.api.withdrawConsent();
      wdDlg.close();
      await ctx.refresh();
      ctx.flash("Consent withdrawn. Perch will not use your CV and entries until you agree again.", "#/account");
      renderAccount(root, ctx);
    } catch (e) {
      wdErr.hidden = false; wdErr.textContent = e.message; wdGo.disabled = false;
    }
  });

  fill(root, h("div", { class: "screen account" },
    h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
    h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: "Account and data" })),
    h("dl", { class: "fields acct-facts" },
      h("div", { class: "field" }, h("dt", { text: "Signed in as" }), h("dd", { text: sess.display_name || "your account" })),
      h("div", { class: "field" }, h("dt", { text: "Using Perch as" }), h("dd", { text: roles.map(sideWord).join(" and ") || "None chosen" })),
      sess.consent ? h("div", { class: "field" }, h("dt", { text: "Consent" }),
        h("dd", {}, h("span", { text: sess.consent.required ? "Not agreed to the current text. " : `Version ${sess.consent.accepted_version}, agreed. ` }),
          sess.consent.required
            ? h("a", { class: "btn", href: "#/welcome", "data-key": "consent-again", text: "Agree again" })
            : h("button", { class: "btn", type: "button", id: "wd-open", "data-key": "wd-open",
              onclick: () => wdDlg.showModal() }, h("span", { text: "Withdraw consent…" })))) : null),
    h("section", { class: "box", "aria-labelledby": "docs-h" },
      h("h2", { class: "section-title", id: "docs-h", tabindex: "-1", text: "Your documents" }),
      sharedWarn(ctx.session()), docsEl),
    h("section", { class: "box", "aria-labelledby": "picks-h" },
      h("h2", { class: "section-title", id: "picks-h", text: "Citizenship and state (optional)" }), picksEl),
    h("section", { class: "box danger-zone", "aria-labelledby": "del-h" },
      h("h2", { class: "section-title", id: "del-h", text: "Delete my data" }),
      h("p", { text: "Delete your CV and entries, your briefs, your saved awards and leads, your hand-off drafts and cover points, and your account. Perch also deletes your data after 12 months without use." }),
      opener),
    dlg, wdDlg));
  document.getElementById("acct-title").focus({ preventScroll: true });
  await loadDocs();
  await loadPicks();
}

// ---------- My Perch: the signed-in home ----------

const PLURAL_DOCS = (n) => `${n} other ${n === 1 ? "document" : "documents"}`;

// One row of the "Kept and saved" card. The date is written by code from the record's own field.
function keptRow(it, side, ctx, onRemove) {
  const r = it.record;
  const from = [it.saved_id ? "Saved from the list" : null,
    ...(it.kept_in || []).slice(0, 1).map((k) => `Kept in your brief of ${f.formatDate(k.built_at)}`)].filter(Boolean).join(" · ");
  const remove = it.saved_id ? h("button", { class: "btn quiet", type: "button", "data-key": `unsave-${it.saved_id}`,
    "aria-label": `Remove ${r ? (r.name || r.title || "this record") : "this record"} from the saved list`,
    onclick: () => onRemove(it) }, h("span", { text: "Remove" })) : null;
  if (!r) {
    return h("li", { class: "kept-row gone" }, h("div", { class: "kept-main" },
      h("p", { class: "hint", text: "This record is no longer in Perch’s data." })), remove);
  }
  const opp = r.kind === "opportunity";
  const title = (opp ? r.title : r.name) || (opp ? "Untitled opportunity" : "Untitled award");
  const date = r.deadline || (opp ? r.close_date : null);
  const today = f.localToday();
  let when;
  if (date && /^\d{4}-\d{2}-\d{2}/.test(date)) {
    const d = String(date).slice(0, 10);
    if (d >= today) {
      when = h("span", {}, h("span", { text: `Closes ${f.formatDate(d)}` }), h("span", { class: "rel", text: f.closesIn(f.daysBetween(today, d)) }));
    } else {
      when = h("span", {}, h("span", { text: f.formatDate(d) }),
        h("span", { class: `tag ${opp ? "closed" : "past"}`, text: opp ? "Closed" : "Past date on the page" }));
    }
  } else if (r.deadline_quote) when = h("span", { class: "quote-date", text: `The page says: “${r.deadline_quote}”` });
  else when = h("span", { class: "missing", text: "No date on the record" });
  return h("li", { class: "kept-row", "data-id": it.record_id }, h("div", { class: "kept-main" },
    h("button", { class: "title-btn", type: "button", onclick: (e) => ctx.openEvidence(r, e.currentTarget) },
      h("span", { text: title }), evMark()),
    h("div", { class: "kept-date" }, when),
    from ? h("p", { class: "kept-from", text: from }) : null), remove);
}

const briefTitle = (b, side) => {
  if (side === "student") return `Options checked ${f.formatDate(b.created_at)}`;
  return b.topics && b.topics.length ? b.topics.slice(0, 3).join(", ") : `Researcher brief, ${f.formatDate(b.created_at)}`;
};

export async function renderMyPerch(root, ctx, opts = {}) {
  const { home = false } = opts;
  const sess = ctx.session();
  document.title = "My Perch — Perch";
  if (sess.guest) {
    fill(root, h("div", { class: "screen" },
      home ? null : h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
      h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: "My Perch" }),
        h("p", { class: "page-sub", text: "Sign in to keep awards, their dates and your briefs." })),
      h("p", {}, h("a", { class: "btn primary", href: ctx.signIn(), text: "Sign in" }))));
    return;
  }
  if (!sess.signed_in) { fill(root, needSignIn(ctx, "My Perch")); return; }
  const roles = (sess.roles || []).filter((r) => r === "student" || r === "researcher");
  const both = roles.length > 1;
  const side = sess.audience || roles[0] || "student";
  const student = side === "student";
  const noun = student ? "awards" : "calls";
  const keptEl = h("div", { "aria-busy": "true" }, h("div", { class: "shimmer-card" }));
  const briefsEl = h("div", { "aria-busy": "true" }, h("div", { class: "shimmer-card" }));
  const docsEl = h("div", { "aria-busy": "true" }, h("div", { class: "shimmer-card" }));
  const browse = student ? { href: "#/awards", text: "Browse Temple awards" } : { href: "#/funding", text: "Browse funding" };
  const startHref = student ? "#/student" : "#/start";
  fill(root, h("div", { class: "screen my-perch" },
    home ? null : h("a", { class: "back", href: "#/" }, icon("back"), h("span", { text: "Back" })),
    h("div", { class: "title-row" },
      h("div", {}, h("h1", { class: "page", id: "acct-title", tabindex: "-1", text: "My Perch" }),
        h("p", { class: "page-sub", text: `Your kept ${noun}, their dates and your briefs.` })),
      both ? h("div", { class: "seg", role: "group", "aria-label": "Using Perch as" },
        roles.map((r) => h("button", { type: "button", "aria-pressed": String(r === side), "data-key": `side-${r}`,
          onclick: async () => { if (r === side) return; try { await ctx.api.setAudience(r); await ctx.refresh(); renderMyPerch(root, ctx, opts); } catch (e) { ctx.announce(e.message); } } },
        h("span", { text: r === "student" ? "Student" : "Researcher" })))) : null),
    h("div", { class: "start-row" },
      h("a", { class: "btn primary", href: student ? "#/awards" : "#/start", text: student ? "Browse Temple awards" : "Find a researcher" }),
      h("a", { class: "btn", href: student ? "#/student" : "#/funding", text: student ? "Check my fit" : "Browse funding" })),
    h("div", { class: "home-grid" },
      h("section", { class: "box home-kept", "aria-labelledby": "kept-h" }, h("h2", { class: "section-title", id: "kept-h", text: "Kept and saved" }), keptEl),
      h("section", { class: "box home-briefs", "aria-labelledby": "briefs-h" }, h("h2", { class: "section-title", id: "briefs-h", text: "Briefs" }), briefsEl),
      h("aside", { class: "box home-docs", "aria-labelledby": "docs-h" }, h("h2", { class: "section-title", id: "docs-h", text: "Your documents" }), docsEl))));
  const title = document.getElementById("acct-title");
  if (!home) title.focus({ preventScroll: true });

  const failure = (e, what) => h("p", { class: "notice warn" }, icon("warn"),
    h("span", { text: e.code === "consent_required" ? "Agree to the consent first." : `${what} could not be loaded. ${e.message}` }));

  // ----- kept and saved -----
  let items = [];
  const drawKept = () => {
    keptEl.setAttribute("aria-busy", "false");
    fill(keptEl, items.length ? h("ul", { class: "kept-list" }, items.map((it) => keptRow(it, side, ctx, remove)))
      : h("div", { class: "empty-list" }, owl("look", "owl-sm"),
        h("p", { class: "lede", text: `Nothing kept yet. Press Keep on ${student ? "an award" : "a call"} and it shows here with its date.` }),
        h("a", { class: "btn", href: browse.href, text: browse.text })));
  };
  async function remove(it) {
    try {
      await ctx.api.unsave(it.saved_id);
      // a record that is also kept in a brief stays listed, without the saved mark
      if ((it.kept_in || []).length) Object.assign(it, { saved_id: null }); else items = items.filter((x) => x !== it);
      drawKept();
      ctx.announce("Removed from the saved list.");
      const t = document.getElementById("kept-h"); if (t) { t.tabIndex = -1; t.focus(); }
    } catch (e) { ctx.announce(e.message); }
  }
  ctx.api.saved(side).then((got) => { items = got.items; drawKept(); },
    (e) => { keptEl.setAttribute("aria-busy", "false"); fill(keptEl, failure(e, "Your kept list")); });

  // ----- briefs -----
  ctx.api.myBriefs(side).then((rows) => {
    rows.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    briefsEl.setAttribute("aria-busy", "false");
    const draw = (list) => {
      briefsEl.setAttribute("aria-busy", "false");
      fill(briefsEl, list.length ? h("ul", { class: "brief-list-rows" }, list.map((b) => {
      const busy = b.status === "queued" || b.status === "running";
      const status = busy ? "Still building" : ["failed", "cancelled", "dead"].includes(b.status) ? "Stopped" : null;
      const meta = `${f.plural(b.leads, "lead")} · ${b.kept || 0} kept${b.sample_leads ? ` · ${b.sample_leads} sample` : ""}${status ? ` · ${status}` : ""}`;
      return h("li", { class: "brief-line brief-row", "data-id": b.id },
        h("div", { class: "brief-main" }, h("p", { class: "brief-title", text: briefTitle(b, side) }), h("p", { class: "brief-meta", text: meta }),
          status === "Stopped" && b.error ? h("p", { class: "brief-meta brief-error", "data-key": "brief-error", text: String(b.error) }) : null),
        h("div", { class: "brief-acts" },
          h("a", { class: "btn", href: `#/brief/${encodeURIComponent(b.id)}/routes` },
            h("span", { text: "Open" }), h("span", { class: "sr-only", text: ` the brief built ${f.formatDate(b.created_at)}` })),
          h("a", { class: "quiet-link", href: `#/rerun/${encodeURIComponent(b.id)}`, "aria-label": "Change details and run again", text: "Run again" }),
          busy ? h("button", { class: "btn quiet", type: "button", "data-key": `stop-${b.id}`, onclick: () => stopBrief(b.id) }, icon("stop"), h("span", { text: "Stop" })) : null));
    })) : h("div", { class: "empty-list" }, h("p", { class: "lede", text: "No briefs yet." }),
      h("a", { class: "btn", href: startHref, text: student ? "Check my fit" : "Find a researcher" })));
    };
    async function stopBrief(id) {
      const btn = briefsEl.querySelector(`[data-key="stop-${CSS.escape(id)}"]`);
      if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
      try {
        await ctx.api.cancelBrief(id);
        const fresh = await ctx.api.myBriefs(side);
        fresh.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
        draw(fresh);
        const open = briefsEl.querySelector(`[data-id="${CSS.escape(id)}"] a.btn`);
        if (open) open.focus({ preventScroll: true });
        ctx.announce("Stopped. Run again builds a new one.");
      } catch (e) {
        if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
        ctx.announce(e.message);
      }
    }
    draw(rows);
  }, (e) => { briefsEl.setAttribute("aria-busy", "false"); fill(briefsEl, failure(e, "Your briefs")); });

  // ----- documents -----
  ctx.api.docs(side).then((docs) => {
    docsEl.setAttribute("aria-busy", "false");
    const cv = docs.find((d) => d.kind === "cv");
    const others = docs.length - (cv ? 1 : 0);
    fill(docsEl,
      cv ? h("p", { class: "doc-line", text: `CV stored: ${cv.name || cv.label || "CV"}` })
        : h("p", {}, h("span", { text: "No CV stored. " }), h("a", { class: "quiet-link", href: startHref, text: "Add your CV" })),
      others > 0 ? h("p", { class: "hint", text: PLURAL_DOCS(others) }) : null,
      h("p", {}, h("a", { class: "quiet-link", href: "#/account", text: "Manage in Account and data" })));
  }, (e) => { docsEl.setAttribute("aria-busy", "false"); fill(docsEl, failure(e, "Your documents")); });
}
