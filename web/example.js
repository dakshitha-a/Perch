// The example brief (S50 Q22): a saved brief played back in the app's replay mode, from a file the
// deploy places at web/example/<side>.json. Nothing is called and nothing is saved.
import { fill, h, icon } from "./dom.js";

const q = new URLSearchParams(location.search);
const side = q.get("side") === "student" ? "student" : "researcher";
const tab = ["routes", "profile", "compare", "scout"].includes(q.get("tab")) ? q.get("tab") : "routes";
try {
  const r = await fetch(`example/${side}.json`, { cache: "no-cache" });
  if (!r.ok) throw new Error(String(r.status));
  const data = await r.json();
  if (!data || !data.brief || !data.brief.brief || !data.brief.brief.id) throw new Error("not a saved brief");
  window.PERCH_REPLAY = data;
  window.PERCH_EXAMPLE = { side };
  if (!location.hash || location.hash === "#/") {
    history.replaceState(null, "", `#/brief/${encodeURIComponent(data.brief.brief.id)}/${tab}`);
  }
  await import("./app.js");
} catch {
  // No file on this server (or not one Perch can play): say so plainly, with the way back.
  document.title = "Example not found — Perch";
  // app.js never loads here, so the header's tools point back to the app.
  document.getElementById("theme").hidden = true;
  document.getElementById("help").setAttribute("href", "./#/help");
  const main = document.getElementById("main");
  fill(main, h("div", { class: "empty example-missing" },
    h("div", {}, h("h1", { class: "page", tabindex: "-1", text: "The example is not on this server." }),
      h("p", { class: "lede", text: "The example brief plays back from a saved file, and this server has none." }),
      h("p", {}, h("a", { class: "btn", href: "./" }, icon("back"), h("span", { text: "Back to Perch" }))))));
  main.querySelector("h1").focus({ preventScroll: true });
}
