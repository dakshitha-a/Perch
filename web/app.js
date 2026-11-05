// Perch web app: Find -> Profile -> Routes, with the evidence panel (docs/design/UI.md).
// Plain DOM, no build step. Every value from a record goes in through textContent.

import { liveApi, replayApi } from "./api.js";
import { add, evMark, fill, h, icon } from "./dom.js";
import { renderHelp } from "./help.js";
import { compareOffices, loadCompare, renderCompare } from "./compare.js";
import { coverBlock, coverListLine } from "./cover.js";
import { renderHandoff } from "./handoff.js";
import { renderScout } from "./scout.js";
import * as f from "./format.js";
import { hop, owl, poke, setOwl } from "./owl.js";
import { renderAccount, renderMyPerch, renderWelcome } from "./account.js";
import { renderList, renderSamples } from "./browse.js";
import { isStudent, keptWords, matchPill, resetStudent, renderStudentStart, studentCompare, studentProfile, studentRoutes, STUDENT_ROUTES } from "./student.js";

const api = window.PERCH_REPLAY ? replayApi(window.PERCH_REPLAY) : liveApi(window.PERCH_API || "");
// The server no longer knows the session (a guest session lasts an hour): go to the start
// and say so on the landing page, with the two ways on.
api.onExpired = (wasGuest) => {
  setTimeout(() => {
    stopPolling();
    S.session = { signed_in: false };
    S.notice = wasGuest ? "Your guest session has ended. Nothing was saved."
      : "You were signed out. Sign in again to carry on.";
    S.noticeEnded = true;
    drawWho();
    drawBanner();
    announce(S.notice);
    go("#/");
  }, 0);
};
const POLL_MS = 1500;
const TABS = ["routes", "profile", "compare", "scout"]; // the order of the tabs (S24)
const SOURCES = { openalex: "OpenAlex", grants_gov: "Grants.gov", nih_reporter: "NIH RePORTER",
  nsf: "NSF Award Search", perch: "Perch", user: "Your own document",
  temple_sdfa: "Temple Scholar Development and Fellowships Advising (public list)",
  synthetic: "SYNTHETIC sample corpus (invented, not a real scholarship)" };
const KINDS = { opportunity: "Funding opportunity", work: "Paper", award: "Public award",
  researcher: "Researcher", organisation: "Organisation", lead: "Industry lead",
  user: "Your own document", scholarship: "Scholarship or fellowship" };
const SIGNALS = { citing_works: "They cite your papers", sbir_sttr: "NIH SBIR/STTR awards",
  topic_works: "They publish in your topics" };

const S = {
  find: { q: "", busy: false, error: null, candidates: null, searched: "", explain: true,
    minAmount: "", direction: "", include: "", exclude: "", stage: "",
    picked: null, building: false, docs: null, docIds: new Set() },
  who: "s", // the landing's Student | Researcher control; Student comes first (S43)
  session: { signed_in: false }, // the last GET /auth/session answer; the page never guesses
  flash: null, // a message for the banner slot, e.g. "Your data was deleted."
  notice: null, // a message for the landing, e.g. that the guest session ended
  noticeEnded: false, // the notice is the "session ended" one, with Start again and Sign in
  brief: null, // last GET /briefs payload
  briefId: null,
  tab: "routes",
  sort: "order",
  route: "A", // Routes tab: "A" grants, "B" industry
  filter: null, // Routes, grants: {kind: "agency" | "code", value} from the leads' own values (U25)
  open: new Set(), // lead ids whose "Why it fits" is open
  shut: new Set(), // with the user's own documents it starts open; ids the reader closed
  stepsOpen: false,
  pollTimer: null,
  gen: 0, // bumps whenever the brief on screen changes; stale polls drop out
  failedPolls: 0,
  seen: { explained: 0, stagesDone: 0 },
  startedHere: false,
  listWithheld: false, // two or more flagged cards on view: the list note says it once (S50 V5)
  stoppedId: null, // the brief this page asked to stop, so its failed state reads "Stopped" (S50 Q6)
};

const $ = (sel) => document.querySelector(sel);
const main = () => $("#main");

function announce(msg) {
  const live = $("#live");
  live.textContent = "";
  setTimeout(() => { live.textContent = msg; }, 30);
}

// ---------- routing ----------

function screen(name) {
  document.body.dataset.screen = name;
  syncHomeLink();
}

// The header's My Perch link says when My Perch is the screen shown (S49 P8).
function syncHomeLink() {
  const a = $("#my-perch-link");
  if (!a) return;
  if (document.body.dataset.screen === "home") a.setAttribute("aria-current", "page");
  else a.removeAttribute("aria-current");
}

function leaveBrief() {
  stopPolling();
  S.briefId = null;
  S.brief = null;
  closeEvidence();
}

