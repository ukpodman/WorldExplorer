"""Interactive continent map for the Explore page (Streamlit custom component v2, no external downloads).

The outlines come from assets/world_map.json (Natural Earth, public domain; built by tools/build_world_map.py) and are
coloured by the app's own continent classification. Clicking a continent only selects it: it never starts a quiz or
touches a round. The continent buttons under the map are the keyboard and screen-reader route to the same choice.

While a continent is open the map stays mounted but hidden, and the same script looks after focus: it moves focus to
the continent heading (bringing it into view on phones), returns to the map with Escape, and puts focus back on the
continent's button when the map returns.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

MAP_FILE = Path(__file__).resolve().parent.parent / "assets" / "world_map.json"
STACK_MAX_WIDTH = 900  # px; at or below this width the Explore columns stack (keep in sync with assets/styles.css)
# Continent fills: light tints of the app palette (teal, ivory, gold), all with dark text contrast for labels.
FILLS = {"North America": "#BFDCD6", "South America": "#E7CF9C", "Europe": "#9ED6D2", "Africa": "#EBDDB8",
         "Asia": "#7FC4BF", "Oceania": "#F2E4BE"}
SELECTED_FILL = "#E2B55A"
# Small original emblems, one per continent (24 x 24 units, drawn in ivory and gold on a navy badge). They are
# generic pictures, not maps or trademarks: peaks and a pine, a palm, a castle tower, a baobab, a pagoda, sun and waves.
EMBLEMS = {
    "North America": '<path d="M3 19l6-10 3 5 2-3 5 8z" fill="#F7F4ED"/><path d="M9 9l1.6 2.7-1.6.9-1.6-.9z" fill="#9ED6D2"/>'
                     '<path d="M18 19v-2m0 0l-2.4 0 2.4-4 2.4 4z" stroke="#E2B55A" stroke-width="1.4" fill="#E2B55A" stroke-linejoin="round"/>',
    "South America": '<path d="M12 20c0-5 .3-8 1-10" stroke="#E2B55A" stroke-width="1.6" fill="none" stroke-linecap="round"/>'
                     '<path d="M13 10c-2-3-5-3.5-8-2.5 3 .2 5 1.2 8 2.5zm0 0c1.5-3.2 4.5-4 7.5-3.5-2.8.6-4.8 1.8-7.5 3.5zm0 0c-3-.8-5.5.6-7 3 2.3-1.4 4.5-2 7-3zm0 0c3-1 5.8 0 7.2 2.4-2.4-1.1-4.6-1.6-7.2-2.4z" fill="#F7F4ED"/>'
                     '<path d="M4 20h16" stroke="#9ED6D2" stroke-width="1.4" stroke-linecap="round"/>',
    "Europe": '<path d="M6 20V10h3v2h2v-2h2v2h2v-2h3v10z" fill="#F7F4ED"/><path d="M10.5 20v-3.5a1.5 1.5 0 013 0V20z" fill="#17283B"/>'
              '<path d="M12 10V4m0 0h4l-1.3 1.2L16 6.4h-4" stroke="#E2B55A" stroke-width="1.2" fill="#E2B55A" stroke-linejoin="round"/>',
    "Africa": '<path d="M10.6 20l.6-8h1.6l.6 8z" fill="#E2B55A"/><ellipse cx="12" cy="9" rx="7.5" ry="3.2" fill="#F7F4ED"/>'
              '<path d="M12 12l-3-2.5M12 12l3-2.5" stroke="#E2B55A" stroke-width="1.1" stroke-linecap="round"/><path d="M4 20h16" stroke="#9ED6D2" stroke-width="1.4" stroke-linecap="round"/>',
    "Asia": '<path d="M5 9.5l7-4 7 4h-2.5l1.5 2h-12l1.5-2z" fill="#F7F4ED"/><path d="M7 15l5-2.4 5 2.4h-1.8l1 1.6h-8.4l1-1.6z" fill="#F7F4ED"/>'
            '<path d="M9 11.5v1.4M15 11.5v1.4M10 16.6V20M14 16.6V20M8 20h8" stroke="#E2B55A" stroke-width="1.3" stroke-linecap="round"/>'
            '<path d="M12 5.5V3.5" stroke="#E2B55A" stroke-width="1.3" stroke-linecap="round"/>',
    "Oceania": '<circle cx="15" cy="8.5" r="3.4" fill="#E2B55A"/>'
               '<path d="M3 14.5c2 0 2-1.6 4.5-1.6S9.5 14.5 12 14.5s2-1.6 4.5-1.6 2.5 1.6 4.5 1.6" stroke="#F7F4ED" stroke-width="1.6" fill="none" stroke-linecap="round"/>'
               '<path d="M3 18.5c2 0 2-1.6 4.5-1.6S9.5 18.5 12 18.5s2-1.6 4.5-1.6 2.5 1.6 4.5 1.6" stroke="#9ED6D2" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
}


def globe_svg(size: int = 44) -> str:
    """Badge for "all countries" (same style as the continent emblems)."""
    art = ('<circle cx="12" cy="12" r="7.5" fill="none" stroke="#F7F4ED" stroke-width="1.5"/>'
           '<ellipse cx="12" cy="12" rx="3.2" ry="7.5" fill="none" stroke="#E2B55A" stroke-width="1.3"/>'
           '<path d="M4.5 12h15M6 8h12M6 16h12" stroke="#9ED6D2" stroke-width="1.2"/>')
    return (f'<svg class="continent-emblem" width="{size}" height="{size}" viewBox="-2 -2 28 28" aria-hidden="true" focusable="false">'
            f'<circle cx="12" cy="12" r="13" fill="#17283B" stroke="#E2B55A" stroke-width="1.4"/>{art}</svg>')


def emblem_svg(continent: str, size: int = 44) -> str:
    """The continent's emblem as a small decorative badge (hidden from screen readers)."""
    art = EMBLEMS.get(continent, "")
    return (f'<svg class="continent-emblem" width="{size}" height="{size}" viewBox="-2 -2 28 28" aria-hidden="true" focusable="false">'
            f'<circle cx="12" cy="12" r="13" fill="#17283B" stroke="#E2B55A" stroke-width="1.4"/>{art}</svg>')


