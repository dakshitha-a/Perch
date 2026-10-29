// Pure helpers: dates, amounts, labels and explanation parsing. No DOM here, so
// tests/test_web.py can run them under Node when it is installed.

export const STAGES = {
  researcher: "Confirming the researcher",
  works: "Reading the papers",
  awards: "Finding public awards",
  profile: "Mapping research threads",
  route_a: "Searching open opportunities",
  route_b: "Finding industry leads",
  summary: "Summarising the profile",
  explanations: "Explaining each lead",
};

// Short names for agencies as Grants.gov spells them; anything else shows in full.
const AGENCY_SHORT = {
  "National Institutes of Health": "NIH",
  "National Science Foundation": "NSF",
  "Department of Energy": "DOE",
  "Department of Defense": "DOD",
  "Agency for Health Care Research and Quality": "AHRQ",
  "Centers for Disease Control and Prevention": "CDC",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
  "Dec"];

export function parseDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Number.isFinite(y) ? new Date(Date.UTC(y, (m || 1) - 1, d || 1)) : null;
}

// "28 Oct 2027", from the record's own date string, never shifted by time zone.
export function formatDate(iso) {
  const d = parseDate(iso);
  return d ? `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}` : "";
}

export function daysBetween(fromIso, toIso) {
  const a = parseDate(fromIso), b = parseDate(toIso);
  return a && b ? Math.round((b - a) / 86400000) : null;
}

// Plain-words distance to a date, computed by code from two record dates.
export function until(days) {
  if (days === null) return "";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days < 60) return `in ${days} days`;
  const months = Math.round(days / 30.44);
  if (months < 24) return `in ${months} months`;
  return `in ${Math.floor(months / 12)} years`;
}

export function closesIn(days) {
  if (days === null) return "";
  if (days < 0) return "closed";
  if (days === 0) return "closes today";
  return until(days);
}

export function urgency(days) {
  if (days === null) return "none";
  if (days < 0) return "closed";
  if (days <= 30) return "soon";
  return "open";
}

// Amounts exactly as stored, with separators; never rounded.
export function money(n) {
  return "$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function awardSize(opp) {
  const lo = opp.award_floor, hi = opp.award_ceiling;
  if (hi && lo) return `${money(lo)} to ${money(hi)}`;
  if (hi) return `Up to ${money(hi)}`;
  if (lo) return `From ${money(lo)}`;
  return null;
}

export function agencyShort(name) {
  return AGENCY_SHORT[name] || name || "";
}

export function fitBand(score) {
  if (score === null || score === undefined) return null;
  if (score >= 80) return { key: "strong", word: "strong", label: "Strong fit" };
  if (score >= 60) return { key: "good", word: "good", label: "Good fit" };
  if (score >= 40) return { key: "partial", word: "partial", label: "Partial fit" };
  return { key: "weak", word: "weak", label: "Weak fit" };
}

// Applicant categories that name higher education, copied from the record.
export function higherEdRows(rows) {
  return (rows || []).filter((r) => /institutions of higher education/i.test(r)
    && !/other than institutions of higher education/i.test(r));
}

export function shortId(id) {
  return String(id || "").replace(/^https?:\/\/openalex\.org\//, "").replace(/^grants_gov:/, "");
}

// Split text into plain strings and citation ids. Ids are [BRACKETED] tokens or bare
// OpenAlex work ids (W followed by digits).
const ID = "[A-Za-z0-9][A-Za-z0-9.:\\-]*"; // private ids carry a colon (private:proposal)
const TOKEN = new RegExp(`\\[(${ID}(?:,\\s*${ID})*)\\]|\\b(W\\d{5,})\\b`, "g");

export function segments(text, known = null) {
  const out = [];
  let last = 0;
  const isCite = (id) => !known || known.has(id) || /^W\d+$/.test(id) || /^[A-Z]{2,4}(-[A-Z]{2,3})?-\d{2}-\d{3}$/.test(id);
  for (const m of String(text || "").matchAll(TOKEN)) {
    const ids = m[1] ? m[1].split(/,\s*/) : [m[2]];
    if (m[1] && !ids.every(isCite)) continue;
    if (m.index > last) out.push(text.slice(last, m.index));
    for (const id of ids) out.push({ cite: id });
    last = m.index + m[0].length;
  }
  if (last < String(text || "").length) out.push(text.slice(last));
  return tidy(out);
}

function tidy(parts) {
  // Drop the space left before a removed bracket and before final punctuation.
  const out = [];
  for (const p of parts) {
    if (typeof p === "string" && out.length && typeof out[out.length - 1] === "string") {
      out[out.length - 1] += p;
    } else out.push(p);
  }
  return out.map((p, i) => (typeof p === "string" && out[i + 1] && typeof out[i + 1] !== "string"
    ? p.replace(/\s+$/, " ") : p)).filter((p) => p !== "");
}

// The fit explanation is "<opportunity sentence> Cited work: W1 clause; W2 clause."
// (built by code in perch/skills/fit.py). Returns {opportunity, findings} or, when the
// text does not have that shape, {raw} so nothing the model wrote is lost.
export function parseExplanation(text, citedIds = []) {
  const known = new Set(citedIds);
  const s = String(text || "").trim();
  const at = s.indexOf("Cited work: ");
  if (!s) return null;
  if (at < 0) return { raw: segments(s, known) };
  const opp = s.slice(0, at).trim();
  const body = s.slice(at + "Cited work: ".length).trim().replace(/\.$/, "");
  const findings = [];
  for (const part of body.split(/;\s+/)) {
    const m = part.match(/^(W\d+|private:[a-z]+)\s+([\s\S]*?)(?:\s*\[(?:W\d+|private:[a-z]+)\])?$/);
    if (!m || !m[2].trim()) return { raw: segments(s, known) };
    findings.push({ paper: m[1], text: m[2].trim().replace(/\.$/, "") });
  }
  return { opportunity: segments(opp, known), findings };
}

// Today's date where the user is, as YYYY-MM-DD (not the UTC date).
export function localToday(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function elapsed(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}

export function plural(n, one, many = one + "s") {
  return `${n} ${n === 1 ? one : many}`;
}

export function safeUrl(u) {
  return /^https?:\/\//i.test(String(u || "")) ? u : null;
}

export function doiUrl(doi) {
  if (!doi) return null;
  return safeUrl(doi) || `https://doi.org/${doi}`;
}