function route() {
  if (location.hash && !location.hash.startsWith("#/")) return; // in-page anchors, e.g. the skip link
  const parts = location.hash.split("?")[0].replace(/^#\/?/, "").split("/").filter(Boolean);
  const onHelp = parts[0] === "help";
  if (onHelp) $("#help").setAttribute("aria-current", "page");
  else $("#help").removeAttribute("aria-current");
  document.body.classList.toggle("on-help", onHelp);
  if (onHelp) {
    leaveBrief();
    screen("help");
    document.title = "Help — Perch";
    renderHelp(main(), { back: S.lastHash && S.lastHash !== location.hash ? S.lastHash : "#/" });
    window.scrollTo(0, 0);
    // Focus lands on the page heading, as on other screens (S50 A1), not on the whole <main>,
    // which drew a focus ring round the page (S50 QA).
    const h1 = main().querySelector("h1");
    if (h1) { h1.tabIndex = -1; h1.focus({ preventScroll: true }); } else main().focus({ preventScroll: true });
    return;
  }
  S.lastHash = location.hash || "#/";
  if (location.hash && location.hash !== "#/") { S.notice = null; S.noticeEnded = false; }
  if (!location.hash || location.hash === "#/") drawBanner();
  else if (S.flash && S.flashFor !== location.hash) { S.flash = null; drawBanner(); }
  const sess = S.session;
  // A new account, or one whose consent text changed, finishes the welcome screen first.
  // The public lists and the account page need no agreement, so they stay open (S43 S12, M6).
  const OPEN = ["welcome", "account", "awards", "funding", "samples"];
  if (sess.signed_in && (sess.needs_welcome || (sess.consent && sess.consent.required))
      && !OPEN.includes(parts[0])) {
    leaveBrief();
    goReplace(`#/welcome${returnQuery()}`);
    return;
  }
  const rt = { api, go, goReplace, announce, session: () => S.session, refresh: refreshSession,
    signIn: signInHref, flash, openEvidence: (rec, opener) => openEvidence(rec && rec.id ? rec.id : rec, opener), closeEvidence };
  if (parts[0] === "welcome") {
    leaveBrief();
    screen("form");
    renderWelcome(main(), rt, new URLSearchParams(location.hash.split("?")[1] || "").get("return_to"));
    window.scrollTo(0, 0);
    return;
  }
  if (parts[0] === "account") {
    leaveBrief();
    screen("form");
    renderAccount(main(), rt);
    window.scrollTo(0, 0);
    return;
  }
  // My Perch is a signed-in user's home (S49 P-D1, U41): #/ and #/me both show it.
  if (parts[0] === "me" || (!parts.length && sess.signed_in && api.mode !== "replay")) {
    leaveBrief();
    screen("home");
    document.title = "My Perch — Perch";
    renderMyPerch(main(), rt, { home: true });
    window.scrollTo(0, 0);
    return;
  }
  if (parts[0] === "awards" || parts[0] === "funding") {
    leaveBrief();
    screen("list");
    window.scrollTo(0, 0);
    renderList(main(), { ...rt, audience: parts[0] === "awards" ? "student" : "researcher" });
    return;
  }
  if (parts[0] === "samples") {
    leaveBrief();
    screen("list");
    window.scrollTo(0, 0);
    renderSamples(main(), { ...rt, audience: parts[1] === "researcher" ? "researcher" : "student" });
    return;
  }
  if (parts[0] === "student") {
    leaveBrief();
    screen("form");
    window.scrollTo(0, 0);
    renderStudentStart(main(), { api, go, announce, session: S.session, signIn: signInHref, refresh: refreshSession });
    return;
  }
  if (parts[0] === "find") {
    leaveBrief();
    screen("form");
    renderPick();
    window.scrollTo(0, 0);
    return;
  }
  if (parts[0] === "rerun" && parts[1]) {
    leaveBrief();
    screen("form");
    rerun(decodeURIComponent(parts[1]));
    return;
  }
  if (parts[0] === "brief" && parts[1]) {
    const id = decodeURIComponent(parts[1]);
    screen("brief");
    S.tab = TABS.includes(parts[2]) ? parts[2] : S.tab;
    if (id !== S.briefId) openBrief(id);
    else renderPanel();
    return;
  }
  leaveBrief();
  screen("landing");
  window.scrollTo(0, 0);
  renderFind();
}

// "?return_to=..." for the welcome screen: where the visitor was headed.
function returnQuery() {
  const here = location.hash && !location.hash.startsWith("#/welcome") ? `/${location.hash}` : "";
  return here && here !== "/#/" ? `?return_to=${encodeURIComponent(here)}` : "";
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

// For "nothing to show here" redirects: replace the history entry instead of adding one,
// so the browser's Back keeps moving back instead of landing here again (S27).
function goReplace(hash) {
  if (location.hash === hash) route();
  else location.replace(hash);
}

// ---------- header, banner, session (S43) ----------

async function refreshSession() {
  if (!api.session) return S.session;
  try { S.session = await api.session(); } catch { S.session = { signed_in: false }; }
  drawWho();
  drawBanner();
  return S.session;
}

// The sign-in link: the identity provider's own page, then back to where the visitor was.
function signInHref(hash = location.hash || "#/") {
  return `/auth/login?return_to=${encodeURIComponent(`/${hash}`)}`;
}

function flash(text, forHash) {
  S.flash = text;
  S.flashFor = forHash || location.hash || "#/";
  drawBanner();
  announce(text);
}

// The banner slot: a guest session says so on every screen; a one-time message shows on the
// screen it was meant for. It is the chip colour, not amber: amber means sample data.
function drawBanner() {
  if (api.mode === "replay") return;
  const b = $("#banner");
  const sess = S.session;
  const lines = [];
  if (sess.guest) {
    lines.push(h("p", { class: "banner-line", "data-key": "guest-banner" }, icon("info"),
      h("span", { text: sess.notice || "Nothing is saved in a guest session. It ends in an hour." }),
      h("a", { href: signInHref(), text: "Sign in" })));
  }
  if (S.flash) {
    // S50 (V26): a done thing ("Your data was deleted.") gets a check; anything else, info.
    lines.push(h("p", { class: "banner-line", role: "status", "data-key": "flash-banner" },
      icon(/^Your data was deleted\./.test(S.flash) ? "check" : "info"),
      h("span", { text: S.flash }),
      h("button", { class: "x", type: "button", "aria-label": "Dismiss",
        onclick: () => { S.flash = null; drawBanner(); }, text: "×" })));
  }
  b.hidden = !lines.length;
  b.classList.add("neutral");
  fill(b, ...lines);
}

const firstWord = (name) => {
  const w = String(name || "").trim().split(/\s+/)[0] || "Account";
  return w.length > 10 ? `${w.slice(0, 9)}…` : w;
};

function drawWho() {
  const who = $("#acct-slot");
  if (api.mode === "replay") return;
  const sess = S.session;
  document.body.classList.toggle("signed-in", Boolean(sess.signed_in));
  if (!sess.signed_in) {
    // A guest signs in from the banner's link, so the header has no second one (S49 U17).
    fill(who,
      sess.guest ? h("span", { class: "chip guest-chip", text: "Guest" }) : null,
      S.signinDown || sess.guest ? null : h("a", { class: "btn quiet", id: "sign-in", href: signInHref(), text: "Sign in" }));
    return;
  }
  const roles = sess.roles || [];
  const both = roles.includes("student") && roles.includes("researcher");
  const other = sess.audience === "student" ? "researcher" : "student";
  const close = (refocus) => {
    $("#acct-menu").hidden = true;
    $("#acct-btn").setAttribute("aria-expanded", "false");
    if (refocus) $("#acct-btn").focus();
  };
  const item = (el) => h("li", {}, el);
  const menu = h("ul", { id: "acct-menu", class: "acct-menu", hidden: true },
    item(h("a", { href: "#/", onclick: () => close(false), text: "My Perch" })),
    item(h("a", { href: "#/account", onclick: () => close(false), text: "Account and data" })),
    both ? item(h("button", { type: "button", "data-key": "switch-side", onclick: async () => {
      try {
        await api.setAudience(other);
        await refreshSession();
        close(false);
        S.who = other === "student" ? "s" : "r";
        announce(`Switched to the ${other} side.`);
        go("#/");
        route();
      } catch (e) { announce(e.message); }
    }, text: `Switch to the ${other} side` })) : null,
    item(h("button", { type: "button", id: "menu-theme", onclick: () => $("#theme").click(), text: "Theme" })),
    item(h("button", { type: "button", "data-key": "sign-out", onclick: async () => {
      try {
        const out = await api.logout();
        S.session = { signed_in: false };
        drawWho();
        drawBanner();
        if (out && out.end_session_url) { location.assign(out.end_session_url); return; }
        go("#/");
        route();
      } catch (e) { announce(e.message); }
    }, text: "Sign out" })));
  const btn = h("button", { id: "acct-btn", class: "btn quiet acct-btn", type: "button", "aria-expanded": "false",
    "aria-controls": "acct-menu", "aria-label": `Account: ${sess.display_name || "signed in"}`,
    onclick: () => {
      const open = menu.hidden;
      menu.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      if (open) menu.querySelector("a, button").focus();
    } }, icon("person"), h("span", { class: "acct-name", text: firstWord(sess.display_name) }));
  const wrap = h("div", { class: "acct",
    onkeydown: (e) => { if (e.key === "Escape" && !menu.hidden) { e.stopPropagation(); close(true); } },
    onfocusout: (e) => { if (!menu.hidden && !wrap.contains(e.relatedTarget)) close(false); } }, btn, menu);
  // At 480 px and wider My Perch has its own link; under that the menu holds it (S49 P8).
  fill(who, h("a", { class: "btn quiet", id: "my-perch-link", href: "#/", text: "My Perch" }), wrap);
  syncHomeLink();
  syncThemeItem();
}

// The theme button also lives in the account menu, where a phone has room for it.
function syncThemeItem() {
  const item = $("#menu-theme");
  if (item) item.textContent = `Theme: ${$("#theme .theme-word").textContent}`;
}

// ---------- Landing (S24): Scout on the branch, the headline, Researcher | Student ----------

function keepFocus(render) {
  const a = document.activeElement;
  const key = a && (a.id || a.dataset.key);
  render();
  if (!key) return;
  const t = document.getElementById(key) || main().querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (t && t !== document.activeElement) t.focus({ preventScroll: true });
}

// A segmented control: a radiogroup of two buttons, arrow keys move the choice.
function seg(label, value, options, pick) {
  const keys = options.map((o) => o[0]);
  return h("div", { class: "seg", role: "radiogroup", "aria-label": label },
    options.map(([key, text, extra]) => h("button", { type: "button", role: "radio", "data-key": `seg-${key}`,
      "aria-checked": String(value === key), tabindex: value === key ? "0" : "-1",
      onclick: () => pick(key),
      onkeydown: (e) => {
        if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
        e.preventDefault();
        const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : keys.length - 1;
        const next = keys[(keys.indexOf(key) + step) % keys.length];
        pick(next);
        setTimeout(() => { const b = document.querySelector(`[data-key="seg-${next}"]`); if (b) b.focus(); }, 0);
      } }, h("span", { text }), extra || null)));
}

function renderFind() {
  document.title = "Perch";
  const F = S.find;
  const input = h("input", { id: "q", name: "q", type: "search", autocomplete: "off",
    enterkeyhint: "search", placeholder: matchMedia("(max-width: 419px)").matches ? "Name, ORCID or OpenAlex ID"
      : "Researcher name, ORCID iD or OpenAlex ID",
    "aria-describedby": "q-hint", "aria-invalid": F.empty ? "true" : null, value: F.q,
    oninput: (e) => { F.q = e.target.value; const was = F.empty; F.empty = false;
      if (was) keepFocus(renderFind); } });
  const researcher = h("form", { role: "search", onsubmit: (e) => { e.preventDefault(); search(); } },
    h("label", { for: "q", class: "sr-only", text: "Find a Temple researcher" }),
    h("div", { class: "searchbox" }, input,
      h("button", { class: "btn primary", type: "submit", disabled: F.busy,
        "aria-busy": F.busy ? "true" : null }, h("span", { text: F.busy ? "Searching" : "Find" }))),
    h("div", { class: "hint-row" },
      // F25: an empty Find says what to type, in the hint the box points to.
      h("span", { id: "q-hint", class: F.empty ? "field-error" : null,
        text: F.empty ? "Type a name, ORCID iD or OpenAlex ID." : "Names search Temple authors; an ID finds anyone." }),
      h("details", { class: "more-opts" }, h("summary", { "data-key": "more-opts", text: "What else you can add" }),
        h("p", { text: "After you pick the person, you can tell Perch where your research is going, keywords to search for or leave out, a career stage and a smallest award size. All of it is optional." }))));
  const sess = S.session;
  const replay = api.mode === "replay";
  // S51 (D4): while accounts are not open, a visitor who is not signed in starts the guest
  // sample from the second button, as when sign-in is down. The header keeps its Sign in.
  const closed = !sess.signed_in && !sess.guest && sess.accounts_open === false;
  // The landing buttons and the guest line (S43).
  const fitButton = sess.signed_in
    ? h("button", { class: "btn", type: "button", "data-key": "fit", onclick: () => go("#/student") },
      h("span", { text: "Check my fit with my CV" }))
    : sess.guest
      ? h("button", { class: "btn", type: "button", "data-key": "fit", onclick: () => go("#/student") },
        h("span", { text: "Try a sample student" }))
      : S.signinDown || closed
        // Sign-in is unavailable (S43 M1) or accounts are closed (S51 D4): the guest sample instead.
        ? h("button", { class: "btn", type: "button", "data-key": "fit", disabled: S.guestBusy, onclick: startGuest },
          h("span", { text: "Try a sample student" }))
        : h("a", { class: "btn", "data-key": "fit", href: signInHref("#/student") },
          h("span", { text: "Check my fit with my CV" }));
  const guestLine = !sess.signed_in && !sess.guest && !replay
    ? h("p", { class: "guest-line hint" }, h("span", { text: "No account? " }),
      h("button", { class: "linkish", type: "button", "data-key": "guest-start", disabled: S.guestBusy,
        onclick: startGuest }, h("span", { text: "Try it as a guest" })),
      h("span", { text: ". Nothing is saved." })) : null;
  const student = h("div", { class: "student-go" },
    h("a", { class: "btn primary", "data-key": "browse-awards", href: replay ? null : "#/awards",
      "aria-disabled": replay ? "true" : null }, h("span", { text: "Browse Temple awards" })),
    replay ? h("span", { class: "hint", text: "The preview has no server." }) : fitButton,
    replay ? null : exampleSlot("student"),
    // With sign-in down, "Try a sample student" is already the guest path (S49 U19, R5).
    S.signinDown || closed ? null : guestLine);
  const browseFunding = replay ? null : h("a", { class: "quiet-link", "data-key": "browse-funding", href: "#/funding" },
    h("span", { text: "Browse funding" }));
  fill(main(), h("div", { class: "landing" },
    heroArt(),
    h("h1", { text: "Find funding that fits." }),
    // The sub-line (S43).
    h("p", { class: "lede", text: "Temple scholarships and research funding, every claim linked to its record." }),
    S.notice ? h("div", { class: `notice ${S.noticeEnded ? "info" : "warn"} notice-ended`, role: "status" }, icon("warn"),
      h("p", { text: S.notice }),
      S.noticeEnded ? h("button", { class: "btn", type: "button", "data-key": "start-again", onclick: startGuest },
        h("span", { text: "Start again" })) : null,
      S.noticeEnded ? h("a", { class: "btn", href: signInHref(), text: "Sign in" }) : null,
      h("button", { class: "x", type: "button", "aria-label": "Dismiss", "data-key": "notice-close",
        onclick: () => { S.notice = null; S.noticeEnded = false; keepFocus(renderFind); }, text: "×" })) : null,
    seg("Who is searching", S.who, [["s", "Student"], ["r", "Researcher"]], (k) => { S.who = k; keepFocus(renderFind); }),
    S.who === "s" ? student : [researcher,
      replay ? null : h("div", { class: "landing-links" }, exampleSlot("researcher"), browseFunding), guestLine],
    F.error ? h("div", { class: "notice error", role: "alert" }, icon("warn"), h("p", { text: F.error })) : null));
}

// "See an example brief" (S50 Q22): the slot is drawn empty and filled only when the server
// holds that side's example file, so the landing moves by one line at most.
function exampleSlot(side) {
  const slot = h("span", { class: "example-slot" });
  api.exampleAvailable(side).then((ok) => {
    if (!ok || !slot.isConnected) return;
    fill(slot, h("a", { class: "quiet-link", "data-key": "example-brief", href: side === "student" ? "example.html?side=student" : "example.html" },
      h("span", { text: "See an example brief" })));
  });
  return slot;
}

// "Try it as a guest": a session of one hour on the side the visitor chose.
async function startGuest() {
  if (S.guestBusy) return;
  S.guestBusy = true;
  try {
    await api.startGuest(S.who === "s" ? "student" : "researcher");
    S.notice = null;
    S.noticeEnded = false;
    await refreshSession();
    announce("Guest session started. Nothing is saved in it.");
  } catch (e) {
    S.find.error = e.message;
  }
  S.guestBusy = false;
  keepFocus(renderFind);
}

function heroArt() {
  // A branch at dusk with Scout on it. Decorative; Scout reacts to taps.
  const wrap = h("div", { class: "hero-art", "aria-hidden": "true" });
  wrap.innerHTML = `<svg class="scene" viewBox="0 0 320 150" focusable="false">
    <circle class="moon" cx="262" cy="38" r="18"/>
    <circle class="moon-cut" cx="271" cy="32" r="16"/>
    <circle class="star" cx="214" cy="22" r="1.6"/><circle class="star" cx="300" cy="78" r="1.3"/>
    <circle class="star" cx="236" cy="64" r="1.1"/>
    <path class="branch" d="M0 120 C60 112 120 118 180 110 C220 105 260 108 320 96"/>
    <path class="twig" d="M150 114 C160 100 172 94 186 92"/>
    <path class="leaf" d="M186 92 c8 -10 20 -8 24 -4 c-8 8 -18 9 -24 4z"/>
    <path class="leaf" d="M60 116 c-4 -12 2 -20 8 -22 c4 10 0 18 -8 22z"/>
    <path class="leaf" d="M240 104 c6 -9 16 -9 20 -6 c-6 7 -15 9 -20 6z"/>
  </svg>`;
  const o = owl("idle", "owl-hero", { button: true, copy: true });
  o.setAttribute("aria-label", "Scout, the owl");
  wrap.removeAttribute("aria-hidden");
  wrap.querySelector("svg").setAttribute("aria-hidden", "true");
  wrap.append(o);
  return wrap;
}

async function search() {
  const F = S.find;
  const q = F.q.trim();
  if (!q) {  // F25: say what is missing, not nothing
    F.empty = true;
    if (location.hash !== "#/find") keepFocus(renderFind);
    const box = $("#q");
    if (box) box.focus();
    announce("Type a name, ORCID iD or OpenAlex ID.");
    return;
  }
  const oid = (q.match(ORCID) || [])[1];
  if (oid && !f.orcidOk(oid)) { // checked before any lookup (Q18)
    Object.assign(F, { busy: false, candidates: [], searched: q, picked: null, badOrcid: true, badId: false, unknownId: false,
      error: "That is not a valid ORCID iD: its last character does not match the rest. Check it on orcid.org." });
    announce(F.error);
    if (location.hash === "#/find") renderPick(); else go("#/find");
    const t = $("#pick-title");
    if (t) t.focus();
    return;
  }
  if (AID_TRY.test(q) && !AID_OK.test(q)) { // R5: "A12" is refused before any lookup
    Object.assign(F, { busy: false, candidates: [], searched: q, picked: null, badOrcid: false, badId: true, unknownId: false,
      error: "An OpenAlex author ID is an A followed by at least eight digits. Check it, or search by name or ORCID iD." });
    announce(`That is not an OpenAlex author ID. ${F.error}`);
    if (location.hash === "#/find") renderPick(); else go("#/find");
    const t = $("#pick-title");
    if (t) t.focus();
    return;
  }
  Object.assign(F, { busy: true, error: null, candidates: null, searched: q, picked: null, badOrcid: false, badId: false, unknownId: false });
  keepFocus(location.hash === "#/find" ? renderPick : renderFind);
  try {
    const r = await api.resolve(q);
    F.candidates = r.candidates || [];
  } catch (e) {
    // The server's plain sentence for an id it refuses or OpenAlex does not know (R5).
    if (e.status === 404 || e.status === 422) { F.badId = e.status === 422; F.unknownId = e.status === 404; }
    F.error = e.status === 0 || e.status === 404 || e.status === 422 ? e.message
      : `OpenAlex could not be searched: ${e.message} Check the spelling or try an ORCID iD.`;
  }
  F.busy = false;
  const n = (F.candidates || []).length;
  // An exact OpenAlex ID or ORCID iD with one Temple match needs no "This is the one"
  // (review W1). An ID finds anyone, so a match outside Temple always asks first (Q18).
  if (n === 1 && EXACT_ID.test(q) && atTemple(F.candidates[0])) {
    F.picked = F.candidates[0];
    announce("One match for that ID. Ready to build the brief.");
  } else if (F.candidates) announce(n ? `${f.plural(n, "match", "matches")} found.` : "No match found.");
  if (location.hash === "#/find") renderPick(); else go("#/find");
  const t = $("#pick-title");
  if (t) t.focus();
}

// ---------- Researcher 2: pick the person, then optional context ----------

const CTX_FIELDS = ["direction", "include", "exclude", "cv", "proposal"];
const EXACT_ID = /^(?:https?:\/\/(?:openalex\.org\/(?:authors\/)?|orcid\.org\/))?(?:A\d{6,}|\d{4}-\d{4}-\d{4}-\d{3}[\dX])$/i;
const ORCID = /^(?:https?:\/\/orcid\.org\/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$/i;
// An OpenAlex author id typed in the box, and the shape a real one has (R5; the server's
// perch.sources.openalex.author_id_ok).
const AID_TRY = /^(?:https?:\/\/(?:api\.)?openalex\.org\/(?:authors\/)?)?A\d+$/i;
const AID_OK = /^(?:https?:\/\/(?:api\.)?openalex\.org\/(?:authors\/)?)?A\d{8,}$/i;
const atTemple = (c) => (c.institutions || []).some((i) => /temple university/i.test(i));

function renderPick() {
  const F = S.find;
  if (!F.candidates && !F.error && !F.busy) { goReplace("#/start"); return; }
  document.title = "Pick the researcher — Perch";
  const c = F.picked;
  const list = c ? [c] : (F.candidates || []);
  const n = (F.candidates || []).length;
  const title = c ? "Ready to build the brief." : F.busy ? "Searching OpenAlex…"
    : F.badOrcid ? "That is not a valid ORCID iD."
    : F.badId ? "That is not an OpenAlex author ID."
    : F.unknownId ? "No OpenAlex author has that ID."
    : !n ? `No Temple University author matches “${F.searched}”.`
      : n === 1 ? "Is this the right person?" : "Which one is the right person?";
  const note = once(title, F.error);
  const sub = c ? "Add anything below to steer it, or build it now."
    : F.busy ? "" : !n ? ["Try the name as it appears on papers, or paste an ORCID iD, which looks like ", h("span", { class: "nowrap", text: "0000-0000-0000-0000" }), "."]
      : n === 1 && !atTemple(F.candidates[0]) ? "This profile does not list Temple University. An ID finds anyone, so check that it is the right person. Nothing runs until you pick it."
        : `${f.plural(n, "Temple author", "Temple authors")} in OpenAlex ${n === 1 ? "matches" : "match"}. Nothing runs until you pick one.`;
  const back = c
    ? h("div", { class: "back-row" },
      h("button", { class: "back btn quiet", type: "button", "data-key": "unpick",
        onclick: () => { F.picked = null; renderPick(); const t = $("#pick-title"); if (t) t.focus(); } },
      icon("back"), h("span", { text: "Back to the matches" })),
      // D4: a signed-in user may start over with another person.
      S.session.signed_in ? h("a", { class: "quiet-link", "data-key": "choose-else", href: "#/start" },
        h("span", { text: "Choose someone else" })) : null)
    : h("a", { class: "back", href: "#/start" }, icon("back"), h("span", { text: "Back" }));
  const again = c ? null : h("form", { role: "search", onsubmit: (e) => { e.preventDefault(); search(); } },
    h("label", { for: "q", class: "sr-only", text: "Find a Temple researcher" }),
    h("div", { class: "searchbox small" },
      h("input", { id: "q", type: "search", value: F.q, autocomplete: "off", oninput: (e) => { F.q = e.target.value; } }),
      h("button", { class: "btn", type: "submit", disabled: F.busy, text: F.busy ? "Searching" : "Search again" })));
  fill(main(), h("div", { class: "screen" },
    back, again,
    h("div", { class: "title-row" },
      h("div", {}, h("h1", { class: "page", id: "pick-title", tabindex: "-1", text: title }),
        sub ? h("p", { class: "page-sub" }, sub) : null),
      c ? h("div", { class: "build-box fade-in" }, buildButton(c, "build")) : null),
    note ? h("div", { class: "notice error", role: "alert" }, icon("warn"), h("p", { text: note })) : null,
    F.busy ? h("div", { class: "shimmer-card" }) : null,
    list.length ? h("ul", { class: "cand-list" }, list.map((x, i) => candidateCard(x, i === 0 && !c && n > 1))) : null,
    c ? cvBox() : null,
    c ? contextPanel(c) : null,
    // S50 (V32, Q13): a second Build button where the form ends, so a long form needs no scroll back.
    c ? h("div", { class: "build-foot" }, buildButton(c, "build-foot")) : null));
}

function buildButton(c, key) {
  const F = S.find;
  return h("button", { class: "btn primary big", type: "button", "data-key": key, disabled: F.building,
    onclick: () => build(c) }, h("span", { text: F.building ? "Starting" : "Build brief" }));
}

// An error that opens with the heading's own words says the rest only (R15).
function once(title, error) {
  const head = String(title).replace(/\.$/, "");
  if (!error || !error.startsWith(head)) return error;
  const rest = error.slice(head.length).replace(/^[.:;,]\s*/, "").trim();
  return rest ? rest[0].toUpperCase() + rest.slice(1) : null;
}

function candidateCard(c, best) {
  const id = f.shortId(c.id);
  const chosen = S.find.picked === c;
  const temple = atTemple(c);
  const meta = [
    (c.institutions || []).filter((i) => !/temple university/i.test(i)).join(", ") || null,
    c.works_count != null ? `${c.works_count.toLocaleString("en-US")} ${c.works_count === 1 ? "work" : "works"}` : null, // R14
    c.cited_by_count != null ? `${c.cited_by_count.toLocaleString("en-US")} ${c.cited_by_count === 1 ? "citation" : "citations"}` : null,
    `OpenAlex ${id}`].filter(Boolean);
  return h("li", { class: `cand${chosen ? " chosen fade-in" : best ? " best" : ""}` },
    h("div", { class: "cand-body" },
      h("div", { class: "cand-top" }, h("h2", { text: c.display_name }),
        temple ? h("span", { class: "temple", text: "Temple University" }) : null),
      h("p", { class: "cand-meta2" }, meta.join(" · "),
        c.orcid ? [" · ", h("a", { href: f.safeUrl(c.orcid), target: "_blank", rel: "noopener",
          text: `ORCID ${c.orcid.replace(/^https?:\/\/orcid\.org\//, "")}` })] : null),
      c.topics && c.topics.length ? h("ul", { class: "topics", "aria-label": "OpenAlex topics" },
        c.topics.slice(0, 3).map((t) => h("li", { text: t.display_name }))) : null),
    chosen ? h("span", { class: "picked-mark" }, icon("keep"), h("span", { text: "Selected" }))
      : h("button", { class: "btn outline", type: "button", "data-key": `pick-${id}`,
        onclick: () => { S.find.picked = c; renderPick(); const t = $("#pick-title"); if (t) t.focus(); } },
      h("span", { text: "This is the one" }), h("span", { class: "sr-only", text: `: ${c.display_name}` })));
}

function contextPanel(c) {
  const F = S.find;
  const set = (k) => (e) => { F[k] = e.target.value; };
  // Folded under the one Build button (review W1); it opens by itself once it holds anything.
  const filled = ["direction", "include", "exclude"].some((k) => F[k].trim()) || F.stage || F.minAmount;
  return h("details", { class: "more-panel fade-in", open: F.moreOpen || Boolean(filled),
    ontoggle: (e) => { F.moreOpen = e.target.open; } },
    h("summary", { "data-key": "more-ctx" }, h("h2", { id: "more-h", text: "Tell Perch more (optional)" })),
    h("div", { class: "more-body" },
    h("p", { class: "page-sub", text: "Everything here steers the search. All of it is optional." }),
    // S50 (Q31): Explain each lead sits with the other options; it stays ticked by default.
    h("label", { class: "check explain-check" },
      h("input", { type: "checkbox", "data-key": "explain", checked: F.explain, onchange: (e) => { F.explain = e.target.checked; } }),
      h("span", {}, h("b", { text: "Explain each lead" }),
        h("span", { class: "hint", text: " A model writes a short, cited reason for every lead. This is the slow step." }))),
    h("div", { class: "box-grid" },
      h("div", { class: "box" },
        h("label", { class: "big", for: "ctx-direction", text: "Where your research is going" }),
        h("textarea", { id: "ctx-direction", rows: 4, maxlength: 1000, placeholder: "A sentence or two", value: F.direction, oninput: set("direction") })),
      h("div", { class: "box" },
        h("label", { class: "big", for: "ctx-include", text: "Keywords to search for" }),
        h("input", { id: "ctx-include", type: "text", placeholder: "Comma-separated", value: F.include, oninput: set("include") }),
        h("label", { class: "big", for: "ctx-exclude", text: "Keywords to leave out" }),
        h("input", { id: "ctx-exclude", type: "text", placeholder: "Comma-separated", value: F.exclude, oninput: set("exclude"),
          "aria-describedby": "exc-hint" }),
        h("p", { class: "note", id: "exc-hint", text: "Opportunities that mention one of these in the title or description are left out." })),
      h("div", { class: "box" },
        h("label", { class: "big", for: "ctx-stage", text: "Career stage" }),
        h("select", { id: "ctx-stage", "aria-describedby": "stage-hint", onchange: (e) => { F.stage = e.target.value; } },
          [["", "Not stated"], ["early_stage", "Early-career: early-stage investigator (NIH)"], ["established", "Established investigator"]]
            .map(([v, t]) => h("option", { value: v, selected: F.stage === v, text: t }))),
        h("p", { class: "note", id: "stage-hint", text: "Early-career also shows awards only for early-stage or new investigators. They are marked “You said”, so you can check NIH’s definition." }),
        h("label", { class: "big", for: "ctx-min", text: "Leave out awards smaller than (US dollars)" }),
        h("input", { id: "ctx-min", type: "number", inputmode: "numeric", min: "0", step: "any", placeholder: "Any",
          value: F.minAmount, "aria-describedby": "min-hint", oninput: (e) => { F.minAmount = e.target.value; } }),
        h("p", { class: "note", id: "min-hint", text: "Compared with the award ceiling in each record. Records that state no amount stay in." })))));
}

// The researcher's CV card (S49 D3, M4): on the pick screen under the picked person, not
// folded. A signed-in user ticks stored documents, uploads a file or pastes text; a guest is
// pointed to sign-in; a signed-out visitor sees nothing.
function cvBox() {
  const F = S.find;
  if (api.mode === "replay" || (!S.session.signed_in && !S.session.guest)) return null;
  const head = () => [h("h2", { class: "section-title", id: "cv-h", text: "Add your CV (optional)" })];
  const box = h("section", { class: "box cv-box fade-in", "aria-labelledby": "cv-h" });
  if (S.session.guest) {
    fill(box, ...head(), h("p", { class: "note" }, h("span", { text: "Sign in to add your CV. " }),
      h("a", { href: signInHref(), text: "Sign in" })));
    return box;
  }
  const status = h("p", { class: "hint cv-status", role: "status" });
  // A new document is ticked: it is what the user just added for this brief.
  async function save(body) {
    F.cvBusy = true; draw();
    const before = new Set((F.docs || []).map((d) => d.id));
    try {
      await api.addDoc({ kind: "cv", ...body }, "researcher");
      F.docs = await api.docs("researcher");
      for (const d of F.docs) if (!before.has(d.id)) F.docIds.add(d.id);
      F.cvText = "";
      status.textContent = "Saved. It is ticked for this brief.";
      announce("CV saved.");
    } catch (e) {
      status.textContent = e.code === "consent_required" ? "Agree to the consent first, on your account page." : e.message;
    }
    F.cvBusy = false; draw();
  }
  function upload(file) {
    if (!file) return;
    const rd = new FileReader();
    rd.onload = () => save({ filename: file.name, data: String(rd.result).split(",")[1] || "" });
    rd.readAsDataURL(file);
  }
  function draw() {
    const docs = F.docs && F.docs.length ? h("div", { class: "cv-docs" }, F.docs.map((d) => h("label", { class: "check" },
      h("input", { type: "checkbox", checked: F.docIds.has(d.id),
        onchange: (e) => { if (e.target.checked) F.docIds.add(d.id); else F.docIds.delete(d.id); } }),
      h("span", { text: `${d.name || d.label || d.kind} (${d.kind})` }))))
      : h("p", { class: "note", text: F.docs ? "No stored documents yet." : "Loading your documents" });
    const text = h("textarea", { id: "r-cv-text", rows: 6, maxlength: 60000, value: F.cvText || "",
      oninput: (e) => { F.cvText = e.target.value; } });
    fill(box, ...head(),
      h("p", { class: "hint", text: "Used for cover-letter points and Scout. Stored encrypted. Contact details are blanked before a model reads it." }),
      docs,
      h("div", { class: "file-row" },
        h("input", { id: "r-cv-file", class: "sr-only file-input", type: "file", accept: ".pdf,.docx,.txt,.md", disabled: F.cvBusy,
          onchange: (e) => upload(e.target.files[0]) }),
        h("label", { class: "btn", for: "r-cv-file", "aria-disabled": F.cvBusy ? "true" : null },
          icon("paper"), h("span", { text: F.cvBusy ? "Saving" : "Upload a file" }))),
      h("details", { class: "cv-paste", open: Boolean(F.cvText) },
        h("summary", { "data-key": "cv-paste", text: "Paste text instead" }),
        h("label", { class: "sr-only", for: "r-cv-text", text: "Your CV as text" }),
        text,
        h("button", { class: "btn", type: "button", "data-key": "cv-save", disabled: F.cvBusy,
          onclick: () => { if ((F.cvText || "").trim()) save({ text: F.cvText, filename: "cv.txt" }); } },
        h("span", { text: "Save my CV" }))),
      status);
  }
  draw();
  if (!F.docs) {
    api.docs("researcher").then((d) => {
      F.docs = d;
      // S50 (Q19): a stored CV is ticked by default, unless this form already chose its documents.
      if (!F.docIds.size && !F.docsChosen) for (const x of d) if (x.kind === "cv") F.docIds.add(x.id);
      F.docsChosen = true;
      draw();
    })
      .catch((e) => { F.docs = []; draw(); status.textContent = e.code === "consent_required" ? "Agree to the consent first, on your account page." : e.message; });
  }
  return box;
}

// "Change details and run again" (D4): load a brief and go back to its form with its details
// filled in. A student brief goes to the start screen, which shows the stored CV and entries.
async function rerun(id) {
  fill(main(), h("div", { class: "loading" }, owl("work", "owl-md"), h("p", { text: "Opening the brief's details" })));
  let d;
  try { d = await api.brief(id); } catch (e) { renderMissing(id, e.message); return; }
  if (!location.hash.startsWith("#/rerun/")) return; // the user went elsewhere meanwhile
  if (isStudent(d)) { goReplace("#/student"); return; }
  const r = d.researcher || {};
  const o = (d.brief && d.brief.options) || {};
  const cand = { id: r.id, display_name: r.display_name, institutions: r.institutions || [], orcid: r.orcid,
    works_count: r.works_count, cited_by_count: r.cited_by_count, topics: [] };
  const list = (v) => (Array.isArray(v) ? v.join(", ") : "");
  Object.assign(S.find, { q: r.display_name || "", candidates: [cand], picked: cand, searched: r.display_name || "",
    busy: false, error: null, badOrcid: false, badId: false, unknownId: false,
    direction: o.direction || "", include: list(o.include_keywords), exclude: list(o.exclude_keywords),
    stage: o.career_stage || "", minAmount: o.min_amount != null ? String(o.min_amount) : "",
    explain: o.explain != null ? Boolean(o.explain) : S.find.explain, docIds: new Set(o.doc_ids || []) });
  goReplace("#/find");
}

// One build call: the api makes sure a session exists, then starts the brief.
async function build(c) {
  const F = S.find;
  resetStudent(); // a researcher brief replaces any student one; Back finds an empty form (S27)
  const req = { author_id: f.shortId(c.id), explain: F.explain };
  const words = (x) => x.split(",").map((w) => w.trim()).filter(Boolean);
  if (F.direction.trim()) req.direction = F.direction.trim();
  if (words(F.include).length) req.include_keywords = words(F.include);
  if (words(F.exclude).length) req.exclude_keywords = words(F.exclude);
  if (F.stage) req.career_stage = F.stage;
  if (F.docIds.size) req.doc_ids = [...F.docIds];
  const min = parseFloat(F.minAmount);
  if (Number.isFinite(min) && min > 0) req.min_amount = min;
  F.building = true; F.error = null;
  keepFocus(renderPick);
  try {
    if (S.session.signed_in && S.session.audience !== "researcher" && (S.session.roles || []).includes("researcher")) {
      await api.setAudience("researcher");  // a brief is built on the side the session is on
      await refreshSession();
    }
    const r = await api.create(req, "researcher");
    await refreshSession(); // a first brief may have started a guest session: show the banner
    S.startedHere = true;
    S.tab = "routes";
    S.briefId = null; // a new brief: open it fresh
    F.building = false;
    go(`#/brief/${encodeURIComponent(r.id)}/routes`);
  } catch (e) {
    F.building = false;
    F.error = `The brief could not start: ${e.message}`;
    renderPick();
    const err = main().querySelector(".notice.error");
    if (err) err.scrollIntoView({ block: "center" });
  }
}

// ---------- Brief ----------

function stopPolling() {
  clearTimeout(S.pollTimer);
  S.pollTimer = null;
  S.gen += 1;
}

async function openBrief(id) {
  stopPolling();
  Object.assign(S, { briefId: id, brief: null, filter: null, weakOpen: false, centreOpen: false, firstShown: null, open: new Set(), shut: new Set(), stepsOpen: false,
    failedPolls: 0, seen: { explained: 0, stagesDone: 0 } });
  fill(main(), h("div", { class: "loading" }, owl("work", "owl-md"),
    h("p", { text: "Opening the brief" })));
  await poll();
}

async function poll() {
  const id = S.briefId, gen = S.gen;
  let data;
  try {
    data = await api.brief(id);
  } catch (e) {
    if (gen !== S.gen) return;
    if (e.status === 404) return renderMissing(id, e.message);
    S.failedPolls += 1;
    if (S.failedPolls >= 4 || !S.brief) return renderMissing(id, e.message);
    S.pollTimer = setTimeout(poll, POLL_MS * 2);
    return;
  }
  if (gen !== S.gen) return;
  S.failedPolls = 0;
  const first = !S.brief;
  S.brief = data;
  if (first) renderBrief();
  else updateBrief();
  const st = data.brief.status;
  if (st === "queued" || st === "running") S.pollTimer = setTimeout(poll, POLL_MS);
}

function renderMissing(id, msg) {
  fill(main(), h("div", { class: "empty" }, owl("worry", "owl-md"),
    h("div", {}, h("p", { class: "lede", text: "This brief could not be opened." }),
      h("p", { class: "hint", text: msg }),
      h("a", { class: "btn", href: "#/" }, icon("back"), h("span", { text: "Back to the start" })))));
}

const leadsOf = () => (S.brief ? S.brief.leads : []);
const stage = (name) => S.brief.brief.stages.find((s) => s.name === name) || { status: "pending" };
const isDone = (name) => ["done", "skipped"].includes(stage(name).status);
// Temple internal funding is its own list, route "T" on screen: the back end marks those
// leads group "temple_internal" on route A (S49 FM9). They never join the federal list.
const routeOf = (l) => (l.group === "temple_internal" ? "T" : l.route || "A");
const routeLeads = (r) => leadsOf().filter((l) => routeOf(l) === r);
const explainedCount = () => routeLeads("A").filter((l) => l.explanation || l.flagged).length;

function renderBrief() {
  const d = S.brief;
  const r = d.researcher || {};
  const student = isStudent(d);
  const name = student ? "Your options" : r.display_name || "Your brief";
  document.title = window.PERCH_EXAMPLE ? "Example brief — Perch" : `${name} — Perch`;
  if (student && !["F", "S"].includes(S.route)) S.route = "F";
  if (!student && !["A", "B", "T"].includes(S.route)) S.route = "A";
  // F23: the date's parts never part at a line end ("1" / "Nov 2026").
  const asOf = f.formatDate(d.brief.options.as_of).replace(/ /g, "\u00a0");
  // A guest's sample brief says whose CV it checks (S43 S8).
  const sampleBrief = Boolean(d.brief.options.persona);
  const meta = student ? (sampleBrief ? `Temple awards, fellowships and sample scholarships, checked against the sample student's CV by rule · as of ${asOf}`
      : `Temple awards and fellowships, checked against your CV by rule · as of ${asOf}`)
    : [...(r.institutions || []), `Brief as of ${asOf}`].join(" · ");
  // Back: a student returns to the start screen, a researcher to the matches.
  // The example brief's Back leaves the example for the app itself (S50 Q22).
  const back = window.PERCH_EXAMPLE ? h("a", { class: "back", href: "./" }, icon("back"), h("span", { text: "Back to Perch" }))
    : student ? h("a", { class: "back", href: "#/student" }, icon("back"), h("span", { text: "Back" }))
    : h("a", { class: "back", href: S.find.candidates ? "#/find" : "#/" }, icon("back"), h("span", { text: "Back" }));
  // S3: the second tab is "What Perch read" on both sides.
  const tabs = h("div", { class: `tabs${student ? " student" : ""}`, role: "tablist", "aria-label": "Brief sections" },
    tabButton("routes", student ? "Your options" : "Routes", student ? "Options" : "Routes"),
    tabButton("profile", "What Perch read", "Read"),
    tabButton("compare", "Compare", "Compare"), tabButton("scout", "Ask Scout", "Scout"));
  fill(main(), h("div", { class: "brief screen" }, back,
    h("div", { class: "title-row" },
      h("div", {}, h("h1", { class: "page who", text: name }), h("p", { class: "brief-meta", text: meta })),
      // S49 (U37, S8, D4): the ready chip, Change details and Export share one group.
      h("div", { class: "brief-tools" }, h("div", { id: "ready-slot" }), rerunLink("rerun-wide"), exportMenu(student))),
    sampleSteered()
      ? h("p", { class: "notice sample-note", role: "note" },
      h("span", { class: "sample-badge", text: "Sample data" }),
      h("span", { text: ` Built from an invented SYNTHETIC student. Nothing here is about you.` })) : null,
    h("div", { id: "progress" }),
    h("div", { class: "tabs-wrap" }, tabs),
    h("div", { class: "cols" },
      h("div", { class: "main-col" }, h("div", { id: "panel", role: "tabpanel", tabindex: "-1" })),
      h("div", { class: "rail", id: "rail" })),
    h("div", { id: "keep-float" })));
  S.seen.explained = explainedCount();
  S.seen.stagesDone = d.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  S.startedHere = false;
  renderProgress();
  renderTabs();
  renderPanel();
}

// "Change details and run again" (D4): a signed-in user's way back to the form with this
// brief's details filled in. Under 700 px it is the Export menu's first row instead.
function rerunLink(cls) {
  if (!S.session.signed_in || api.mode === "replay") return null;
  const href = `#/rerun/${encodeURIComponent(S.briefId)}`;
  // S50 (V16): beside the ready chip it is a short "Run again"; its name keeps the full words.
  if (cls === "rerun-wide") {
    return h("a", { class: `btn quiet ${cls}`, "data-key": cls, href, "aria-label": "Change details and run again" },
      icon("restore"), h("span", { text: "Run again" }));
  }
  return h("a", { class: `btn quiet ${cls}`, "data-key": cls, href }, h("span", { text: "Change details and run again" }));
}

// The Export button: a menu with the exports. A saved preview has nothing to download
// (review W12), so it has no menu. A student brief has no "Records as JSON" (S49 R2).
function exportMenu(student = false) {
  if (!api.exportFile) return null;
  const err = h("p", { class: "hint", role: "status" });
  async function download(kind) {
    try {
      const blob = await api.exportFile(S.briefId, kind);
      const url = URL.createObjectURL(blob);
      const a = h("a", { href: url, download: `perch-brief.${kind}` });
      if (kind === "html") { a.removeAttribute("download"); a.target = "_blank"; a.rel = "noopener"; }
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      err.textContent = "";
    } catch (e) { err.textContent = e.message; }
  }
  const pop = h("section", { class: "export-bar" },
    h("p", { class: "export" },
      rerunLink("rerun-narrow"),
      h("button", { class: "btn quiet", onclick: () => download("html") }, icon("paper"), h("span", { text: "Print or save as PDF" })),
      h("button", { class: "btn quiet", onclick: () => download("md") }, icon("download"), h("span", { text: "Markdown" })),
      student ? null : h("button", { class: "btn quiet", onclick: () => download("json") }, icon("download"), h("span", { text: "Records as JSON" }))),
    err);
  const det = h("details", { class: "export-menu" },
    h("summary", { "data-key": "export" }, icon("download"), h("span", { text: "Export" })),
    h("div", { class: "export-pop" }, pop));
  det.addEventListener("keydown", (e) => { if (e.key === "Escape" && det.open) { det.open = false; det.querySelector("summary").focus(); e.stopPropagation(); } });
  return det; // a click outside closes it: one listener, set in init() (review W17)
}

function tabButton(key, label, short) {
  return h("button", { role: "tab", id: `tab-${key}`, class: "tab", "aria-controls": "panel", "aria-label": label,
    onclick: () => go(`#/brief/${encodeURIComponent(S.briefId)}/${key}`),
    onkeydown: (e) => {
      // The WAI-ARIA tabs keys: arrows move one tab, Home and End to the first and last (Q27).
      if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const tabs = TABS.filter((k) => $(`#tab-${k}`));
      const other = e.key === "Home" ? tabs[0] : e.key === "End" ? tabs[tabs.length - 1]
        : tabs[(tabs.indexOf(key) + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      go(`#/brief/${encodeURIComponent(S.briefId)}/${other}`);
      setTimeout(() => $(`#tab-${other}`).focus(), 0);
    } }, h("span", { class: "tab-label lbl-long", text: label }), h("span", { class: "lbl-short", "aria-hidden": "true", text: short }));
}

function renderTabs() {
  for (const key of TABS) {
    const t = $(`#tab-${key}`);
    if (!t) continue;
    const on = S.tab === key;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
  }
  const keptLeads = leadsOf().filter((l) => l.status === "kept"), kept = keptLeads.length;
  // S51 (W23): at 600 px and wider the tab is named as the shortlist's button names it,
  // "Compare and draft (2)"; the phone keeps "Compare".
  const k = $("#tab-compare .tab-label");
  if (k) fill(k, "Compare", h("span", { class: "wide-600", text: " and draft" }), kept ? ` (${kept})` : "");
  const kt = $("#tab-compare");
  // A student's count keeps public and sample apart (U10).
  if (kt) kt.setAttribute("aria-label", !kept ? "Compare and draft" : isStudent(S.brief) ? `Compare and draft, ${keptWords(keptLeads)} kept` : `Compare and draft, ${kept} kept`);
  $("#panel").setAttribute("aria-labelledby", `tab-${S.tab}`);
}

function updateBrief() {
  const ex = explainedCount();
  const done = S.brief.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  const pOwl = $("#progress .owl");
  if (ex > S.seen.explained || done > S.seen.stagesDone) { hop(pOwl); }
  if (done > S.seen.stagesDone) {
    const last = S.brief.brief.stages.filter((s) => ["done", "skipped"].includes(s.status)).pop();
    if (last) announce(`${f.STAGES[last.name] || last.name}: done.`);
  }
  S.seen = { explained: ex, stagesDone: done };
  renderProgress();
  renderTabs();
  renderPanel();
}

// ---------- progress: owl, step name, step count, a thin bar in the branch colour ----------

function renderProgress() {
  const b = S.brief.brief;
  const box = $("#progress");
  const stages = b.stages;
  const runningIdx = stages.findIndex((s) => s.status === "running");
  const failedIdx = stages.findIndex((s) => s.status === "failed");
  const doneN = stages.filter((s) => ["done", "skipped"].includes(s.status)).length;
  const t0 = Date.parse(stages[0] && stages[0].started_at) || Date.parse(b.created_at);
  const lastEnd = Math.max(...stages.map((s) => Date.parse(s.finished_at) || 0));
  let state = "work", headline, detail, sub = null;
  // S50 (Q6): the server reports a stopped brief as failed; the page remembers that this
  // reader pressed Stop, and says so in place of the server's sentence.
  const stopped = b.status === "failed" && S.stoppedId === S.briefId;
  if (stopped) {
    state = "look";
    headline = "Stopped";
    detail = `${doneN} of ${stages.length} steps`;
    sub = "You stopped this brief. Run again builds a new one.";
  } else if (b.status === "failed") {
    state = "droop";
    const s = stages[failedIdx] || {};
    headline = `Stopped at: ${f.STAGES[s.name] || s.name || "a step"}`;
    detail = `${doneN} of ${stages.length} steps`;
    sub = b.error || s.detail || "The server did not say why.";
  } else if (b.status === "done") {
    state = "done";
    headline = "Brief ready";
    detail = `Built in ${f.elapsed(lastEnd - t0)} · ${stages.length} of ${stages.length} steps`;
  } else if (b.status === "queued") {
    // Nothing has started: say it waits, not the first step's name (U19). The server
    // does not report a place in line, so none is shown.
    const job = S.brief.job || {};
    headline = "Waiting in line";
    detail = `0 of ${stages.length} steps`;
    if (job.worker_seen === false) {
      // S49 re-check: no worker has checked in lately, so waiting would not help.
      state = "droop";
      headline = "Not started";
      sub = "The part of Perch that builds briefs is not running right now. Your brief will start when it is back. You can leave this page and come back.";
    } else if (job.queued_ahead > 0) {
      sub = `${job.queued_ahead === 1 ? "One brief is" : `${job.queued_ahead} briefs are`} ahead of yours. Briefs run a few at a time.`;
    } else {
      sub = "Your brief starts in a moment.";
    }
  } else {
    const i = runningIdx >= 0 ? runningIdx : Math.max(stages.findIndex((x) => x.status === "pending"), 0);
    const s = stages[i];
    headline = `${f.STAGES[s.name] || s.name}…`;
    detail = `Step ${i + 1} of ${stages.length}`;
    if (s.name === "explanations" && isDone("route_a")) detail += ` · ${explainedCount()} of ${routeLeads("A").length} explained`;
  }
  const pct = b.status === "done" ? 100 : (doneN / Math.max(stages.length, 1)) * 100;
  // S51 (W5): the header's Run again shows once. It is hidden while the brief is queued or
  // running, and after this reader stopped it, since the progress card then holds its own.
  const quiet = ["queued", "running"].includes(b.status) || stopped;
  for (const a of document.querySelectorAll("[data-key=rerun-wide], [data-key=rerun-narrow]")) a.hidden = quiet;
  // S49 (U37, S8): once the brief is ready, the progress card folds into a chip beside
  // Export, "Ready · 7 s", which opens the Steps. While it builds or after it fails, the
  // full card stays. The saved preview keeps its card, which holds "Replay the build".
  const slot = $("#ready-slot");
  if (b.status === "done" && slot && api.mode !== "replay") {
    box.replaceChildren();
    box.hidden = true;
    let chip = slot.querySelector(".ready-chip");
    if (!chip) {
      const summary = h("summary", { "data-key": "ready-chip" }, owl("done", "owl-xs"), h("span", { class: "ready-word" }));
      chip = h("details", { class: "ready-chip" }, summary, h("div", { class: "ready-pop" }));
      chip.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && chip.open) { chip.open = false; summary.focus(); e.stopPropagation(); }
      });
      fill(slot, chip);
    }
    const word = f.readyWord(lastEnd - t0);
    chip.querySelector(".ready-word").textContent = word;
    chip.querySelector("summary").setAttribute("aria-label", word === "Ready" ? "Brief ready. Show the steps"
      : `Brief ready, built in ${f.elapsed(lastEnd - t0)}. Show the steps`);
    fill(chip.querySelector(".ready-pop"), h("p", { class: "ready-pop-head", text: `${stages.length} of ${stages.length} steps done` }), stepsList(stages));
    return;
  }
  if (slot) slot.replaceChildren();
  box.hidden = false;
  let card = box.querySelector(".pcard");
  if (!card) {
    card = h("section", { class: "pcard", role: "status", "aria-label": "Progress" },
      owl(state, "owl-sm", { button: true, copy: true }),
      h("div", { class: "pcard-main" },
        h("div", { class: "pcard-line" }, h("b", { class: "p-head" }), h("span", { class: "p-detail" })),
        h("div", { class: "pbar", "aria-hidden": "true" }, h("span")),
        h("p", { class: "p-sub hint" })),
      h("div", { class: "p-act" }),
      h("div", { class: "progress-steps" }));
    fill(box, card);
  }
  card.classList.toggle("failed", b.status === "failed" && !stopped); // a stop the reader asked for is no error
  card.classList.toggle("done", b.status === "done"); // one line on a phone once ready (U5)
  setOwl(card.querySelector(".owl"), state);
  card.querySelector(".owl").classList.toggle("bob", b.status === "running" || b.status === "queued");
  card.querySelector(".p-head").textContent = headline;
  card.querySelector(".p-detail").textContent = detail;
  card.querySelector(".pbar > span").style.width = `${pct}%`;
  const subEl = card.querySelector(".p-sub");
  subEl.textContent = sub || "";
  subEl.hidden = !sub;
  // The actions are redrawn only when they change, so a focused Stop survives each poll.
  const canStop = ["queued", "running"].includes(b.status) && S.session.signed_in && api.mode !== "replay";
  const stopping = canStop && S.stoppedId === S.briefId;
  const act = card.querySelector(".p-act");
  const actSig = `${b.status}:${stopped}:${canStop}:${stopping}:${api.mode}`;
  if (act.dataset.sig !== actSig) {
    const hadFocus = act.contains(document.activeElement);
    act.dataset.sig = actSig;
    fill(act,
      stopped ? h("a", { class: "btn primary", "data-key": "rerun-stopped", href: `#/rerun/${encodeURIComponent(S.briefId)}` },
        icon("restore"), h("span", { text: "Run again" }))
        : b.status === "failed" ? h("button", { class: "btn primary", onclick: rebuild }, h("span", { text: "Build again" })) : null,
      // aria-disabled, not disabled, while it stops, so focus stays on the button.
      canStop ? h("button", { class: "btn quiet", type: "button", "data-key": "stop-brief", "aria-disabled": stopping ? "true" : null,
        onclick: stopBrief }, icon("stop"), h("span", { text: stopping ? "Stopping" : "Stop" })) : null,
      api.mode === "replay" && b.status === "done" ? h("button", { class: "btn link", type: "button", onclick: replayBuild }, h("span", { text: "Replay the build" })) : null);
    if (hadFocus) { const k = act.querySelector("[data-key=stop-brief], [data-key=rerun-stopped]"); if (k) k.focus(); }
  }
  const steps = h("details", { class: "steps", open: S.stepsOpen,
    ontoggle: (e) => { S.stepsOpen = e.target.open; } },
  // U8: the count is live progress, so it shows only while the brief builds.
  h("summary", {}, h("span", { text: "Steps" }),
    b.status === "done" ? null : h("span", { class: "steps-n", text: `(${doneN} of ${stages.length} done)` })),
  stepsList(stages));
  fill(card.querySelector(".progress-steps"), steps);
}

// Stop a brief while it builds (S50 Q6): signed-in users only; the cancel route refuses guests.
// The next poll draws the failed state, which reads "Stopped" for this reader.
async function stopBrief(e) {
  if (e.currentTarget.getAttribute("aria-disabled") === "true" || S.stoppedId === S.briefId) return;
  S.stoppedId = S.briefId;
  renderProgress();
  try {
    await api.cancelBrief(S.briefId);
    announce("Stopping the brief.");
  } catch (err) {
    S.stoppedId = null;
    renderProgress();
    announce(err.message || "The brief could not be stopped.");
  }
}

function stepsList(stages) {
  return h("ol", { class: "steps-list" }, stages.map((s) => h("li", { "data-status": s.status },
    h("span", { class: "step-dot", "aria-hidden": "true" }),
    h("span", { class: "step-name" }, h("b", { text: f.STAGES[s.name] || s.name }),
      h("span", { class: "sr-only", text: `, ${stepWord(s.status)}` })),
    h("span", { class: "step-detail", text: stepDetail(s) }))));
}

async function replayBuild() {
  const r = await api.create({});
  S.startedHere = true;
  S.briefId = null;
  go(`#/brief/${encodeURIComponent(r.id)}/routes`);
}

function stepWord(st) {
  return { pending: "waiting", running: "in progress", done: "done", skipped: "already on file",
    failed: "failed" }[st] || st;
}

function stepDetail(s) {
  const dur = s.started_at && s.finished_at
    ? ` (${f.elapsed(Date.parse(s.finished_at) - Date.parse(s.started_at))})` : "";
  if (s.status === "skipped") {
    return s.detail === "explanations off" ? "Turned off for this brief"
      : `Already on file: ${s.detail || ""}`;
  }
  if (s.status === "pending") return "Waiting";
  if (s.status === "running") return "In progress";
  return (s.detail || "") + dur;
}

async function rebuild() {
  if (api.mode === "replay") replayBuild();
  else go(isStudent(S.brief) ? "#/student" : S.find.picked ? "#/find" : "#/start");
}

// ---------- panels ----------

function renderPanel() {
  if (!S.brief || !$("#panel")) return;
  renderTabs();
  const panel = $("#panel");
  if (panel.dataset.tab !== S.tab) {
    panel.dataset.tab = S.tab;
    panel.dataset.sig = "";
    panel.replaceChildren();
    $("#rail").replaceChildren();
  }
  drawRail();
  if (isStudent(S.brief) && S.tab !== "scout") { renderStudentPanel(panel); return; }
  if (S.tab === "profile") renderProfile(panel);
  else if (S.tab === "compare") drawCompare();
  else if (S.tab === "scout") {
    const sig = `scout:${S.brief.brief.status}`;
    if (panel.dataset.sig !== sig) {  // brief polls do not redraw Scout; Scout redraws itself
      panel.dataset.sig = sig;
      drawScout();
    }
  } else renderRoutes(panel);
}

// The floating kept pill steps aside while a warning is on screen, so it never covers the
// Industry "not verified" note (U16).
const warningsInView = new Set();
let warningWatch = null;
function watchWarning(el) {
  if (!("IntersectionObserver" in window)) return el;
  warningWatch = warningWatch || new IntersectionObserver((seen) => {
    for (const e of seen) { if (e.isIntersecting) warningsInView.add(e.target); else warningsInView.delete(e.target); }
    syncWarnings();
  });
  warningWatch.observe(el);
  return el;
}
function syncWarnings() {
  for (const el of [...warningsInView]) {
    if (!document.contains(el)) { warningsInView.delete(el); if (warningWatch) warningWatch.unobserve(el); }
  }
  document.body.classList.toggle("warn-in-view", warningsInView.size > 0);
}

// The right rail on the list tab: the shortlist card above the evidence panel. Under
// 900 px the rail hides and a floating keep pill takes the shortlist's place.
const KIND_SHORT = { A: "Grant", T: "Temple", B: "Industry", F: "Award", S: "Sample" };

function leadTitle(l) {
  return (l.opportunity && l.opportunity.title) || (l.organisation && l.organisation.name)
    || (l.record && (l.record.name || l.record.title)) || l.record_id;
}

function drawRail() {
  const rail = $("#rail");
  if (!rail || !S.brief) return;
  const onList = S.tab === "routes";
  rail.hidden = !onList;
  const kept = leadsOf().filter((l) => l.status === "kept");
  const student = isStudent(S.brief);
  if (onList) {
    let card = rail.querySelector(".shortlist");
    if (!card) {
      card = h("section", { class: "shortlist", "aria-labelledby": "sl-title" });
      const ev = h("aside", { class: "rail-evidence", id: "rail-ev", "aria-label": "Evidence", tabindex: "0",
        onscroll: (e) => railFade(e.currentTarget) });
      fill(rail, card, ev);
      emptyRail();
    }
    const sig = JSON.stringify(kept.map((l) => l.id));
    if (card.dataset.sig !== sig) {
      card.dataset.sig = sig;
      card.classList.toggle("has", kept.length > 0);
      const focusKey = card.contains(document.activeElement) ? "sl-compare" : null;
      const item = (l) => h("li", { class: "fade-in" },
        h("span", { class: "kind-short", text: KIND_SHORT[routeOf(l)] || "Lead" }),
        h("span", { class: "sl-title", text: leadTitle(l), title: leadTitle(l) }),
        h("button", { class: "x", type: "button", "aria-label": `Remove from shortlist: ${leadTitle(l)}`,
          onclick: () => setLead(l.id, "restore") }, "×"));
      // A student's public fellowships and SYNTHETIC samples are two lists (U10, rule 11).
      const groups = student ? [["F", "Temple awards and fellowships"], ["S", "Samples"]].map(([r, t]) => [t, kept.filter((l) => l.route === r)])
        .filter(([, ls]) => ls.length) : [[null, kept]];
      fill(card,
        h("div", { class: "shortlist-head" }, h("h2", { id: "sl-title", text: "Your shortlist" }),
          h("span", { text: !kept.length ? "none yet" : student ? keptWords(kept) : `${kept.length} kept` })),
        kept.length ? groups.map(([t, ls]) => [t ? h("p", { class: "sl-group", text: t }) : null, h("ul", {}, ls.map(item))])
          : h("p", { text: student ? "Keep fellowships or scholarships and they collect here, ready to compare."
            : "Keep grants or industry leads and they collect here, ready to compare and hand off." }),
        // U11: one label on both sides; with nothing kept, an outline button and a hint.
        h("button", { class: `btn ${kept.length ? "primary" : "outline"}`, type: "button", "data-key": "sl-compare",
          disabled: !kept.length, "aria-describedby": kept.length ? null : "sl-hint",
          onclick: () => go(`#/brief/${encodeURIComponent(S.briefId)}/compare`) },
        h("span", { text: "Compare and draft" })),
        kept.length ? null : h("p", { class: "hint sl-hint", id: "sl-hint", text: "Keep a lead first" }));
      if (focusKey) { const b = card.querySelector(`[data-key="${focusKey}"]`); if (b && !b.disabled) b.focus(); }
    }
  }
  syncWarnings(); // a warning that left with the last panel no longer hides the pill
  const float = $("#keep-float");
  // Not on Compare (its own place) or Ask Scout, where it would cover the question box.
  const show = kept.length > 0 && (S.tab === "routes" || S.tab === "profile");
  const fsig = show ? String(kept.length) : "";
  if (float.dataset.sig !== fsig) {
    float.dataset.sig = fsig;
    fill(float, show ? h("div", { class: "keep-float fade-in", role: "region", "aria-label": "Kept" },
      h("span", { text: student ? `Kept: ${keptWords(kept)}` : `${kept.length} kept` }),
      h("a", { class: "btn", href: `#/brief/${encodeURIComponent(S.briefId)}/compare`, "data-key": "keep-compare" },
        h("span", { text: "Compare" }))) : null);
  }
}

// The rail's Evidence box with nothing picked. A route switch comes back here, so a
// grant's record never sits beside the industry list (U9).
function emptyRail() {
  const ev = $("#rail-ev");
  if (!ev) return;
  evidenceAsk++; // a record still loading for the old list is dropped
  document.querySelectorAll("#panel .lead.selected").forEach((x) => x.classList.remove("selected"));
  ev.removeAttribute("aria-labelledby");
  fill(ev, h("p", { class: "ev-kind", text: "Evidence" }),
    h("p", { class: "empty-ev", text: "Pick a card’s title to see its record here. Every value is copied from the record." }));
  railFade(ev);
}

// A record longer than the rail fades out at the bottom until it is scrolled to its end,
// so a cut row does not read as the end of the record (U27).
function railFade(box) {
  if (box) box.classList.toggle("more", box.scrollHeight - box.scrollTop - box.clientHeight > 4);
}

function switchRoute(r) {
  if (S.route !== r) emptyRail();
  S.route = r;
  renderPanel();
  panelFocus(`route-${r}`);
}

// ----- Student brief (S18, student.js) -----

function renderStudentPanel(panel) {
  const d = S.brief;
  const sig = JSON.stringify([S.tab, S.route, d.brief.stages.map((s) => s.status),
    d.leads.map((l) => [l.status, Boolean(l.explanation), l.flagged])]);
  if (panel.dataset.sig === sig) return;
  panel.dataset.sig = sig;
  const ctx = { brief: d, route: S.route, papers: d.papers || {}, openEvidence, setLead, announce, api,
    offices: d.offices || api.studentOffices, guest: Boolean(S.session.guest), signIn: signInHref(),
    briefId: S.briefId, setRoute: switchRoute, accountsOpen: accountsOpen(),
    goRoutes: () => go(`#/brief/${encodeURIComponent(S.briefId)}/routes`) };
  if (S.tab === "profile") keepFocus(() => fill(panel, ...studentProfile(d, ctx)));
  else if (S.tab === "compare") studentCompare(panel, ctx);
  else keepFocus(() => studentRoutes(panel, ctx));
}

// ----- Compare -----

const keptIds = () => leadsOf().filter((l) => l.status === "kept").map((l) => l.id).sort();

function drawCompare(focusKey) {
  const panel = $("#panel");
  if (!panel || S.tab !== "compare" || !S.brief) return;
  const kept = keptIds();
  renderCompare(panel, { keptCount: kept.length, openEvidence, redraw: drawCompare, handoff: true,
    goRoutes: () => go(`#/brief/${encodeURIComponent(S.briefId)}/routes`) });
  renderHandoff(panel.querySelector(".handoff-box"), { api, briefId: S.briefId, announce,
    kept: leadsOf().filter((l) => l.status === "kept"), offices: compareOffices(), redraw: drawCompare,
    guest: Boolean(S.session.guest), signIn: signInHref(), accountsOpen: accountsOpen() });
  if (kept.length) loadCompare(api, S.briefId, kept, () => drawCompare());
  if (focusKey) panelFocus(focusKey);
}

function drawScout() {
  const panel = $("#panel");
  if (!panel || S.tab !== "scout" || !S.brief) return;
  renderScout(panel, { api, briefId: S.briefId, done: S.brief.brief.status === "done", student: isStudent(S.brief),
    openEvidence, announce, rerender: drawScout, label: recordLabel,
    // Only a guest is turned away: a server without accounts still runs the open Scout path
    // and has no guest sessions (S46 re-check).
    signedIn: !(S.session && S.session.guest), signIn: signInHref(), accountsOpen: accountsOpen() });
}

// How Scout names a record of this brief (U8): a grant by its opportunity number; a
// fellowship or scholarship, whose name the answer already says, as "Evidence", with
// "(sample)" for a SYNTHETIC one. The full name is the button's label. null: not a lead.
function recordLabel(id) {
  // A paper reads as the card's papers block names it: a short title and the year (Q8).
  const papers = (S.brief && S.brief.papers) || {};
  const w = /^W\d+$/.test(id) ? papers[`https://openalex.org/${id}`] || papers[id] : null;
  if (w && w.title) {
    const year = w.publication_year ? ` (${w.publication_year})` : "";
    const short = w.title.length > 48 ? `${w.title.slice(0, 46).replace(/\s+\S*$/, "")}…` : w.title;
    return { text: `${short}${year}`, full: `${w.title}${year}`, name: `${w.title}${year}` };
  }
  if (/^W\d+$/.test(id)) return { text: "A paper", full: "A paper by the researcher; Evidence opens it", name: "a paper" };
  const l = leadsOf().find((x) => x.record_id === id || f.shortId(x.record_id) === id
    || (x.opportunity && x.opportunity.opportunity_number === id));
  if (!l) return null;
  const full = leadTitle(l);
  // S50 (V17): a chip never says "Evidence" alone: the record's title, cut to 32 characters, or
  // with no title its source and number, such as "Grants.gov PAR-25-442".
  // a student lead's record is a scholarship: its title is `name` (S50 QA)
  const title = (l.opportunity && l.opportunity.title) || (l.record && (l.record.title || l.record.name)) || null;
  const text = title ? clipTitle(title, 32) : sourceLabel(l);
  if (l.sample) return { text: `${text} (sample)`, full: `${full}, sample data`, sample: true, name: `${full} (sample)` };
  if (l.route === "B") return null;
  return { text, full, name: title ? full : text };
}

// A record's source and number, for a chip with no title to show (S50 V17).
function sourceLabel(l) {
  const o = l.opportunity || {};
  const key = o.source || (l.record && l.record.source) || l.source_kind || String(l.record_id || "").split(":")[0];
  const src = SOURCES[key] || "Record";
  return `${src} ${o.opportunity_number || f.shortId(l.record_id)}`;
}

const clipTitle = (t, n) => (t.length > n ? `${t.slice(0, n).trimEnd()}…` : t);

// ----- Profile -----

function renderProfile(panel) {
  const d = S.brief, b = d.brief;
  const sig = JSON.stringify([b.summary, b.topics, b.threads.length, d.awards.length,
    Object.keys(d.papers || {}).length, b.stages.map((s) => s.status)]);
  if (panel.dataset.sig === sig) return;
  panel.dataset.sig = sig;
  const card = (sec) => { if (sec) sec.classList.add("pblock"); return sec; };
  keepFocus(() => fill(panel, h("div", { class: "prof-cols" },
    h("div", { class: "left" }, card(youSaidSection()), card(summarySection()), card(threadsSection())),
    h("div", { class: "right" }, card(horizonSection()), card(keyPapersSection())))));
}

// The most cited of the researcher's papers in this brief, one row per title.
function keyPapersSection() {
  const d = S.brief;
  if (!isDone("profile")) return h("section", { class: "block" }, h("h2", { class: "section-title", text: "Key papers" }), skeleton(3));
  const all = distinctPapers(Object.values(d.papers || {}).filter((w) => !isOwnDoc(w)));
  if (!all.length) return null;
  const top = [...all].sort((a, b) => (b.cited_by_count || 0) - (a.cited_by_count || 0)
    || (b.publication_year || 0) - (a.publication_year || 0)).slice(0, 5);
  return h("section", { class: "block" },
    h("h2", { class: "section-title" }, h("span", { text: "Key papers" }), h("span", { class: "hint", text: `${top.length} of ${all.length}, most cited first` })),
    h("ul", { class: "papers" }, top.map(paperRow)));
}

// Context (Q16): what the user typed on Find, shown as theirs, never as a fact.
function youSaidSection() {
  const o = S.brief.brief.options;
  const rows = [
    o.direction ? ["Direction", o.direction] : null,
    o.include_keywords && o.include_keywords.length ? ["Search for", o.include_keywords.join(", ")] : null,
    o.exclude_keywords && o.exclude_keywords.length ? ["Leave out", o.exclude_keywords.join(", ")] : null,
    o.career_stage ? ["Career stage", o.career_stage === "early_stage" ? "Early-stage investigator (NIH)" : "Established investigator"] : null,
  ].filter(Boolean);
  if (!rows.length) return null;
  return h("section", { class: "block you-said" },
    h("h2", { class: "section-title", text: "You said" }),
    h("p", { class: "hint", text: "These steer the search. Perch does not check them, and no explanation cites them." }),
    h("dl", { class: "fields" }, rows.map(([k, v]) => field(k, v))));
}

function summarySection() {
  const b = S.brief.brief;
  const st = stage("summary");
  let body;
  if (b.summary) {
    body = [h("p", { class: "summary" }, renderSegs(citedOnly(f.segments(b.summary)))),
      b.topics.length ? h("ul", { class: "chips", "aria-label": "Topics" },
        b.topics.map((t) => h("li", { class: "chip", text: t }))) : null,
      h("p", { class: "provenance" }, modelWord(),
        h("span", { text: "Written by a model and checked against the papers it cites." }))];
  } else if (st.status === "skipped") {
    body = [h("p", { class: "hint", text: "The model summary is turned off for this brief. The threads below come from the papers alone." }), openAlexTopics()];
  } else if (st.status === "done" || st.status === "failed") {
    body = [h("p", { class: "notice warn" }, icon("warn"), h("span", {
      text: "The summary was withheld because it failed the citation checks twice. The threads below come from the papers alone." })),
    openAlexTopics()];
  } else {
    body = [skeleton(2), h("p", { class: "hint", text: "The summary is written after the search for leads." })];
  }
  // The Model text tag in the body is the one marker (U35).
  return h("section", { class: "block" }, h("h2", { class: "section-title", text: "Summary" }), body);
}

// A chip only for a paper in this brief. Any other id is dropped, so the summary never
// shows a bare record id or offers a record that cannot be opened (S22 review, S25 review).
function citedOnly(segs) {
  const papers = S.brief.papers || {};
  return segs.filter((x) => typeof x === "string" || papers[x.cite] || papers[`https://openalex.org/${x.cite}`]);
}

function openAlexTopics() {
  const t = (S.brief.researcher || {}).topics || [];
  return t.length ? [h("ul", { class: "chips", "aria-label": "OpenAlex topics" },
    t.slice(0, 5).map((x) => h("li", { class: "chip", text: x.display_name }))),
  h("p", { class: "provenance" }, h("span", { text: "Topics as OpenAlex lists them." }))] : null;
}

function horizonSection() {
  const d = S.brief, b = d.brief;
  const title = h("h2", { class: "section-title", text: "Award horizon" });
  if (!isDone("awards")) return h("section", { class: "block" }, title, skeleton(1));
  if (!d.awards.length) {
    return h("section", { class: "block" }, title, h("p", { class: "lede", text:
      "No public NIH or NSF award was found for this researcher." }),
    h("p", { class: "hint", text: "That says nothing about other funding. Perch only reads public federal award records." }));
  }
  const asOf = b.options.as_of;
  const left = b.award_horizon ? f.daysBetween(asOf, b.award_horizon) : null;
  return h("section", { class: "block horizon" }, title,
    // S51 (W33): a plain sentence at the section-title size, not a large date that reads as an error.
    h("p", { class: "horizon-date" },
      h("span", { class: "horizon-line", text: !b.award_horizon ? "The last federal award’s end date is not stated in the record"
        : `Last federal award ${left !== null && left < 0 ? "ended" : "ends"} ${f.formatDate(b.award_horizon).replace(/ /g, "\u00a0")}` }),
      left !== null && left >= 0 ? h("span", { class: "hint", text: f.until(left) }) : null),
    h("p", { class: "hint", text:
      `The end date of the last public federal award found, out of ${f.plural(d.awards.length, "award")}. Nothing about lab finances is inferred.` }),
    h("p", { class: "legend", "aria-hidden": "true" },
      h("span", { class: "key active" }), h("span", { text: "Running at the brief date" }),
      h("span", { class: "key now" }), h("span", { text: "Brief date" })),
    awardTimeline(d.awards, asOf));
}

function awardTimeline(awards, asOf) {
  const rows = [...awards].sort((a, b) => (b.end_date || "").localeCompare(a.end_date || ""));
  const ts = rows.flatMap((a) => [a.start_date, a.end_date]).filter(Boolean).map((x) => f.parseDate(x).getTime());
  const now = f.parseDate(asOf).getTime();
  const lo = Math.min(...ts, now), hi = Math.max(...ts, now);
  const span = Math.max(hi - lo, 1);
  const x = (iso) => ((f.parseDate(iso).getTime() - lo) / span) * 100;
  const yr = (t) => new Date(t).getUTCFullYear();
  const SHOW = 5;
  const item = (a) => {
    const active = a.end_date && a.end_date >= asOf;
    return h("li", { class: `award${active ? " active" : ""}` },
      h("button", { class: "award-btn", "data-key": `award-${a.key}`,
        onclick: (e) => openEvidence(a.record_id || a.key, e.currentTarget) },
        h("span", { class: "award-top" },
          h("span", { class: "award-num", text: `${a.agency} ${a.award_number}` }),
          h("span", { class: "award-dates", text: `${f.formatDate(a.start_date)} to ${f.formatDate(a.end_date)}` })),
        h("span", { class: "award-title", text: a.title }),
        a.matched_by_initial ? h("span", { class: "tag ember award-initial", text: "Matched by initial: check it is yours" }) : null,
        a.start_date && a.end_date ? h("span", { class: "span-bar", "aria-hidden": "true" },
          h("span", { class: "bar-now", style: `left:${x(asOf)}%` }),
          h("span", { class: "bar-fill", style: `left:${x(a.start_date)}%;width:${Math.max(x(a.end_date) - x(a.start_date), 1.5)}%` })) : null));
  };
  return h("div", { class: "timeline" },
    h("p", { class: "axis", "aria-hidden": "true" }, h("span", { text: String(yr(lo)) }),
      h("span", { text: String(yr(hi)) })),
    h("ul", { class: "awards" }, rows.slice(0, SHOW).map(item)),
    rows.length > SHOW ? h("details", { class: "more" },
      h("summary", { text: `Show ${rows.length - SHOW} earlier awards` }),
      h("ul", { class: "awards" }, rows.slice(SHOW).map(item))) : null);
}

// How the paper counts on this tab relate, from the code's own rules (U23): OpenAlex's
// author record counts every work; the threads use the works on file that are research
// output (perch/profile.py RESEARCH_TYPES) with a title and a date on or before the brief
// date; Key papers picks from the papers this brief carries, each thread's top papers and
// those the explanations cite (perch/api.py brief_view).
function threadsNote() {
  const d = S.brief, b = d.brief;
  const n = b.work_ids.filter((id) => !/^user:|^said:/.test(id)).length;
  if (!n) return null;
  const all = (d.researcher || {}).works_count;
  const shown = distinctPapers(Object.values(d.papers || {}).filter((w) => !isOwnDoc(w))).length;
  // S50 (V48): the first sentence shows; the rest opens under "How threads work".
  return foldNote([
    `These threads group ${f.plural(n, "work")} on file by what they are about.`,
    all != null ? `OpenAlex counts ${f.plural(all, "work")} for this researcher.` : null,
    "The works are research output, such as articles, preprints and chapters, dated on or before the brief date. Labels are the words that set each group apart.",
    shown ? `Key papers picks from the ${shown} this brief shows: each thread’s top papers and those the explanations cite.` : null,
  ].filter(Boolean));
}

function foldNote(sentences) {
  const [first, ...rest] = sentences;
  return h("div", { class: "threads-note" }, h("p", { class: "hint", text: first }),
    rest.length ? h("details", { class: "threads-how" }, h("summary", { "data-key": "threads-how", text: "How threads work" }),
      h("p", { class: "hint", text: rest.join(" ") })) : null);
}

function threadsSection() {
  const d = S.brief, b = d.brief;
  const title = h("h2", { class: "section-title", text: "Research threads" });
  if (!isDone("profile")) return h("section", { class: "block" }, title, skeleton(3));
  return h("section", { class: "block" }, title,
    threadsNote() || foldNote(b.work_ids.length
      ? [`${f.plural(b.work_ids.length, "paper")} grouped by what they are about.`, "Labels are the words that set each group apart."]
      : ["No public papers on file.", "Labels are the most frequent words."]),
    h("ol", { class: "threads" }, b.threads.map((t, i) => {
      const papers = distinctPapers((t.work_ids || []).map((id) => d.papers[id]).filter(Boolean)).slice(0, 5);
      const meter = h("span", { class: "meter", "aria-hidden": "true" },
        h("span", { style: `width:${Math.max(t.weight * 100, 2)}%` }));
      if (t.said) {
        return h("li", { class: "thread said" },
          h("div", { class: "thread-head" },
            h("h3", { text: t.label }),
            h("span", { class: "share", text: `${Math.round(t.weight * 100)}% of the search` })),
          meter,
          h("p", { class: "hint", text: "From what you said. Used as a search query, never as a fact." }),
          h("ul", { class: "papers" }, papers.map(paperRow)));
      }
      // S50 (V48): "Thread 1 · 73 %" over the label's words as chips; the share is the server's
      // weight, with recent papers counting more (G23).
      const words = String(t.label || "").split(",").map((x) => x.trim()).filter(Boolean);
      return h("li", { class: "thread" },
        h("div", { class: "thread-head" },
          h("h3", { text: `Thread ${i + 1} · ${Math.round(t.weight * 100)} %` }),
          h("span", { class: "share", text: `${Math.round(t.weight * 100)} % of the papers’ weight. Newer papers count more.` })),
        words.length ? h("p", { class: "thread-words" }, h("span", { class: "sr-only", text: "Words: " }),
          words.map((x) => h("span", { class: "chip", text: x }))) : null,
        meter,
        h("p", { class: "hint", text: `${f.plural(t.work_ids.length, "paper")}. Most recent first:` }),
        h("ul", { class: "papers" }, papers.map(paperRow)));
    })));
}

// One row per paper title: OpenAlex often lists a journal article and its preprints as
// separate works. The journal version wins over an arXiv copy (S22, audit S4).
function distinctPapers(works) {
  const norm = (w) => String(w.title || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  // Short generic titles ("Correction", "Editorial") are different works: never merged.
  const key = (w) => (norm(w).split(" ").length >= 4 ? norm(w) : w.id);
  const preprint = (w) => /arxiv|biorxiv|medrxiv|preprint/i.test(w.venue || "");
  const seen = new Map();
  for (const w of works) {
    const k = key(w);
    if (!seen.has(k)) seen.set(k, w);
    else if (preprint(seen.get(k)) && !preprint(w)) seen.set(k, w);
  }
  return [...seen.values()];
}

function paperRow(w) {
  return h("li", {}, h("button", { class: "paper", "data-key": `paper-${w.id}`, onclick: (e) => openEvidence(w.id, e.currentTarget) },
    isOwnDoc(w) ? ownLabel() : null,
    h("span", { class: "paper-title", text: w.title }),
    h("span", { class: "paper-meta", text: [w.publication_year, w.venue].filter(Boolean).join(", ") })));
}

function skeleton(lines) {
  return h("div", { class: "skeleton", "aria-hidden": "true" },
    Array.from({ length: lines }, (_, i) => h("span", { style: `width:${92 - i * 17}%` })));
}

// ----- Routes -----

function sortedLeads() {
  const leads = [...routeLeads(S.route)];
  if (S.route === "B") return leads.sort((a, b) => a.rank - b.rank);
  const close = (l) => (l.opportunity && l.opportunity.close_date) || "9999";
  const score = (l) => (typeof l.match_score === "number" ? l.match_score : -1);
  if (S.sort === "closing") leads.sort((a, b) => close(a).localeCompare(close(b)) || a.rank - b.rank);
  // S50 (V3, V42): Best match is the Match score, highest first, with the server's rank as the
  // tie-break; a lead with no score goes last.
  else leads.sort((a, b) => score(b) - score(a) || a.rank - b.rank);
  return leads;
}

// Grants, Temple internal calls (when the brief has any) and industry leads sit side by side
// as equal routes; a switch picks one.
function routeSwitch() {
  const n = (r) => routeLeads(r).filter((l) => l.status !== "dismissed").length;
  const btn = (r, label) => {
    const ready = isDone(r === "B" ? "route_b" : "route_a"); // T is found with the grants
    return h("button", { class: "route-btn", "data-key": `route-${r}`, "aria-pressed": String(S.route === r),
      onclick: () => switchRoute(r) },
    // On a phone "Temple internal" reads "Temple", so three routes fit one row.
    r === "T" ? [h("span", { class: "route-long", text: label }), h("span", { class: "route-short", "aria-hidden": "true", text: "Temple" })]
      : h("span", { text: label }),
    ready ? h("span", { class: "route-n", text: String(n(r)) }) : null);
  };
  return h("div", { class: "route-switch", role: "group", "aria-label": "Route" },
    btn("A", "Grants"), routeLeads("T").length ? btn("T", "Temple internal") : null, btn("B", "Industry"));
}

// One score and one order (S27): Perch's order is the Match score; closing date is the only
// other way to sort. S50 (V3, V42): a small labelled select, not a second segmented switch.
const SORTS = [["order", "Best match"], ["closing", "Closing soonest"]];

function sortSwitch() {
  const pick = h("select", { id: "sort-pick", class: "sort-pick", "data-key": "sort",
    onchange: (e) => { S.sort = e.target.value; renderPanel(); panelFocus("sort"); } },
  ...SORTS.map(([v, label]) => h("option", { value: v, text: label })));
  pick.value = S.sort;
  return h("div", { class: "sort-group" }, h("label", { class: "sort-label", for: "sort-pick", text: "Sort" }), pick);
}

function updateSwitch(panel) {
  for (const r of ["A", "T", "B"]) {
    const el = panel.querySelector(`[data-key="route-${r}"] .route-n`);
    if (el) el.textContent = String(routeLeads(r).filter((l) => l.status !== "dismissed").length);
  }
}

function panelFocus(key) {
  const el = document.querySelector(`#panel [data-key="${key}"]`);
  if (el) el.focus();
}

function renderRoutes(panel) {
  if (S.route === "B") { renderIndustry(panel); return; }
  if (!isDone("route_a")) {
    const failed = S.brief.brief.status === "failed";
    const stopped = failed && S.stoppedId === S.briefId;
    const sig = `wait:${failed}:${stopped}`;
    if (panel.dataset.sig === sig) return;
    panel.dataset.sig = sig;
    fill(panel, routeSwitch(), h("div", { class: "empty" }, owl(failed && !stopped ? "droop" : "look", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: stopped ? "You stopped this brief before the search for leads finished."
        : failed ? "The search for leads did not run." : "Leads appear here when the search finishes." }),
      h("p", { class: "hint", text: stopped ? "Run again builds a new one." : failed ? "See the steps above for what stopped."
        : "What Perch read fills in first." }))), failed ? null : [skeleton(3), skeleton(3)]);
    return;
  }
  const leads = sortedLeads();
  const open = leads.filter((l) => l.status !== "dismissed");
  const active = open.filter(passes);
  const dismissed = leads.filter((l) => l.status === "dismissed");
  const explaining = stage("explanations").status === "running" || stage("explanations").status === "pending";

  const sig = `routes:${S.route}:${isDone("route_b")}:${routeLeads("T").length > 0}`;
  if (panel.dataset.sig !== sig) {
    panel.dataset.sig = sig;
    // S49 (U10, A6): the route row holds the route switch alone; the count heading and Sort
    // share the list's head row, and the notices sit under it, said once for the list.
    fill(panel, h("div", { class: "route-row" }, routeSwitch()),
      h("div", { class: "list-head" },
        h("h2", { class: "section-title", id: "routes-title" }),
        sortSwitch()),
      // S51 (W22): what the Match number is, said once for the list.
      h("p", { class: "hint match-hint", text: "Match: how closely the call’s text matches the papers, out of 100. It is not the odds of funding." }),
      h("p", { class: "hint routes-sub" }),
      S.route === "T" ? h("p", { class: "hint route-hint", text: "Temple’s own funding calls for faculty, kept apart from federal grants. Each call’s page says whom to contact." })
        : hiddenLine(),
      h("p", { class: "hint model-line", text: "Model text is a model’s reading of the fit, checked against the records it cites." }),
      h("div", { id: "list-notices" }),
      h("div", { class: "filter-box" }),
      h("ol", { class: "leads", "aria-labelledby": "routes-title" }),
      h("div", { class: "weak-box" }),
      h("div", { class: "centre-box" }),
      h("div", { class: "dismissed-box" }));
  }
  updateSwitch(panel);
  const pick = panel.querySelector("#sort-pick");
  if (pick && pick.value !== S.sort) pick.value = S.sort;
  const noun = S.route === "T" ? ["Temple internal call", "Temple internal calls"] : ["open opportunity", "open opportunities"];
  panel.querySelector("#routes-title").textContent = active.length === open.length
    ? f.plural(open.length, ...noun)
    : `${active.length} of ${f.plural(open.length, ...noun)}`;
  drawFilters(panel.querySelector(".filter-box"), open);
  // The kept count shows in the shortlist, the floating pill and the Compare tab (W3).
  const subBits = [];
  if (explaining && S.brief.brief.options.explain) subBits.push(`${explainedCount()} of ${routeLeads("A").length} explained so far`);
  // Only live progress here; what Match means is in its pill and Help (Dakshitha, S27).
  const sub = panel.querySelector(".routes-sub");
  sub.textContent = subBits.length ? `${subBits.join(". ")}.` : "";
  sub.hidden = !subBits.length;
  // U43: what model text is, said once above the list, when the list holds any.
  panel.querySelector(".model-line").hidden = !open.some((l) => l.explanation);
  // S50 (V5): two or more flagged cards on view: the list note says it once, the cards say nothing.
  S.listWithheld = active.filter((l) => l.flagged).length >= 2;
  drawNotices(panel.querySelector("#list-notices"), active);

  if (!leads.length) {
    fill(panel.querySelector(".leads"), h("li", { class: "empty" }, owl("worry", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: "No open opportunity passed the eligibility check." }),
        h("p", { class: "hint", text: stage("route_a").detail || "" }))));
    return;
  }
  // The first five cards always show open, whatever their band, so the first view is
  // never one card; after the fifth, weak ones fold under a count (U24, Q6).
  const weak = (l) => (f.fitBand(l.match_score) || {}).key === "weak";
  // S51 (H7): centre and programme grants leave the list for their own fold, under the
  // single-lab cards and their "Show N more". They still count in the heading and the tab.
  const centre = active.filter((l) => l.group === "centre");
  const single = active.filter((l) => l.group !== "centre");
  const folded = single.slice(OPEN_FIRST).filter(weak);
  const top = single.filter((l) => !folded.includes(l));
  // S51 (W14): with a CV in the brief, only the first card shown starts open.
  S.firstShown = top.length ? top[0].id : null;
  syncList(panel.querySelector(".leads"), top);
  const wbox = panel.querySelector(".weak-box");
  if (!folded.length) wbox.replaceChildren();
  else {
    let wd = wbox.querySelector("details");
    if (!wd) {
      wd = h("details", { class: "weak-fold", open: S.weakOpen,
        ontoggle: (e) => { S.weakOpen = e.target.open; } }, h("summary", { "data-key": "weak-fold" }), h("ol", { class: "leads" }));
      fill(wbox, wd);
    }
    wd.querySelector("summary").textContent = `Show ${folded.length} more`;
    syncList(wd.querySelector("ol"), folded);
  }
  const cbox = panel.querySelector(".centre-box");
  if (!centre.length) cbox.replaceChildren();
  else {
    let cd = cbox.querySelector("details");
    if (!cd) {
      cd = h("details", { class: "weak-fold centre-fold", open: S.centreOpen,
        ontoggle: (e) => { S.centreOpen = e.target.open; } }, h("summary", { "data-key": "centre-fold" }),
      h("p", { class: "hint", text: "Centres and programmes of several projects apply through the institution. Each card says why it is here." }),
      h("ol", { class: "leads" }));
      fill(cbox, cd);
    }
    cd.querySelector("summary").textContent = `Centre and programme grants (${centre.length})`;
    syncList(cd.querySelector("ol"), centre);
  }
  const box = panel.querySelector(".dismissed-box");
  if (!dismissed.length) { box.replaceChildren(); return; }
  let det = box.querySelector("details");
  if (!det) {
    det = h("details", { class: "dismissed" }, h("summary"), h("ol", { class: "leads" }));
    fill(box, det);
  }
  det.querySelector("summary").textContent = `Dismissed (${dismissed.length})`;
  syncList(det.querySelector("ol"), dismissed);
}