@st.cache_resource(show_spinner=False)
def map_data() -> dict:
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))


CSS = """
:host { display:block; }
.wm { position:relative; width:100%; line-height:0; }
.wm svg { display:block; width:100%; height:auto; border-radius:14px; background:#1B4A63; touch-action:manipulation; }
.wm .land { stroke:#1B4A63; stroke-width:.6; stroke-linejoin:round; vector-effect:non-scaling-stroke; cursor:pointer;
            transition:fill-opacity .15s ease, fill .15s ease; -webkit-tap-highlight-color:transparent; }
.wm .land:hover { fill-opacity:1 !important; filter:brightness(1.06); }
.wm.has-sel .land:not(.sel) { fill-opacity:.55; }
.wm .land.sel { stroke-width:1; }
.wm .ant { fill:#2B5670; stroke:#1B4A63; stroke-width:.6; vector-effect:non-scaling-stroke; pointer-events:none; }
.wm .grid { stroke:#FFFFFF; stroke-opacity:.06; fill:none; vector-effect:non-scaling-stroke; pointer-events:none; }
.wm .coast { fill:none; stroke:#8FD3CD; stroke-opacity:.28; stroke-width:5; stroke-linejoin:round; vector-effect:non-scaling-stroke; pointer-events:none; }
.wm .waves { fill:none; stroke:#CFE8E4; stroke-opacity:.16; stroke-linecap:round; vector-effect:non-scaling-stroke; pointer-events:none; }
.wm .compass { pointer-events:none; opacity:.8; }
.wm .emb { cursor:pointer; transform-box:fill-box; transform-origin:center; transition:transform .18s ease; -webkit-tap-highlight-color:transparent; }
.wm .emb:hover { transform:scale(1.12); }
.wm .emb .ring { fill:none; stroke:#E2B55A; stroke-width:1.4; opacity:0; transform-box:fill-box; transform-origin:center; }
.wm .emb.sel .ring { animation:we-ring 1.8s ease-out infinite; }
.wm.has-sel .emb:not(.sel) { opacity:.6; }
.wm .land { animation:we-rise .5s ease-out both; }
@keyframes we-ring { 0% { opacity:.9; transform:scale(1); } 100% { opacity:0; transform:scale(1.6); } }
@keyframes we-rise { from { fill-opacity:0; } }
.wm text { font-family:"Segoe UI","Inter",system-ui,-apple-system,Arial,sans-serif; font-weight:700; fill:#17283B;
           stroke:#F7F4ED; stroke-linejoin:round; paint-order:stroke; text-anchor:middle; pointer-events:none; }
@media (prefers-reduced-motion:reduce) { .wm .land, .wm .emb { transition:none; animation:none; } .wm .emb.sel .ring { animation:none; opacity:.9; } }
"""

