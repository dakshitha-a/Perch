// Scout, the owl. One inline SVG; its pose is set by data-state and animated in CSS.
// States follow real status (docs/design/UI.md §3): idle, look, work, done, worry, droop.
// hop() is a one-off reaction when something lands.

const SVG = `
<svg viewBox="0 0 80 80" aria-hidden="true" focusable="false">
  <g class="owl-all">
    <g class="owl-wing owl-wing-l"><path d="M20 42 C13 51 16 62 25 67 C22 57 23 48 24 42 Z"/></g>
    <g class="owl-wing owl-wing-r"><path d="M60 42 C67 51 64 62 55 67 C58 57 57 48 56 42 Z"/></g>
    <path class="owl-body" d="M19 42 C19 25 25 16 29 10 L33 19 C37 17.5 43 17.5 47 19 L51 10
      C55 16 61 25 61 42 C61 60 52 70 40 70 C28 70 19 60 19 42 Z"/>
    <ellipse class="owl-belly" cx="40" cy="54" rx="12.5" ry="13"/>
    <path class="owl-chev" d="M34 50 l3 2.4 l3 -2.4 l3 2.4 l3 -2.4 M35.5 56 l3 2.4 l3 -2.4 l3 2.4
      M37 62 l3 2.2 l3 -2.2"/>
    <g class="owl-head">
      <circle class="owl-face" cx="31" cy="35" r="10.5"/>
      <circle class="owl-face" cx="49" cy="35" r="10.5"/>
      <g class="owl-eyes">
        <circle class="owl-white" cx="31" cy="35" r="7.4"/>
        <circle class="owl-white" cx="49" cy="35" r="7.4"/>
        <g class="owl-pupils">
          <circle class="owl-iris" cx="31" cy="35" r="5"/>
          <circle class="owl-iris" cx="49" cy="35" r="5"/>
          <circle class="owl-pupil" cx="31" cy="35" r="2.6"/>
          <circle class="owl-pupil" cx="49" cy="35" r="2.6"/>
          <circle class="owl-glint" cx="32.6" cy="33.3" r="1.1"/>
          <circle class="owl-glint" cx="50.6" cy="33.3" r="1.1"/>
        </g>
        <ellipse class="owl-lid owl-lid-l" cx="31" cy="35" rx="7.8" ry="7.8"/>
        <ellipse class="owl-lid owl-lid-r" cx="49" cy="35" rx="7.8" ry="7.8"/>
      </g>
      <path class="owl-happy" d="M24.5 36 Q31 29.5 37.5 36 M42.5 36 Q49 29.5 55.5 36"/>
      <path class="owl-brow" d="M24 25.5 L36 28.5 M56 25.5 L44 28.5"/>
      <path class="owl-beak" d="M37 41 L43 41 L40 47 Z"/>
    </g>
    <path class="owl-feet" d="M33 69 v3.5 M35.5 69 v3.5 M44.5 69 v3.5 M47 69 v3.5"/>
  </g>
</svg>`;

export function owl(state = "idle", extra = "") {
  const el = document.createElement("span");
  el.className = `owl ${extra}`.trim();
  el.dataset.state = state;
  el.innerHTML = SVG; // static markup, no data
  return el;
}

export function setOwl(el, state) {
  if (el && el.dataset.state !== state) el.dataset.state = state;
}

export function hop(el) {
  if (!el) return;
  el.classList.remove("hop");
  void el.offsetWidth; // restart the animation
  el.classList.add("hop");
  setTimeout(() => el.classList.remove("hop"), 700);
}