// What the rules left out (S49 F2; S50 V44): one short summary that opens to a line per rule.
// The labels and counts are the server's.
function hiddenLine() {
  const hid = (S.brief.brief.hidden || S.brief.hidden || []).filter((x) => x && x.label && x.count);
  if (!hid.length) return null;
  const total = hid.reduce((n, x) => n + x.count, 0);
  return h("details", { class: "hidden-fold" },
    h("summary", { "data-key": "hidden-fold", text: `${total} hidden by the rules` }),
    h("ul", { class: "hidden-list" }, hid.map((x) => h("li", { text: `${x.label}: ${x.count}` }))));
}

// The list's notices (S49 U3, U16): the withheld-reason note once for the list when two or
// more cards on it are flagged, and cover.js's one line. Empty, the slot takes no room.
function drawNotices(box, shown) {
  if (!box) return;
  const flagged = shown.filter((l) => l.flagged).length;
  // S51 (D16): when the model budget skipped the written reasons, one line says so, first,
  // in place of the withheld note. The stage's own detail says why (BUDGET_DETAIL).
  const budget = budgetSkipped(stage("explanations"));
  const items = [
    budget ? budgetLine() : null,
    flagged >= 2 && !budget ? h("p", { class: "notice info list-note", "data-withheld": "" }, icon("info"),
      h("span", { text: WITHHELD_NOTE })) : null,
    coverListLine(coverCtx())].filter(Boolean);
  const sig = JSON.stringify([budget, flagged >= 2, items.map((x) => x.textContent)]);
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  fill(box, ...items);
}

