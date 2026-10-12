"""Interactive continent map for the Explore page (Streamlit custom component v2, no external downloads).

The outlines come from assets/world_map.json (Natural Earth, public domain; built by tools/build_world_map.py) and are
coloured by the app's own continent classification. Clicking a continent only selects it: it never starts a quiz or
touches a round. The continent buttons under the map are the keyboard and screen-reader route to the same choice.

The same script also looks after the continent details panel when it is shown as a bottom sheet (phones and
portrait tablets, up to 900 px): it moves focus into the sheet, keeps Tab inside it, closes it with Escape or a tap
on the dimmed background, and returns focus to the control that opened it.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

MAP_FILE = Path(__file__).resolve().parent.parent / "assets" / "world_map.json"
SHEET_MAX_WIDTH = 900  # px; keep in sync with assets/styles.css (continent sheet media query)
# Continent fills: light tints of the app palette (teal, ivory, gold), all with dark text contrast for labels.
FILLS = {"North America": "#BFDCD6", "South America": "#E7CF9C", "Europe": "#9ED6D2", "Africa": "#EBDDB8",
         "Asia": "#7FC4BF", "Oceania": "#F2E4BE"}
SELECTED_FILL = "#E2B55A"


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
.wm text { font-family:"Segoe UI","Inter",system-ui,-apple-system,Arial,sans-serif; font-weight:700; fill:#17283B;
           stroke:#F7F4ED; stroke-linejoin:round; paint-order:stroke; text-anchor:middle; pointer-events:none; }
@media (prefers-reduced-motion:reduce) { .wm .land { transition:none; } }
"""

JS = r"""
const NS = "http://www.w3.org/2000/svg";
function el(name, attrs) { const n = document.createElementNS(NS, name); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; }

function sheetState() { return window.__weSheet || (window.__weSheet = { open: false, ret: null, scroll: null }); }
function narrow(max) { return window.matchMedia("(max-width:" + max + "px)").matches; }
function visible(selector) {
  return Array.from(document.querySelectorAll(selector)).find(n => n.getClientRects().length && n.offsetWidth > 0) || null;
}
function panel() { return document.querySelector(".st-key-continent_panel"); }
function focusables(root) {
  return Array.from(root.querySelectorAll('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"]), input, select, textarea'))
    .filter(n => n.offsetParent !== null || n === document.activeElement);
}

function installGlobalHandlers() {
  if (window.__weSheetHandlers) return;
  window.__weSheetHandlers = true;
  document.addEventListener("keydown", (ev) => {
    const s = sheetState();
    if (!s.open || !narrow(s.max) || !panel()) return;
    if (ev.key === "Escape") { ev.preventDefault(); s.trigger && s.trigger("close", Date.now()); return; }
    if (ev.key === "Tab") {  // keep keyboard focus inside the open sheet
      const items = focusables(panel());
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (!panel().contains(document.activeElement)) { ev.preventDefault(); first.focus(); }
      else if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    }
  }, true);
  document.addEventListener("click", (ev) => {
    const s = sheetState();
    if (s.open && ev.target.closest && ev.target.closest(".continent-scrim")) { s.trigger && s.trigger("close", Date.now()); }
  }, true);
  document.addEventListener("focusin", (ev) => {  // remember the control that opens the details
    const t = ev.target;
    if (t && t.closest && (t.closest("[class*='st-key-continent_btn_']") || t.closest(".st-key-world_map"))) sheetState().opener = t;
  }, true);
}

function syncSheet(data, trigger) {
  const s = sheetState();
  s.trigger = trigger; s.max = data.sheet_max;
  const wasOpen = s.open;
  s.open = !!data.selected;
  if (s.open && !wasOpen) {
    s.ret = s.opener || document.activeElement;
    s.last = data.selected;
    if (narrow(s.max)) {
      let tries = 0;
      (function focusSheet() {
        const title = document.querySelector(".st-key-continent_panel .continent-title");
        if (title) { title.focus({ preventScroll: true }); return; }
        if (tries++ < 30) setTimeout(focusSheet, 50);
      })();
    }
  } else if (!s.open && wasOpen) {
    const back = s.ret && document.contains(s.ret) && s.ret.getClientRects().length ? s.ret
      : visible(".st-key-continent_btn_" + (s.last || "").replace(/ /g, "_") + " button");
    if (back) setTimeout(() => { try { back.focus({ preventScroll: true }); } catch (e) {} }, 60);
    s.ret = null;
  }
  if (data.scroll && data.scroll !== s.scroll) {
    s.scroll = data.scroll;
    let tries = 0;
    (function scrollToBrowser() {
      const target = visible(".st-key-explore_scope");
      if (target && !panel()) {
        target.scrollIntoView({ block: "start" });
        setTimeout(() => target.scrollIntoView({ block: "start" }), 400);  // again once late layout has settled
        return;
      }
      if (tries++ < 30) setTimeout(scrollToBrowser, 50);
    })();
  }
}

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const cache = window.__weMapPaths || (window.__weMapPaths = {});
  if (data.map) Object.assign(cache, data.map);
  installGlobalHandlers();
  syncSheet(data, setTriggerValue);
  if (!cache.continents) { setTriggerValue("need_map", Date.now()); return; }

  let root = parentElement.querySelector(".wm");
  if (!root) {
    root = document.createElement("div");
    root.className = "wm";
    const vb = cache.viewbox;
    const svg = el("svg", { viewBox: vb.join(" "), preserveAspectRatio: "xMidYMid meet", role: "img" });
    svg.appendChild(el("rect", { x: 0, y: 0, width: vb[2], height: vb[3], fill: "#1B4A63" }));
    let grid = "";
    for (let y = 64; y < vb[3]; y += 64) grid += "M0 " + y + "H" + vb[2];
    for (let x = 125; x < vb[2]; x += 125) grid += "M" + x + " 0V" + vb[3];
    svg.appendChild(el("path", { d: grid, class: "grid" }));
    if (cache.antarctica) svg.appendChild(el("path", { d: cache.antarctica, class: "ant" }));
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
    root.appendChild(svg);
    parentElement.appendChild(root);
    const fit = () => {
      const w = svg.getBoundingClientRect().width || 1;
      const scale = w / vb[2];
      const px = w < 380 ? 9.5 : w < 560 ? 11 : w < 760 ? 12.5 : 13.5;
      svg.querySelectorAll("text").forEach(t => { t.setAttribute("font-size", (px / scale).toFixed(1)); t.setAttribute("stroke-width", (3 / scale).toFixed(1)); });
    };
    if (window.ResizeObserver) new ResizeObserver(fit).observe(svg);
    fit();
  }
  // Fresh handlers each render, so a click always reports through the current component instance.
  root.querySelectorAll(".land").forEach(p => { p.onclick = () => setTriggerValue("select", p.getAttribute("data-continent")); });
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
  root.querySelectorAll("text").forEach(t => { t.textContent = (data.labels && data.labels[t.getAttribute("data-continent")]) || ""; });
}
"""



def _need_map() -> None:
    st.session_state.world_map_sent = False


def render(selected: str | None, labels: dict[str, str], aria_label: str, scroll_token: int, on_select, on_close) -> None:
    """Draw the map. The outlines (about 100 kB) are sent once per browser session; the page caches them."""
    ss = st.session_state
    payload = {"selected": selected, "labels": labels, "aria_label": aria_label, "fills": FILLS,
               "selected_fill": SELECTED_FILL, "sheet_max": SHEET_MAX_WIDTH, "scroll": scroll_token}
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
