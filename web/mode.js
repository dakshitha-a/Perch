// Private mode as a state of the whole app (S18, docs/design/PRIVATE_MODE.md, "Private
// mode as a state"). No DOM here, so Node can test the order of requests: a private
// session always starts before any personal text is sent, and no content guess ever
// turns the mode on or off by itself.

// A browser-only check for text that looks personal: long, or shaped like a CV. It only
// offers a move into private mode; it never sends the text and never switches the mode.
const CV_MARKS = [/\beducation\b/i, /\bgpa\b/i, /\breferences?\b/i, /\bexperience\b/i,
  /\bcurriculum vitae\b|\bresum[eé]\b/i, /\bexpected graduation\b/i, /\bhonou?rs\b/i,
  /[\w.+-]+@[\w-]+\.[\w.]+/, /\+?\d[\d\s().-]{8,}\d/, /\bemployment\b/i, /\bpublications?\b/i];
export const NUDGE_CHARS = 280;

export function looksPersonal(text) {
  const t = String(text || "");
  if (t.trim().length >= NUDGE_CHARS) return true;
  const marks = CV_MARKS.filter((re) => re.test(t)).length;
  const lines = t.split(/\n/).filter((l) => l.trim()).length;
  return marks >= 2 || (marks >= 1 && lines >= 4);
}

// The mode controller. `api` is the private API client (start, end, addDocument, open);
// `hooks.onChange(state)` redraws the frame. Drafts are held here, in memory only, until
// the user adds them: moving text into private mode never sends it.
export function createMode(api, hooks = {}) {
  const st = { available: false, reason: "", on: false, drafts: {} };
  const changed = () => { if (hooks.onChange) hooks.onChange(st); };
  return {
    state: st,
    setAvailable(ok, reason = "") { st.available = ok; st.reason = ok ? "" : reason; changed(); },
    // Start a session if none is open. Every path that takes personal text calls this
    // first and waits for it.
    async enable() {
      if (!st.available) throw new Error(st.reason || "Private mode is not available here.");
      if (!api.open) await api.start();
      st.on = true;
      changed();
    },
    // Send one document; the session is opened first if needed.
    async send(body) {
      await this.enable();
      return api.addDocument(body);
    },
    // Move pasted text out of a public field: open the session, keep the text as an
    // unsent draft. Nothing leaves the browser until the user adds it.
    async move(kind, text) {
      await this.enable();
      st.drafts[kind] = text;
      changed();
    },
    // What turning the switch off discards, for the confirm.
    discards(docs = [], hasBrief = false) {
      const out = docs.map((d) => d.label || d.kind);
      if (Object.values(st.drafts).some((x) => x && x.trim())) out.push("Unsent text you moved here");
      if (hasBrief) out.push("Your private brief, its leads and any drafts");
      return out;
    },
    // Off means end: only after the user confirms.
    async disable(confirm) {
      if (!st.on && !api.open) return true;
      if (confirm && !(await confirm())) return false;
      await api.end();
      st.on = false;
      st.drafts = {};
      changed();
      return true;
    },
  };
}