// The budget line (S51 contract 3.2): the same on both sides; FE-B emits it on the student list.
const budgetSkipped = (st) => Boolean(st && st.status === "skipped" && String(st.detail || "").startsWith("withheld: the daily model budget"));
const budgetLine = () => h("p", { class: "notice info list-note", "data-budget": "" }, icon("info"),
  h("span", { text: "Written reasons are paused: this session’s model budget for today is used. The list, dates, amounts and rule results are not affected." }));

// The withheld-reason note, the same on both sides (S50 contract 3.2).
const WITHHELD_NOTE = "Some written reasons failed Perch’s citation check, so those cards show no reason. Every date, amount and rule result on the cards is still copied from the record.";
const RESEARCH_SECURITY ="Companies outside the United States may need a research-security review before any contact; the office makes that check.";
const OPEN_FIRST = 5; // cards shown open before the Weaker matches fold (Q6)

// One-click filters (U25), built only from the values on the leads themselves: each
// agency as its tag reads, and each activity code. One chip at a time; All clears it.
const agencyOf = (l) => f.agencyShort((l.opportunity || {}).agency, (l.opportunity || {}).parent_agency);
const codeOf = (l) => (l.opportunity || {}).activity_code || null;
function passes(l) {
  const x = S.filter;
  return !x || (x.kind === "agency" ? agencyOf(l) === x.value : codeOf(l) === x.value);
}

