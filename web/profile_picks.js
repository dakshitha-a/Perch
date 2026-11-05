// The optional picks (S53): citizenship and state of residence, shown the same way on the
// student start, the researcher start and the account page. Perch compares them only with a
// listing's own written rule. Nothing here is required, and "Not stated" is the default.

import { h } from "./dom.js";

export const CITIZENSHIP_OPTIONS = [
  ["", "Not stated"], ["us_citizen", "U.S. citizen"], ["permanent_resident", "Permanent resident"],
  ["international", "International"], ["prefer_not", "Prefer not to say"],
];

export const STATE_OPTIONS = [["", "Not stated"], ["AL", "Alabama"], ["AK", "Alaska"], ["AZ", "Arizona"], ["AR", "Arkansas"],
  ["CA", "California"], ["CO", "Colorado"], ["CT", "Connecticut"], ["DE", "Delaware"], ["DC", "District of Columbia"],
  ["FL", "Florida"], ["GA", "Georgia"], ["HI", "Hawaii"], ["ID", "Idaho"], ["IL", "Illinois"], ["IN", "Indiana"],
  ["IA", "Iowa"], ["KS", "Kansas"], ["KY", "Kentucky"], ["LA", "Louisiana"], ["ME", "Maine"], ["MD", "Maryland"],
  ["MA", "Massachusetts"], ["MI", "Michigan"], ["MN", "Minnesota"], ["MS", "Mississippi"], ["MO", "Missouri"],
  ["MT", "Montana"], ["NE", "Nebraska"], ["NV", "Nevada"], ["NH", "New Hampshire"], ["NJ", "New Jersey"],
  ["NM", "New Mexico"], ["NY", "New York"], ["NC", "North Carolina"], ["ND", "North Dakota"], ["OH", "Ohio"],
  ["OK", "Oklahoma"], ["OR", "Oregon"], ["PA", "Pennsylvania"], ["RI", "Rhode Island"], ["SC", "South Carolina"],
  ["SD", "South Dakota"], ["TN", "Tennessee"], ["TX", "Texas"], ["UT", "Utah"], ["VT", "Vermont"],
  ["VA", "Virginia"], ["WA", "Washington"], ["WV", "West Virginia"], ["WI", "Wisconsin"], ["WY", "Wyoming"]];

export const PICKS_LEGEND = "Optional: who you are, for listings that ask";
export const PICKS_HINT = "Stored encrypted with your other inputs. Perch only compares them with a listing's own words. Delete them any time under Account and data.";

// `value` is {citizenship, residency_state} (null or a code); it is updated in place and
// `onchange(value)` is called after each pick. `prefix` keeps the ids unique on a screen.
export function profilePicks({ prefix = "picks", value, onchange = () => {}, disabled = false }) {
  const select = (id, label, options, key) => {
    const sel = h("select", { id, "data-key": id, disabled, onchange: (e) => { value[key] = e.target.value || null; onchange(value); } },
      options.map(([v, t]) => h("option", { value: v, text: t, selected: (value[key] || "") === v })));
    return h("div", { class: "pick" }, h("label", { for: id, text: label }), sel);
  };
  return h("fieldset", { class: "profile-picks" },
    h("legend", { text: PICKS_LEGEND }),
    select(`${prefix}-citizenship`, "Citizenship", CITIZENSHIP_OPTIONS, "citizenship"),
    select(`${prefix}-state`, "State of residence", STATE_OPTIONS, "residency_state"),
    h("p", { class: "hint", text: PICKS_HINT }));
}