JS = r"""
const NS = "http://www.w3.org/2000/svg";
function el(name, attrs) { const n = document.createElementNS(NS, name); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; }

function viewState() { return window.__weView || (window.__weView = { open: false, ret: null }); }
function visible(selector) {
  return Array.from(document.querySelectorAll(selector)).find(n => n.getClientRects().length && n.offsetWidth > 0) || null;
}

function installGlobalHandlers() {
  if (window.__weViewHandlers) return;
  window.__weViewHandlers = true;
  document.addEventListener("keydown", (ev) => {  // Escape returns from a continent to the world map
    const s = viewState(), t = ev.target;
    if (ev.key !== "Escape" || !s.open || !s.trigger) return;
    if (t && t.closest && t.closest("input, textarea, select, [role='combobox'], [role='listbox'], [role='dialog']")) return;
    ev.preventDefault();
    s.trigger("close", Date.now());
  }, true);
  document.addEventListener("focusin", (ev) => {  // remember the control that opened the continent
    const t = ev.target;
    if (t && t.closest && (t.closest("[class*='st-key-continent_btn_']") || t.closest(".st-key-browse_all") || t.closest("[class*='st-key-world_map']"))) viewState().opener = t;
  }, true);
}

function syncView(data, trigger) {
  const s = viewState();
  s.trigger = trigger;
  const wasOpen = s.open, before = s.last;
  s.open = !!data.view_open;
  if (s.open && (!wasOpen || before !== data.view_key)) {
    if (!wasOpen) s.ret = s.opener || document.activeElement;
    s.last = data.view_key;
    let tries = 0;
    (function focusTitle() {  // focus the continent heading; on narrow screens bring it into view
      const title = visible(".st-key-browser_head .continent-title");
      if (title) {
        title.focus({ preventScroll: true });
        const head = title.closest(".st-key-browser_head");
        if (head && head.getBoundingClientRect().top < 0) head.scrollIntoView({ block: "start" });
        return;
      }
      if (tries++ < 40) setTimeout(focusTitle, 50);
    })();
  } else if (!s.open && wasOpen) {
    const last = s.last;
    s.ret = null;
    let tries = 0;
    (function focusBack() {  // back on the map: focus the continent's button again
      const back = visible(last === "World" ? ".st-key-browse_all button" : ".st-key-continent_btn_" + (last || "").replace(/ /g, "_") + " button");
      if (back) {
        back.focus({ preventScroll: true });
        const head = visible(".map-heading");  // the map returns in the same place; bring it into view if needed
        if (head && head.getBoundingClientRect().top < 0) head.scrollIntoView({ block: "start" });
        return;
      }
      if (tries++ < 40) setTimeout(focusBack, 50);
    })();
  }
}

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const cache = window.__weMapPaths || (window.__weMapPaths = {});
  if (data.map) Object.assign(cache, data.map);
  installGlobalHandlers();
  syncView(data, setTriggerValue);
  if (!cache.continents) { setTriggerValue("need_map", Date.now()); return; }

  let root = parentElement.querySelector(".wm");
  if (!root) {
    root = document.createElement("div");
    root.className = "wm";
    const vb = cache.viewbox;
    const svg = el("svg", { viewBox: vb.join(" "), preserveAspectRatio: "xMidYMid meet", role: "img" });
    const defs = el("defs", {});
    const grad = el("radialGradient", { id: "we-ocean", cx: "50%", cy: "42%", r: "70%" });
    grad.appendChild(el("stop", { offset: "0", "stop-color": "#2B6E8A" }));
    grad.appendChild(el("stop", { offset: "1", "stop-color": "#143A52" }));
    defs.appendChild(grad);
    svg.appendChild(defs);
    svg.appendChild(el("rect", { x: 0, y: 0, width: vb[2], height: vb[3], fill: "url(#we-ocean)" }));
    let grid = "";
    for (let y = 64; y < vb[3]; y += 64) grid += "M0 " + y + "H" + vb[2];
    for (let x = 125; x < vb[2]; x += 125) grid += "M" + x + " 0V" + vb[3];
    svg.appendChild(el("path", { d: grid, class: "grid" }));
    // A few soft wave strokes in open ocean (Pacific, Atlantic, Indian Ocean); purely decorative.
    const wave = (x, y) => "M" + x + " " + y + "q8 -6 16 0t16 0";
    svg.appendChild(el("path", { class: "waves", d: [wave(60, 250), wave(90, 268), wave(430, 270), wave(410, 300), wave(650, 330), wave(690, 350), wave(880, 220)].join(""), "stroke-width": 1.4 }));
    // Compass rose in the South Pacific.
    const compass = el("g", { class: "compass", transform: "translate(120 395)", "aria-hidden": "true" });
    compass.appendChild(el("circle", { r: 15, fill: "none", stroke: "#E2B55A", "stroke-opacity": ".55", "stroke-width": 1 }));
    compass.appendChild(el("path", { d: "M0 -20L3.5 -3.5L20 0L3.5 3.5L0 20L-3.5 3.5L-20 0L-3.5 -3.5Z", fill: "#E2B55A", "fill-opacity": ".75" }));
    compass.appendChild(el("path", { d: "M0 -20L3.5 -3.5L0 0Z M20 0L3.5 3.5L0 0Z M0 20L-3.5 3.5L0 0Z M-20 0L-3.5 -3.5L0 0Z", fill: "#F7F4ED", "fill-opacity": ".85" }));
    const north = el("text", { y: -24, class: "compass-n" }); north.textContent = "N"; compass.appendChild(north);
    svg.appendChild(compass);
    if (cache.antarctica) svg.appendChild(el("path", { d: cache.antarctica, class: "ant" }));
    svg.appendChild(el("path", { class: "coast", d: Object.values(cache.continents).join("") }));
    for (const name of Object.keys(cache.continents)) {
      const p = el("path", { d: cache.continents[name], class: "land", "data-continent": name });
      p.appendChild(el("title", {}));
      p.addEventListener("click", () => setTriggerValue("select", name));
      svg.appendChild(p);
    }
    const labels = el("g", { class: "labels", "aria-hidden": "true" });
    for (const name of Object.keys(cache.labels)) {
      const [x, y] = cache.labels[name];
      const t = el("text", { x: x, y: y, "data-continent": name });
      labels.appendChild(t);
    }
    svg.appendChild(labels);
    const emblems = el("g", { class: "emblems" });
    for (const name of Object.keys(cache.labels)) {
      const g = el("g", { class: "emb", "data-continent": name });
      g.innerHTML = '<circle class="ring" cx="12" cy="12" r="13"/><circle cx="12" cy="12" r="13" fill="#17283B" stroke="#E2B55A" stroke-width="1.4"/>' + ((data.emblems || {})[name] || "");
      emblems.appendChild(g);
    }
    svg.appendChild(emblems);
    root.appendChild(svg);
    parentElement.appendChild(root);
    const fit = () => {
      const w = svg.getBoundingClientRect().width || 1;
      const scale = w / vb[2];
      const px = w < 380 ? 9.5 : w < 560 ? 11 : w < 760 ? 12.5 : 13.5;
      svg.querySelectorAll(".labels text").forEach(t => { t.setAttribute("font-size", (px / scale).toFixed(1)); t.setAttribute("stroke-width", (3 / scale).toFixed(1)); });
      // Emblems sit just above their label: 18 px on phones, up to 28 px on large maps; hidden on very small maps.
      const icon = w < 300 ? 0 : w < 420 ? 18 : w < 640 ? 22 : 28;
      svg.querySelectorAll(".emb").forEach(g => {
        const [x, y] = cache.labels[g.getAttribute("data-continent")];
        const s = icon / 28 / scale;
        g.style.display = icon ? "" : "none";
        g.setAttribute("transform", "translate(" + (x - 12 * s).toFixed(1) + " " + (y - (px * 1.05) / scale - 26 * s).toFixed(1) + ") scale(" + s.toFixed(3) + ")");
      });
      const c = svg.querySelector(".compass");
      c.style.display = w < 420 ? "none" : "";
      const n = svg.querySelector(".compass-n");
      n.setAttribute("font-size", 9); n.setAttribute("stroke-width", 0); n.setAttribute("fill", "#E2B55A");
    };
    if (window.ResizeObserver) new ResizeObserver(fit).observe(svg);
    fit();
  }
  // Fresh handlers each render, so a click always reports through the current component instance.
  root.querySelectorAll(".land, .emb").forEach(p => { p.onclick = () => setTriggerValue("select", p.getAttribute("data-continent")); });
  root.querySelectorAll(".emb").forEach(g => g.classList.toggle("sel", g.getAttribute("data-continent") === data.selected));
  root.style.display = data.hidden ? "none" : "";
  const svg = root.querySelector("svg");
  svg.setAttribute("aria-label", data.aria_label || "");
  root.classList.toggle("has-sel", !!data.selected);
  root.querySelectorAll(".land").forEach(p => {
    const name = p.getAttribute("data-continent");
    const sel = name === data.selected;
    p.classList.toggle("sel", sel);
    p.setAttribute("fill", sel ? data.selected_fill : (data.fills[name] || "#CCCCCC"));
    p.querySelector("title").textContent = (data.labels && data.labels[name]) || name;
  });
  root.querySelectorAll(".labels text").forEach(t => { t.textContent = (data.labels && data.labels[t.getAttribute("data-continent")]) || ""; });
}
"""



def _need_map() -> None:
    st.session_state.world_map_sent = False


def render(selected: str | None, labels: dict[str, str], aria_label: str, *, on_select, on_close, hidden: bool = False,
           view: str | None = None) -> None:
    """Draw the map. The outlines (about 100 kB) are sent once per browser session; the page caches them."""
    ss = st.session_state
    payload = {"selected": selected, "labels": labels, "aria_label": aria_label, "fills": FILLS,
               "selected_fill": SELECTED_FILL, "stack_max": STACK_MAX_WIDTH, "hidden": hidden, "emblems": EMBLEMS,
               "view_open": bool(view), "view_key": view}
    if not ss.get("world_map_sent"):
        payload["map"] = map_data()
        ss.world_map_sent = True
    # Registered on every run, as Streamlit documents for inline components (cheap, and it survives runtime restarts).
    component = st.components.v2.component("we_world_map", css=CSS, js=JS)
    component(key="world_map", data=payload, on_select_change=on_select, on_close_change=on_close,
               on_need_map_change=_need_map)


def selected_value() -> str | None:
    """The continent just clicked on the map (inside the select callback)."""
    value = st.session_state.get("world_map") or {}
    return value.get("select") if hasattr(value, "get") else None