function drawFilters(box, open) {
  const tally = (get) => { const m = new Map(); for (const l of open) { const v = get(l); if (v) m.set(v, (m.get(v) || 0) + 1); } return m; };
  const agencies = tally(agencyOf), codes = tally(codeOf);
  if (S.filter && !(S.filter.kind === "agency" ? agencies : codes).has(S.filter.value)) S.filter = null;
  const sig = JSON.stringify([[...agencies], [...codes], S.filter]);
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  if (agencies.size + codes.size < 2) { box.replaceChildren(); return; }
  const chip = (kind, value, n) => {
    const on = kind ? Boolean(S.filter && S.filter.kind === kind && S.filter.value === value) : !S.filter;
    return h("button", { class: "chip filter-chip", type: "button", "aria-pressed": String(on), "data-key": `filter-${kind || "all"}-${value || ""}`,
      onclick: () => { S.filter = kind && !on ? { kind, value } : null; renderPanel(); panelFocus(`filter-${S.filter ? `${kind}-${value}` : "all-"}`); } },
    h("span", { text: value || "All" }), n != null ? h("span", { class: "filter-n", text: ` ${n}` }) : null);
  };
  const sorted = (m) => [...m].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  fill(box, h("div", { class: "filter-chips", role: "group", "aria-label": "Show only grants from" },
    chip(null, null, null),
    ...sorted(agencies).map(([v, n]) => chip("agency", v, n)),
    ...sorted(codes).map(([v, n]) => chip("code", v, n))));
}

// Route B: companies with two or more kinds of public signal. Every sentence and count
// is written by code from the records; the card says it is an inference.
const INDUSTRY_NEEDS_PAPERS = "Industry leads need public papers: Perch finds companies through the works that cite yours, and this brief has none. Add your OpenAlex ID to see them.";

function renderIndustry(panel) {
  const st = stage("route_b");
  // A replay of a stored brief from before Route B has no such step (review W12 kept this).
  if (!S.brief.brief.stages.some((x) => x.name === "route_b")) {
    if (panel.dataset.sig === "oldB") return;
    panel.dataset.sig = "oldB";
    fill(panel, routeSwitch(), h("div", { class: "empty" }, owl("look", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: "This brief was built before Perch had industry leads." }),
        h("button", { class: "btn primary", onclick: rebuild }, h("span", { text: "Build again" })))));
    return;
  }
  if (!isDone("route_b")) {
    const failed = st.status === "failed" || S.brief.brief.status === "failed";
    const sig = `waitB:${failed}`;
    if (panel.dataset.sig === sig) return;
    panel.dataset.sig = sig;
    fill(panel, routeSwitch(), h("div", { class: "empty" }, owl(failed ? "droop" : "look", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: failed ? "The search for industry leads did not run."
        : "Industry leads appear here when that step finishes." }),
      h("p", { class: "hint", text: failed ? (st.detail || "See the steps above for what stopped.")
        : "Grant leads come first." }))), skeleton(3));
    return;
  }
  // T18: a brief from documents alone has no papers to find citing companies with, so the
  // step is skipped: one plain sentence, no warnings about leads that are not there.
  if (st.status === "skipped" && !S.brief.leads.some((l) => l.route === "B")) {
    if (panel.dataset.sig === "skippedB") return;
    panel.dataset.sig = "skippedB";
    fill(panel, routeSwitch(), h("div", { class: "empty skipped-b" }, owl("look", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: INDUSTRY_NEEDS_PAPERS }))));
    updateSwitch(panel);
    return;
  }
  const leads = sortedLeads();
  const active = leads.filter((l) => l.status !== "dismissed");
  const dismissed = leads.filter((l) => l.status === "dismissed");
  if (panel.dataset.sig !== "industry") {
    panel.dataset.sig = "industry";
    fill(panel, routeSwitch(),
      h("div", { class: "routes-bar" }, h("div", {}, h("h2", { class: "section-title", id: "routes-title" }),
        watchWarning(h("p", { class: "notice warn infer-note" }, icon("warn"), h("span", {
          text: "Inferred from public signals; not verified. A company that cites or works near your "
            + "research may have no interest in funding it. SBIR/STTR covers NIH awards only." }))),
        // One fixed line, the same as in the industry hand-off (perch/offices.py, Q13).
        h("p", { class: "hint security-note", text: RESEARCH_SECURITY }))),
      h("ol", { class: "leads", "aria-labelledby": "routes-title" }),
      h("div", { class: "dismissed-box" }));
  }
  updateSwitch(panel);
  panel.querySelector("#routes-title").textContent = f.plural(active.length, "industry lead");
  if (!leads.length) {
    fill(panel.querySelector(".leads"), h("li", { class: "empty" }, owl("worry", "owl-md"),
      h("div", {}, h("p", { class: "lede", text: "No company showed two kinds of public signal." }),
        h("p", { class: "hint", text: st.detail || "" }))));
    return;
  }
  syncList(panel.querySelector(".leads"), active);
  const box = panel.querySelector(".dismissed-box");
  if (!dismissed.length) { box.replaceChildren(); return; }
  let det = box.querySelector("details");
  if (!det) {
    det = h("details", { class: "dismissed" }, h("summary"), h("ol", { class: "leads" }));
    fill(box, det);
  }
  det.querySelector("summary").textContent = `Dismissed (${dismissed.length})`;
  syncList(det.querySelector("ol"), dismissed);
}

function sigRec(r) {
  return h("li", {}, h("button", { class: "paper-ref", "data-key": `rec-${r.id}`, onclick: (e) => openEvidence(r.id, e.currentTarget) },
    h("span", { class: "paper-ref-title", text: r.title || r.id }),
    h("span", { class: "paper-meta", text: [r.date ? f.formatDate(r.date) : null, r.venue].filter(Boolean).join(", ") })));
}

function orgCard(l) {
  const o = l.organisation || {};
  const name = o.name || l.record_id;
  const papers = S.brief.papers || {};
  const tags = h("span", { class: "tags" },
    l.relationship ? h("span", { class: "tag", text: l.relationship }) : null,
    h("span", { class: `evidence-level ${l.confidence || ""}`, text: l.confidence === "stronger"
      ? "Three kinds of signal" : "Two kinds of signal" }));
  const signals = h("ul", { class: "signals" }, (l.signal_items || []).map((s) => h("li", {},
    h("h4", { class: "mini", text: SIGNALS[s.kind] || s.kind }),
    h("p", { text: s.text }),
    // The newest record shows; the rest fold, so a card fits a phone screen (S22, audit S7).
    s.records.length ? h("ul", { class: "sig-recs" }, sigRec(s.records[0])) : null,
    s.records.length > 1 ? h("details", { class: "sig-more" },
      h("summary", { text: `Show ${s.records.length - 1} more` }),
      h("ul", { class: "sig-recs" }, s.records.slice(1).map(sigRec))) : null,
    s.more ? h("p", { class: "hint", text: `and ${s.more} more in the export` }) : null)));
  const cited = (l.cited_ids || []).filter((c) => c.startsWith("W"));
  const yours = cited.length ? h("details", { class: "why" },
    h("summary", { "data-key": "why" }, h("span", { text: "Your papers they cite" }),
      h("span", { class: "hint", text: ` ${cited.length}` })),
    h("ul", { class: "findings" }, cited.map((c) => h("li", {}, paperRef(c, papers))))) : null;
  const actions = l.status === "dismissed"
    ? [h("button", { class: "btn", "data-key": "restore", onclick: () => setLead(l.id, "restore") },
      icon("restore"), h("span", { text: "Restore" }))]
    : [h("button", { class: `btn keep${l.status === "kept" ? " on" : ""}`, "data-key": "keep",
      "aria-pressed": String(l.status === "kept"),
      onclick: () => setLead(l.id, l.status === "kept" ? "restore" : "keep") },
    icon("keep"), h("span", { text: l.status === "kept" ? "Kept" : "Keep" })),
    h("button", { class: "btn quiet", "data-key": "dismiss", onclick: () => setLead(l.id, "dismiss") },
      icon("dismiss"), h("span", { text: "Dismiss" }))];
  for (const b of actions) b.setAttribute("aria-describedby", `t-${cssId(l.id)}`);
  return h("li", { class: `card lead org${l.status === "kept" ? " kept" : ""}${l.status === "dismissed" ? " gone" : ""}`,
    "data-id": l.id },
  // The tags row stays on top; Keep and Dismiss sit in the footer row, as on a grant card (S50).
  h("div", { class: "org-tags" }, tags),
  h("h3", { class: "lead-title" }, h("button", { class: "title-btn", "data-key": "title", id: `t-${cssId(l.id)}`,
    onclick: (e) => openEvidence(l.record_id, e.currentTarget) }, h("span", { text: name }), evMark())),
  // Names merged into this lead, by exact name or by OpenAlex's parent link (U13).
  otherNames(o, name).length ? h("p", { class: "opp-num", text: `Also listed as ${otherNames(o, name).join("; ")}` }) : null,
  // S51 (W31): the line shows only for the model's own sentence; the list's banner already
  // says that industry leads are inferred from public signals.
  l.inference && l.inference !== ORG_FALLBACK ? h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Inference" }),
    h("span", { text: l.inference })) : null,
  signals, yours, leadFoot(null, actions));
}

const ORG_FALLBACK = "Inferred from public signals; not verified.";

// The other names merged into an industry lead; the name shown, with or without its
// country, is not repeated.
function otherNames(o, name) {
  return (o.aliases || []).filter((a) => a !== name && a.replace(/\s*\([^)]*\)\s*$/, "") !== name);
}

// Keyed update: a card is rebuilt only when its data changed, so focus and open
// sections survive polling.
function syncList(ol, leads) {
  const have = new Map([...ol.children].filter((c) => c.dataset.id).map((c) => [c.dataset.id, c]));
  const want = new Set(leads.map((l) => l.id));
  for (const [id, el] of have) if (!want.has(id)) el.remove();
  leads.forEach((l, i) => {
    const sig = JSON.stringify([l.status, l.match_score, l.explanation, l.inference, l.flagged,
      l.unsupported, l.cited_ids.length, isPending(l), Boolean(l.flagged && S.listWithheld), l.id === S.firstShown]);
    let el = have.get(l.id);
    if (!el || el.dataset.sig !== sig) {
      const focusKey = el && el.contains(document.activeElement)
        ? document.activeElement.dataset.key : null;
      const fresh = l.route === "B" ? orgCard(l) : leadCard(l);
      fresh.dataset.sig = sig;
      if (el) el.replaceWith(fresh); else ol.append(fresh);
      if (el && l.explanation && !el.querySelector(".why")) fresh.classList.add("landed");
      el = fresh;
      if (focusKey) { const t = el.querySelector(`[data-key="${focusKey}"]`); if (t) t.focus(); }
    }
    if (ol.children[i] !== el) ol.insertBefore(el, ol.children[i] || null);
  });
}

function cssId(s) {
  return String(s).replace(/[^A-Za-z0-9_-]/g, "_");
}

function isPending(l) {
  return !l.explanation && !l.flagged && Boolean(S.brief.brief.options.explain)
    && !isDone("explanations") && S.brief.brief.status !== "failed";
}

function leadCard(l) {
  const o = l.opportunity || {};
  const days = f.daysBetween(api.mode === "replay" ? S.brief.brief.options.as_of : today(), o.close_date);
  const urg = f.urgency(days);
  const size = f.awardSize(o);
  const band = f.fitBand(l.match_score);
  const pending = isPending(l);
  const parsed = f.parseExplanation(f.secondPerson(l.explanation), l.cited_ids, ownIds(o));

  let fit;
  if (band) {
    fit = matchPill(l.match_score, band);
  } else if (pending) {
    fit = h("span", { class: "fit pending" }, owl("work", "owl-xs"), h("span", { text: "Reading" }));
  }

  // S49 (M1, R3): the line under the title holds the agency, the activity code and a status
  // word, each only when the record has it, so no empty tag is ever drawn. The opportunity
  // number stays in the evidence panel.
  const subText = [f.agencyShort(o.agency, o.parent_agency), o.activity_code].filter((x) => x && String(x).trim()).join(" · ");
  const status = o.status && o.status !== "posted" ? (o.status === "forecasted" ? "Forecast" : o.status) : null;
  const sub = subText || status ? h("p", { class: "lead-sub" }, subText ? h("span", { text: subText }) : null,
    status ? h("span", { class: "tag ember", text: status }) : null) : null;

  // NSF dates its open-anytime programs decades out: past ten years the record's own
  // words stand in place of the date (U3, Q3). Evidence keeps both fields.
  // S50 (G8, BE-G): the record's own words, when it has them, stand in for a date ten years out
  // or for no date at all (a placeholder date reaches the page as null).
  const words = o.close_text || o.close_date_note || null;
  const far = Boolean(words && ((days !== null && days > 3650)
    || (!o.close_date && !o.deadline_quote && !(l.record && l.record.deadline_quote)))) || f.standardDates(o);
  const expires = f.expiresOnly(o);  // T17: a parent announcement's date is its expiry
  // FM3: with no date, the page's own deadline words are shown in quotes, never "Not stated".
  const quote = !o.close_date && !far ? (o.deadline_quote || (l.record && l.record.deadline_quote) || null) : null;
  const missing = () => h("span", { class: "missing", text: "Not stated" });
  // D5: always two facts, the date and the amount, so every card has the same shape.
  const facts = h("dl", { class: "facts facts-2" },
    // F20: an expiry date sits under its own label, not under "Closes".
    h("div", { class: `fact close ${urg}` }, h("dt", { text: quote ? "Deadline" : expires && !far ? "Announcement" : "Closes" }),
      h("dd", {}, far ? h("span", { text: words || o.close_date_note })
        : o.close_date ? h("span", { text: `${expires ? "Expires " : ""}${f.formatDate(o.close_date)}` })
          : quote ? h("span", { class: "quote-date", text: `The page says: “${quote}”` }) : missing(),
        !far && !expires && days !== null ? h("span", { class: "rel", text: f.closesIn(days) }) : null)),
    h("div", { class: "fact" }, h("dt", { text: "Amount" }), h("dd", {}, size ? h("span", { text: size }) : missing())));

  let explain = null;
  if (l.flagged) {
    // U3, S50 V5: when two or more cards on the list are flagged, the list says why once and
    // the card shows no reason section; a lone flagged card keeps its quiet line.
    explain = S.listWithheld ? null : h("p", { class: "hint withheld-line", text: "Written reason withheld: it failed the citation check." });
  } else if (pending) {
    explain = h("div", { class: "writing" }, skeleton(2), h("p", { class: "hint", text: "Writing a cited explanation" }));
  } else if (parsed) {
    explain = explanationBlock(l, parsed, o);
  }

  let actions;
  if (l.status === "dismissed") {
    actions = [h("button", { class: "btn", "data-key": "restore", onclick: () => setLead(l.id, "restore") },
      icon("restore"), h("span", { text: "Restore" }))];
  } else {
    actions = [
      h("button", { class: `btn keep${l.status === "kept" ? " on" : ""}`, "data-key": "keep",
        "aria-pressed": String(l.status === "kept"),
        onclick: () => setLead(l.id, l.status === "kept" ? "restore" : "keep") },
      icon("keep"), h("span", { text: l.status === "kept" ? "Kept" : "Keep" })),
      h("button", { class: "btn quiet", "data-key": "dismiss", onclick: () => setLead(l.id, "dismiss") },
        icon("dismiss"), h("span", { text: "Dismiss" }))];
  }

  for (const b of actions) b.setAttribute("aria-describedby", `t-${cssId(l.id)}`);
  return h("li", { class: `card lead${l.status === "kept" ? " kept" : ""}${l.status === "dismissed" ? " gone" : ""}`,
    "data-id": l.id },
  // The title comes first (S49 D5) and keeps the row but for the Match pill (S50 V2).
  h("div", { class: "lead-top" },
    h("div", { class: "lead-name" },
      h("h3", { class: "lead-title" }, h("button", { class: "title-btn", "data-key": "title", id: `t-${cssId(l.id)}`,
        onclick: (e) => openEvidence(l.record_id, e.currentTarget) }, h("span", { text: o.title || "Untitled opportunity" }), evMark())),
      sub),
    fit ? h("div", { class: "lead-pill" }, fit) : null),
  facts, leadNotes(l), explain,
  // S50 (V2, V39): one footer row: cover-letter points on the left (S46, every grant lead that
  // is not dismissed), Keep and Dismiss on the right.
  leadFoot(l.status === "dismissed" ? null : coverBlock(coverCtx(), S.briefId, l.record_id), actions));
}

// The card's footer row (S50 contract 3.2): the cover-letter block, when there is one, then the actions.
function leadFoot(cover, actions) {
  return h("div", { class: "lead-foot" }, cover || null, h("div", { class: "actions" }, actions));
}

// What cover.js needs for a researcher card and for the list's one line (S49 U16).
function coverCtx() {
  return { api, announce, openEvidence, guest: Boolean(S.session.guest), signIn: signInHref(), audience: "researcher",
    stored: (S.brief && S.brief.cover_points) || [], accountsOpen: accountsOpen() };
}

// S51 (D4, contract 3.2): /auth/session says whether accounts are open; a missing field means open.
function accountsOpen() {
  return !S.session || S.session.accounts_open !== false;
}

// Rule notes written by code: a career-stage unlock, a past sponsor, what the user said.
function leadNotes(l) {
  if (!l.notes || !l.notes.length) return null;
  // Each note is a plain line written by code, such as a past date on the page (S49).
  return h("ul", { class: "lead-notes" }, l.notes.map((n) => h("li", { text: n })));
}

function explanationBlock(l, parsed, o) {
  const papers = S.brief.papers || {};
  const weakBand = (f.fitBand(l.match_score) || {}).key === "weak";
  if (parsed.raw) {
    return h("div", { class: "explain" },
      h("p", { class: "what" }, modelWord(), " ", renderSegs(parsed.raw, ownIds(o))), fitWhy(l, o, weakBand));
  }
  const inference = fitWhy(l, o, weakBand);
  // With the researcher's CV or current research in the brief, the first card shown starts
  // open (S51 W14; it was every card since S27). The verdict is on every card's face now.
  const own = Object.values(papers).some(isOwnDoc);
  const open = own && l.id === S.firstShown ? !S.shut.has(l.id) : S.open.has(l.id);
  const n = parsed.findings.length;
  const docs = parsed.findings.filter((x) => isOwnDoc(papers[x.paper]) || /^user:/.test(x.paper)).length;
  const why = h("details", { class: "why", open,
    ontoggle: (e) => {
      if (e.target.open) { S.open.add(l.id); S.shut.delete(l.id); } else { S.open.delete(l.id); S.shut.add(l.id); }
    } },
  h("summary", { "data-key": "why" }, h("span", { text: weakBand ? "How it relates" : "Why it fits" }),
    h("span", { class: "hint", text: docs && docs < n
      ? ` cites ${f.plural(n, "paper or document", "papers and documents")}`
      : docs ? ` cites ${f.plural(n, "document")}` : ` cites ${f.plural(n, "paper")} by the researcher` })),
  // S51 (W13): what the call funds opens the disclosure; the verdict moved to the face.
  inference ? h("p", { class: "what" }, modelWord(), " ", renderSegs(parsed.opportunity, ownIds(o))) : null,
  // A cited document is not a paper; with the SYNTHETIC sample it is not even theirs (U11).
  // With no paper cited, the heading names the documents alone (G1).
  h("h4", { class: "mini", text: docs && docs < n
    ? (sampleSteered() ? "From the researcher’s papers and the sample document" : "From the researcher’s papers and documents")
    : docs ? (sampleSteered() ? "From the sample document" : "From your documents") : "From the researcher’s papers" }),
  h("ul", { class: "findings" }, parsed.findings.map((x) => h("li", {},
    paperRef(x.paper, papers), h("p", { text: `${x.text}.` })))),
  unsupportedFold(l.unsupported),
  eligibilityRows(o));
  return h("div", { class: "explain" },
    inference || h("p", { class: "what" }, modelWord(), " ", renderSegs(parsed.opportunity, ownIds(o))), why);
}

// The fit verdict on the card's face (S51 W13): the model's inference, labelled as the
// disclosure's summary is, and tagged Inference. Chips for the card's own record are left out.
function fitWhy(l, o, weakBand) {
  if (!l.inference) return null;
  return h("p", { class: "fit-why" }, h("b", { text: weakBand ? "How it relates: " : "Why it fits: " }),
    renderSegs(f.segments(f.secondPerson(l.inference), new Set(l.cited_ids), ownIds(o)), ownIds(o)),
    h("span", { class: "tag model", text: "Inference" }));
}

// Sentences the citation check could not match to a source (S51 contract 3.2, W19): a quiet
// fold that lists each one as it came. FE-B emits the same markup on the student card.
function unsupportedFold(list) {
  if (!list || !list.length) return null;
  return h("details", { class: "unsupported-fold" },
    h("summary", { "data-key": "unsupported", text: list.length === 1 ? "1 sentence could not be matched to its source"
      : `${list.length} sentences could not be matched to their source` }),
    h("ul", {}, list.map((u) => h("li", { text: u }))));
}

function modelWord() {
  return h("span", { class: "tag model", text: "Model text" });
}

// A document the user supplied (id user:..., source "user"), not a public record.
function isOwnDoc(w) {
  return Boolean(w && (w.source === "user" || w.kind === "user"));
}

function ownLabel(text = "Your own document") {
  return h("span", { class: "tag lock" }, icon("lock"), h("span", { text }));
}

function ownIds(o) {
  return new Set([o.opportunity_number, o.id].filter(Boolean));
}

function eligibilityRows(o) {
  const rows = f.higherEdRows(o.eligible_applicants);
  if (!rows.length) return null;
  return h("div", { class: "elig" }, h("h4", { class: "mini", text: "Eligible applicants include" }),
    h("ul", {}, rows.map((r) => h("li", { text: r }))));
}

// Citation chips stay on one line with the punctuation after them. A card's citation
// of its own opportunity is dropped: the card is that record.
function renderSegs(segs, skip = new Set()) {
  const papers = S.brief.papers || {};
  const out = [];
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    if (typeof s === "string") { out.push(s); continue; }
    if (skip.has(s.cite)) {
      if (typeof out[out.length - 1] === "string") out[out.length - 1] = out[out.length - 1].replace(/\s+$/, "");
      continue;
    }
    const next = segs[i + 1];
    const m = typeof next === "string" ? next.match(/^[.,;:)]+/) : null;
    if (m) segs[i + 1] = next.slice(m[0].length);
    // the punctuation after a chip stays on its line (S49: the chip itself does not wrap)
    out.push(m ? h("span", { class: "nowrap" }, cite(s.cite, papers), m[0]) : cite(s.cite, papers));
  }
  return out;
}

function paperRef(id, papers) {
  const w = papers[`https://openalex.org/${id}`] || papers[id];
  return h("button", { class: `paper-ref${isOwnDoc(w) ? " own" : ""}`, "data-key": `cite-${id}`,
    onclick: (e) => openEvidence(id, e.currentTarget) },
  isOwnDoc(w) ? ownLabel(sampleSteered() ? "From the sample student’s document" : undefined) : null,
  isOwnDoc(w) && sampleSteered() ? h("span", { class: "sample-badge", text: "Sample data" }) : null,
  h("span", { class: "paper-ref-title", text: w ? w.title : id }),
  w && w.publication_year ? h("span", { class: "paper-meta", text: [w.publication_year, w.venue].filter(Boolean).join(", ") }) : null);
}

function cite(id, papers) {
  const w = papers[`https://openalex.org/${id}`] || papers[id];
  let label = id;
  if (isOwnDoc(w)) {
    return h("button", { class: "cite own", "data-key": `cite-${id}`,
      "aria-label": `Evidence: ${w.title}, from ${sampleSteered() ? "the SYNTHETIC sample student’s document" : "your own document"}`,
      onclick: (e) => openEvidence(id, e.currentTarget) }, icon("lock"), h("span", { text: w.title }),
    sampleSteered() ? h("span", { class: "sample-badge", text: "Sample data" }) : null);
  }
  if (w) {
    const t = w.title.length > 34 ? `${w.title.slice(0, 32).trimEnd()}…` : w.title;
    label = `${t}${w.publication_year ? `, ${w.publication_year}` : ""}`;
  }
  return h("button", { class: `cite${w ? " paper-cite" : ""}`, "data-key": `cite-${id}`,
    "aria-label": `Evidence: ${w ? w.title : id}`,
    onclick: (e) => openEvidence(id, e.currentTarget) }, h("span", { text: label }));
}

// The brief on screen was built from the SYNTHETIC sample student: its "documents" are
// invented. The server says so in the brief's options.
function sampleSteered() {
  return Boolean(S.brief && S.brief.brief.options && S.brief.brief.options.sample);
}

// The card's rule for a far-off placeholder close date (U3, Q3): a deadline note and a
// date more than ten years out.
function farClose(o) {
  const days = o.close_date ? f.daysBetween(api.mode === "replay" ? S.brief.brief.options.as_of : today(), o.close_date) : null;
  return Boolean(o.close_date_note && days !== null && days > 3650);
}

function today() {
  return f.localToday();
}

async function setLead(leadId, action) {
  const l = leadsOf().find((x) => x.id === leadId);
  if (!l) return;
  const list = [...document.querySelectorAll("#panel .leads > li[data-id]")].filter((x) => !x.closest(".dismissed"));
  const at = list.findIndex((x) => x.dataset.id === leadId);
  const before = l.status;
  l.status = { keep: "kept", dismiss: "dismissed", restore: "new" }[action];
  renderPanel();
  renderTabs();
  if (action === "dismiss") announce("Dismissed. It is in the Dismissed list at the bottom, where you can restore it.");
  // The keep bar became the shortlist and the floating pill in S24 (review W7).
  if (action === "keep") announce("Kept. It is in your shortlist; Compare opens the comparison.");
  try {
    await api.setLead(S.briefId, l.id, action);
  } catch (e) {
    l.status = before;
    renderPanel();
    announce(`That change was not saved: ${e.message}`);
  }
  if (action === "dismiss") {
    // focus the card that took this one's place, or the one before it at the end
    const now = [...document.querySelectorAll("#panel .leads > li[data-id]")].filter((x) => !x.closest(".dismissed"));
    const next = now[Math.min(at, now.length - 1)];
    const target = next && next.querySelector(".title-btn");
    if (target) target.focus();
  }
}

// ---------- evidence panel ----------

let evidenceOpener = null;
let evidenceAsk = 0;  // the latest record asked for; an older answer arriving late is dropped
let evidenceClosing = null;
let evidenceClick = false;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Going from record to record crossfades (S27): the old record fades out while the new one
// is fetched, then the new one fades in. The owl shows only when a fetch is slow.
async function swapRecord(box, id, show) {
  const ask = ++evidenceAsk;
  box.classList.add("swap");
  const slow = setTimeout(() => {
    if (ask !== evidenceAsk) return;
    show(h("div", { class: "loading" }, owl("look", "owl-sm"), h("p", { text: "Fetching the record" })));
    box.classList.remove("swap");
  }, 400);
  let r = null, err = null;
  try { [r] = await Promise.all([api.record(id), wait(130)]); } catch (e) { err = e; }
  clearTimeout(slow);
  if (ask !== evidenceAsk) return null;
  if (err) show(h("p", { class: "notice error" }, icon("warn"), h("span", { text: `The record could not be opened: ${err.message}` })));
  else show(...recordView(r));
  box.scrollTop = 0;
  box.classList.remove("swap");
  return r;
}

async function openEvidence(id, opener) {
  // On a laptop the record opens in the rail beside the list (S24); elsewhere, and on a
  // phone, in the sheet. On a laptop the sheet slides in over the page and leaves the page
  // where it is (S27).
  const railEv = $("#rail-ev");
  if (railEv && railEv.offsetParent !== null && window.matchMedia("(min-width: 901px)").matches) {
    return openInRail(railEv, id, opener);
  }
  evidenceOpener = opener || null;
  evidenceClick = true;  // this click opened it; the outside-click check lets it through
  setTimeout(() => { evidenceClick = false; });
  const panel = $("#evidence");
  const body = $("#evidence-body");
  const wasOpen = !panel.hidden && panel.classList.contains("in");
  clearTimeout(evidenceClosing);
  if (!wasOpen) {
    fill(body);
    $("#evidence-kind").textContent = "Evidence";
    const modal = !window.matchMedia("(min-width: 960px)").matches;
    panel.setAttribute("aria-modal", String(modal));
    panel.setAttribute("aria-labelledby", "evidence-kind");
    for (const el of [main(), $(".bar"), $(".foot"), $("#banner")]) el.inert = modal;
    panel.hidden = false;
    document.body.classList.add("sheet-open");
    void panel.offsetWidth;  // lay the closed sheet out first, so the slide-in runs
    panel.classList.add("in");
    $("#evidence-close").focus();
  }
  const r = await swapRecord(body, id, (...nodes) => fill(body, ...nodes));
  if (!r || panel.hidden) return;
  $("#evidence-kind").textContent = KINDS[r.kind] || "Record";
  panel.setAttribute("aria-labelledby", "evidence-kind evidence-title");
}

async function openInRail(box, id, opener) {
  document.querySelectorAll("#panel .lead.selected").forEach((x) => x.classList.remove("selected"));
  const card = opener && opener.closest && opener.closest(".lead");
  if (card) card.classList.add("selected");
  const r = await swapRecord(box, id, (...nodes) => fill(box, h("p", { class: "ev-kind", text: "Evidence" }), ...nodes));
  railFade(box);
  if (!r) return;
  box.querySelector(".ev-kind").textContent = `Evidence · ${KINDS[r.kind] || "Record"}`;
  box.setAttribute("aria-labelledby", "evidence-title");
  announce(`Evidence: ${r.title || r.name || r.display_name || "record"} is in the panel beside the list.`);
}

function closeEvidence({ refocus = true } = {}) {
  const panel = $("#evidence");
  if (panel.hidden) return;
  evidenceAsk++;
  panel.classList.remove("in");
  document.body.classList.remove("sheet-open");
  for (const el of [main(), $(".bar"), $(".foot"), $("#banner")]) el.inert = false;
  // Hide once the slide-out has run; the reduced-motion rule makes that instant.
  const ms = parseFloat(getComputedStyle(panel).transitionDuration) * 1000 || 0;
  clearTimeout(evidenceClosing);
  evidenceClosing = setTimeout(() => { panel.hidden = true; }, ms);
  // Focus goes back to the opener after the close button or Escape, not after a click elsewhere.
  if (refocus && evidenceOpener && document.contains(evidenceOpener)) evidenceOpener.focus({ preventScroll: true });
}

function field(label, value, kind) {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) return null;
  return h("div", { class: kind ? `field ${kind}` : "field" }, h("dt", { text: label }), h("dd", {}, value));
}

// Enum values from the records read as words on screen: "bachelor's" is "Bachelor's" (U33).
// Display only; the record keeps its own text.
const titled = (v) => (Array.isArray(v) ? v : [v]).filter(Boolean)
  .map((x) => String(x).replace(/(^|[\s,/])(\p{L})/gu, (m, a, b) => a + b.toUpperCase())).join(", ");
// The canary sentence a synthetic record's Purpose ends with. It shows in its own Test marker row.
const CANARY_TAIL = /\s*SYNTHETIC sample record, canary \S+$/;

function recordView(r) {
  const out = [];
  if (r.kind === "scholarship") {
    const e = r.eligibility || {};
    const req = r.application_requirements;
    const items = [];
    if (req) {
      if (req.transcript) items.push("Transcript");
      if (req.essay) items.push("Essay");
      if (req.letters_count) items.push(`${req.letters_count} letter${req.letters_count > 1 ? "s" : ""} of recommendation`);
      if (req.portfolio) items.push("Portfolio");
      if (req.interview) items.push("Interview");
      if (req.fafsa) items.push("FAFSA");
    }
    const amt = r.amount_max != null ? (r.amount_min != null && r.amount_min !== r.amount_max
      ? `${f.money(r.amount_min)} to ${f.money(r.amount_max)}`
      : (r.source === "temple_sdfa" && r.amount_min == null ? `Up to ${f.money(r.amount_max)}` : f.money(r.amount_max))) : "Not stated in the record";
    // A public fellowship's deadline or amount is copied by code from the award's own page.
    const page = r.source === "temple_sdfa" && Boolean(r.details_url);
    const pageHint = h("span", { class: "from-page", text: " (from the award's page)" });
    out.push(r.source === "synthetic" ? h("p", { class: "notice warn sample-note" }, h("span", { class: "tag sample", text: "Sample data" }),
      h("span", { text: " An invented record from a test corpus. Not a real scholarship." })) : null,
    h("h2", { class: "rec-title", id: "evidence-title", text: r.name }),
    h("dl", { class: "fields" },
      field("Sponsor", r.sponsor), field("Purpose", (r.purpose || "").replace(CANARY_TAIL, "")), field("Type", titled(r.award_type)),
      field("Level", titled(r.level_of_study) || "Not stated in the record"),
      field("Field", titled(r.field_of_study)),
      field("Amount", page && r.amount_max != null ? [amt, pageHint] : amt),
      field("Deadline", page && r.deadline ? [f.formatDate(r.deadline), pageHint] : (f.formatDate(r.deadline) || "Not stated in the record")),
      field("Minimum GPA", e.gpa_min != null ? e.gpa_min.toFixed(2) : null),
      field("Undergraduate year", (e.class_year || []).join(", ")),
      field("Majors", (e.major || []).join(", ")),
      field("Enrollment", titled(e.enrolment_status)),
      field("Residency", e.residency_state), field("Citizenship", e.citizenship),
      field("Also asks (you decide)", e.targeted_criterion),
      field("Listing notes", e.notes),
      field("Application asks for", items.join(", ")),
      field("May be open to international students", r.international_ok ? "Yes, per the listing" : null),
      field("Source", SOURCES[r.source] || r.source),
      field("Fetched", f.formatDate(r.fetched_at)),
      r.source === "synthetic" ? field("Test marker", r.canary, "muted") : null),
    page && (r.deadline_quote || r.amount_quote) ? h("div", { class: "page-read" },
      h("p", { class: "hint", text: `Copied by code from the award's page, fetched ${f.formatDate(r.details_fetched_at)}:` }),
      r.deadline_quote ? h("blockquote", {}, h("b", { text: "Deadline: " }), `\u201c${r.deadline_quote}\u201d`) : null,
      r.amount_quote ? h("blockquote", {}, h("b", { text: "Amount: " }), `\u201c${r.amount_quote}\u201d`) : null,
      f.safeUrl(r.details_url) ? h("p", {}, h("a", { href: f.safeUrl(r.details_url), target: "_blank", rel: "noopener", text: "Open the page these came from" })) : null) : null,
    r.source !== "synthetic" && f.safeUrl(r.source_url) ? h("p", {}, h("a", { href: f.safeUrl(r.source_url), target: "_blank", rel: "noopener", text: "Open the public page" })) : null);
    return out.filter(Boolean);
  }
  if (r.kind === "opportunity") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("dl", { class: "fields" },
        field("Opportunity number", r.opportunity_number), field("Agency", r.agency),
        field("Department", r.parent_agency),
        field("Status", r.status ? r.status[0].toUpperCase() + r.status.slice(1) : null),
        field("Posted", f.formatDate(r.open_date)),
        // T21: a far-off placeholder date follows the record's own words and says what it is.
        ...(farClose(r) ? [field("Deadline note", r.close_date_note),
          field("Closes (placeholder in the record)", f.formatDate(r.close_date))]
          : [field("Closes", f.formatDate(r.close_date) || "Not stated in the record"),
            field("Deadline note", r.close_date_note)]),
        field("Archive date", f.formatDate(r.archive_date)),
        field("Award ceiling", r.award_ceiling ? f.money(r.award_ceiling) : "Not stated in the record"),
        field("Award floor", r.award_floor ? f.money(r.award_floor) : "Not stated in the record"),
        field("Activity code", r.activity_code),
        field("Funding instrument", (r.funding_instruments || []).join(", ")),
        field("Assistance listings", (r.assistance_listings || []).join(", "))));
    const all = r.eligible_applicants || [];
    // University types first and the rest behind a toggle; with no university type,
    // the record's own list shows as it is (S27).
    const uni = f.higherEdRows(all);
    const higher = uni.length ? uni : all;
    if (all.length) {
      out.push(h("h3", { class: "mini", text: "Eligible applicants" }),
        h("ul", { class: "elig-list" }, higher.map((x) => h("li", { class: uni.includes(x) ? "hi" : null, text: x }))),
        all.length > higher.length ? h("details", { class: "more" },
          h("summary", { text: `Show ${f.plural(all.length - higher.length, "other applicant type", "other applicant types")}` }),
          h("ul", { class: "elig-list" }, all.filter((x) => !higher.includes(x)).map((x) => h("li", { text: x })))) : null);
    }
    if (r.eligibility_notes) out.push(h("h3", { class: "mini", text: "Eligibility notes" }), longText(r.eligibility_notes));
    if (r.description) out.push(h("h3", { class: "mini", text: "Description" }), longText(r.description));
  } else if (r.kind === "user") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("p", {}, ownLabel()), longText(r.text || ""));
  } else if (r.kind === "work") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("dl", { class: "fields" }, field("Year", r.publication_year), field("Venue", r.venue),
        field("Type", r.type),
        field("DOI", r.doi ? h("a", { href: f.doiUrl(r.doi), target: "_blank", rel: "noopener", text: r.doi.replace(/^https?:\/\/doi\.org\//, "") }) : null),
        field("Cited by", r.cited_by_count !== null ? r.cited_by_count.toLocaleString("en-US") : null)));
    if (r.abstract) out.push(h("h3", { class: "mini", text: "Abstract" }), longText(r.abstract));
  } else if (r.kind === "award") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.title }),
      h("dl", { class: "fields" }, field("Agency", r.agency), field("Award number", r.award_number),
        field("Start", f.formatDate(r.start_date)), field("End", f.formatDate(r.end_date)),
        field("Amount", r.amount ? `${f.money(r.amount)}${r.amount_basis ? ` (${r.amount_basis})` : ""}` : "Not stated in the record"),
        field("Fiscal year", r.fiscal_year), field("Activity code", r.activity_code),
        field("Funding opportunity", r.opportunity_number), field("Institution", r.institution)));
  } else if (r.kind === "lead" && r.route === "B") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: `Industry lead ${r.rank}` }),
      h("p", { class: "provenance" }, h("span", { class: "tag model", text: "Inference" }), h("span", { text: r.inference || "" })),
      h("p", { text: r.explanation || "" }),
      h("dl", { class: "fields" }, field("Suggested relationship", r.relationship),
        field("Organization", h("button", { class: "cite", onclick: (e) => openEvidence(r.record_id, e.currentTarget) },
          h("span", { text: "Open the organization record" })))));
  } else if (r.kind === "organisation") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.name }),
      h("dl", { class: "fields" }, field("Type", r.type), field("Country", r.country),
        field("Names merged", (r.aliases || []).length > 1 ? r.aliases.join("; ") : null)),
      h("p", { class: "hint", text: "Perch counts a company's signals under one name when the source "
        + "names match exactly, apart from case, punctuation, a country in brackets and a legal form such as Inc." }));
  } else if (r.kind === "researcher") {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.display_name }),
      h("dl", { class: "fields" }, field("Institutions", (r.institutions || []).join(", ")),
        field("Works", r.works_count), field("Cited by", r.cited_by_count),
        field("ORCID", r.orcid)));
  } else {
    out.push(h("h2", { class: "rec-title", id: "evidence-title", text: r.id }));
  }
  const url = f.safeUrl(r.source_url);
  if (url) {
    out.splice(1, 0, h("p", { class: "source-top" }, h("a", { class: "btn primary", href: url, target: "_blank", rel: "noopener" },
      icon("external"), h("span", { text: `Open at ${SOURCES[r.source] || "the source"}` }))));
  }
  out.push(h("div", { class: "source" },
    h("p", {}, h("span", { class: "hint", text: "Source " }), h("b", { text: SOURCES[r.source] || r.source })),
    // F21: the Grants.gov attribution is the page footer's, on every screen; the panel no
    // longer prints it a second time.
    h("p", { class: "hint", text: `${r.source === "user" ? "Added" : "Fetched"} ${fetched(r.fetched_at)}` })));
  return out;
}

function fetched(iso) {
  if (!iso) return "at an unknown time";
  return `${f.formatDate(iso)}, ${iso.slice(11, 16)} UTC`;
}

// Long record text shows once, cut to a few lines; the button opens it in place (S27).
let longSeq = 0;
function longText(text) {
  const t = String(text);
  if (t.length <= 700) return h("p", { class: "long", text: t });
  const id = `long-${++longSeq}`;
  const p = h("p", { class: "long clamped", id, text: t });
  const btn = h("button", { type: "button", class: "more-btn", "aria-expanded": "false", "aria-controls": id,
    onclick: () => {
      const open = p.classList.toggle("clamped") === false;
      btn.setAttribute("aria-expanded", String(open));
      btn.lastChild.textContent = open ? "Show less" : "Show the full text";
    } }, h("span", { text: "Show the full text" }));
  return h("div", { class: "long-wrap" }, p, btn);
}

// ---------- theme ----------

const THEMES = ["system", "light", "dark"];

function applyTheme(t) {
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  const b = $("#theme");
  const word = { system: "Auto", light: "Light", dark: "Dark" }[t];
  b.setAttribute("aria-label", `Theme: ${word}`);
  b.querySelector(".theme-word").textContent = word;
  syncThemeItem();
}

function initTheme() {
  let t = "system";
  try { t = localStorage.getItem("perch.theme") || "system"; } catch { /* default */ }
  if (!THEMES.includes(t)) t = "system";
  applyTheme(t);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || "system";
    const next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
    applyTheme(next);
    try { localStorage.setItem("perch.theme", next); } catch { /* convenience only */ }
  });
}

// ---------- start ----------

function init() {
  document.addEventListener("click", (e) => {
    const o = e.target.closest(".owl");
    if (o && !o.classList.contains("owl-xs")) poke(o);
  });
  initTheme();
  $("#evidence-close").addEventListener("click", closeEvidence);
  $("#evidence-scrim").addEventListener("click", closeEvidence);
  // A click anywhere outside the open Evidence card closes it (S27, Dakshitha). A click
  // that opens another record switches the card instead.
  document.addEventListener("click", (e) => {
    const panel = $("#evidence");
    if (panel.hidden || evidenceClick || panel.contains(e.target)) return;
    closeEvidence({ refocus: false });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeEvidence();
    if (e.key === "Tab" && !$("#evidence").hidden && window.matchMedia("(max-width: 959px)").matches) {
      const items = [...$("#evidence").querySelectorAll("button, a[href], summary, [tabindex='0']")].filter((x) => x.offsetParent);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  if (api.mode === "replay" && window.PERCH_EXAMPLE) {
    // The example brief (S50 Q22): labelled plainly, the researcher by alias, with its date.
    const d = window.PERCH_REPLAY;
    const built = f.formatDate(d.brief.brief.created_at);
    const b = $("#banner");
    b.hidden = false;
    b.classList.add("example-banner");
    fill(b, h("p", { class: "banner-line", "data-key": "example-banner" }, h("span", { class: "tag ember", text: "Example" }),
      h("span", { text: d.student
        ? `A saved brief for an invented SYNTHETIC student, built ${built}: real Temple listings and invented sample scholarships. It plays back from a file: nothing is saved.`
        : `A saved brief for a Temple researcher, shown as ${(d.candidates[0] || {}).display_name || "a researcher"}, built ${built} from public records. It plays back from a file: nothing here calls a model or saves anything.` }),
      h("a", { href: "./", text: "Back to Perch" })));
    document.title = "Example brief — Perch";
    S.find.q = (d.candidates[0] || {}).display_name || "";
  } else if (api.mode === "replay") {
    const b = $("#banner");
    b.hidden = false;
    fill(b, h("p", {}, h("b", { text: "Preview. " }),
      h("span", { text: window.PERCH_REPLAY.student
        ? "A SYNTHETIC student brief, played back: an invented student, real fellowship listings and sample scholarships."
        : "A saved brief, played back. Press Find, then This is the one and Build brief, to watch it build." }),
      h("a", { href: `#/brief/${encodeURIComponent(api.briefId)}/routes`, text: "Skip to the result" })));
    S.find.q = (window.PERCH_REPLAY.candidates[0] || {}).display_name || "";
  }
  $(".skip").addEventListener("click", (e) => { e.preventDefault(); main().focus(); });
  // A real click outside the open Export menu closes it; a download clicks a link of its
  // own. One listener for every brief drawn (review W17).
  document.addEventListener("click", (e) => {
    for (const det of document.querySelectorAll("details.export-menu[open], details.ready-chip[open]")) {
      if (e.isTrusted && !det.contains(e.target)) det.open = false;
    }
  });
  // The page's scroll bar is always visible (S49 U4): a bar that appears only near the
  // pointer hid how long the page is.
  const setBar = () => document.documentElement.style.setProperty("--bar-h", `${$(".bar").offsetHeight}px`);
  setBar();
  window.addEventListener("resize", setBar);
  // The header's height changes when the guest chip or the account chip appears (S43 S3).
  if (window.ResizeObserver) new ResizeObserver(setBar).observe($(".bar"));
  window.addEventListener("hashchange", route);
  if (api.mode === "replay") {
    S.who = window.PERCH_REPLAY.student ? "s" : "r";
    route();
    return;
  }
  // The server says who is here before the first screen is drawn. A signed-in visitor
  // lands on the side they used last; a signed-out one always lands on Student.
  // A sign-in that did not finish comes back as #/?signin=failed or =unavailable (S43 M1).
  const signin = new URLSearchParams(location.hash.split("?")[1] || "").get("signin");
  if (signin) {
    history.replaceState(null, "", "#/");
    S.signinDown = signin === "unavailable";
    S.flash = signin === "unavailable"
      ? "Sign-in is not available right now. You can still try a sample student."
      : "Sign-in did not finish. Try again.";
    S.flashFor = "#/";
  }
  refreshSession().then((sess) => {
    if (sess.signed_in && sess.audience) S.who = sess.audience === "researcher" ? "r" : "s";
    route();
  });
}

init();
