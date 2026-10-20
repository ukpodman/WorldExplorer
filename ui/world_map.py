"""Interactive continent map for the Explore page (Streamlit custom component v2, no external downloads).

The outlines come from assets/world_map.json (Natural Earth, public domain; built by tools/build_world_map.py) and are
coloured by the app's own continent classification. Clicking a continent only selects it: it never starts a quiz or
touches a round. The continent buttons under the map are the keyboard and screen-reader route to the same choice.

While a continent is open the map stays in the panel, zoomed to that continent (Project Atlas), and the same script
looks after focus: it moves focus to the continent heading (bringing it into view on phones), returns to the world
view with Escape, and puts focus back on the continent's button when the world view returns.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

MAP_FILE = Path(__file__).resolve().parent.parent / "assets" / "world_map.json"
STACK_MAX_WIDTH = 900  # px; at or below this width the Explore columns stack (keep in sync with assets/styles.css)
# Continent fills: six clearly different, cheerful colours. Every map label (dark text, white halo) keeps at least
# 6:1 contrast, and neighbours differ in lightness as well as hue, so they stay apart with colour blindness too.
FILLS = {"North America": "#A2DC86", "South America": "#EC8838", "Europe": "#B98AEB", "Africa": "#F2C94E",
         "Asia": "#F7E9A0", "Oceania": "#F4919F"}
SELECTED_FILL = ""          # a chosen continent keeps its colour and gets a white outline (the others dim)
ANTARCTICA_FILL = "#E6EEF3"
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


# Ocean names drawn on the map (longitude, latitude of the label), projected like the outlines.
OCEANS = {"Arctic Ocean": [(-2, 84.6)], "Atlantic Ocean": [(-36, 22)], "Pacific Ocean": [(-140, 2), (168, 14)],
          "Indian Ocean": [(74, -30)], "Southern Ocean": [(30, -57)]}


def _project(lon: float, lat: float) -> tuple[float, float]:
    """Natural Earth I, scaled exactly like tools/build_world_map.py (1000 units wide, top at 84° N)."""
    import math

    def raw(lo, la):
        lam, phi = math.radians(lo), math.radians(la)
        p2 = phi * phi
        p4 = p2 * p2
        return (lam * (0.870700 - 0.131979 * p2 - 0.013791 * p4 + 0.003971 * p4 * p4 * p2 - 0.001529 * p4 * p4 * p4),
                phi * (1.007226 + 0.015085 * p2 - 0.044475 * p4 * p2 + 0.028874 * p4 * p4 - 0.005916 * p4 * p4 * p2))
    scale = 500 / raw(180, 0)[0]
    top = raw(0, 84)[1]
    x, y = raw(lon, lat)
    return round(x * scale + 500, 1), round((top - y) * scale, 1)


OCEAN_POINTS = {name: [_project(*ll) for ll in points] for name, points in OCEANS.items()}

# Russia belongs to Europe in the country data, but east of the Ural mountains it is drawn in Asia's colour (and a tap
# there opens Asia), so Europe appears at its real size. Approximate line: Urals, Ural river, Caspian, Caucasus.
URALS = [(66, 84), (66, 76), (64.5, 69.5), (60, 68), (59.2, 64), (59, 60), (58.6, 56), (59.5, 52.5), (58, 51), (54, 50.2),
         (52, 48), (51.5, 46.8), (49.5, 45.5), (47.5, 42.5), (47, 30)]


def _split_paths() -> dict:
    pts = [_project(*ll) for ll in URALS]
    line = " L".join(f"{x},{y}" for x, y in pts)
    last_y, first_x = pts[-1][1], pts[0][0]
    return {"west": f"M{line} L-20,{last_y} L-20,-40 L{first_x},-40 Z",
            # east of the line, plus Russia's far east, which Natural Earth I wraps round to the left edge
            "east": f"M{line} L1020,{last_y} L1020,-40 L{first_x},-40 Z M-20,-40 L260,-40 L260,140 L-20,140 Z"}


SPLIT = _split_paths()

# Project Atlas: choosing a continent zooms the map to it (longitude west, east, latitude south, north).
FOCUS_BOUNDS = {"Africa": (-20, 55, -36, 38), "Europe": (-25, 45, 34, 71), "Asia": (25, 150, -11, 60),
                "North America": (-170, -50, 6, 78), "South America": (-85, -33, -56, 13), "Oceania": (110, 180, -48, 2)}


def _focus_box(bounds: tuple[float, float, float, float]) -> list[float]:
    """The bounds as an x, y, width, height box in map units (sampled, because the projection bends the edges)."""
    west, east, south, north = bounds
    pts = [_project(west + (east - west) * i / 8, south + (north - south) * j / 8) for i in range(9) for j in range(9)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs), min(ys), round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)]


FOCUS_BOXES = {name: _focus_box(b) for name, b in FOCUS_BOUNDS.items()}
LABEL_AT = {"Asia": list(_project(98, 50))}
ZOOM_LABELS = {"in": "Zoom in", "out": "Zoom out", "all": "Show the whole world"}   # Asia's label sits in the middle of its (now larger) area


@st.cache_resource(show_spinner=False)
def map_data() -> dict:
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))


CSS = """
:host { display:block; }
.wm { position:relative; width:100%; line-height:0; }
.wm > svg { display:block; width:100%; height:auto; border-radius:16px; background:#0B3D61; overflow:hidden; }
/* the map fills the box but never pushes the continent pills off a desktop screen (it stays whole: no cropping) */
@media (min-width:701px) { .wm > svg { max-height:max(360px, calc(100vh - 330px)); } }
/* a continent is open (map beside the list on wide screens): a taller frame, the zoomed continent fills it */
@media (min-width:901px) { .wm.tall > svg { height:clamp(320px, calc(100vh - 300px), 620px); max-height:none; } }
.wm .land { stroke:#13202E; stroke-opacity:.45; stroke-width:.7; stroke-linejoin:round; vector-effect:non-scaling-stroke; cursor:pointer;
            transition:fill-opacity .15s ease, fill .15s ease; -webkit-tap-highlight-color:transparent; }
.wm .land:hover { fill-opacity:1 !important; filter:brightness(1.07); }
.wm.has-sel .land:not(.sel) { fill-opacity:.45; }
.wm .land.sel { stroke:#FFFFFF; stroke-opacity:1; stroke-width:2.2; }
.wm .ant { stroke:#9FB6C4; stroke-width:.6; vector-effect:non-scaling-stroke; pointer-events:none; }
.wm .coast { fill:none; stroke:#7FD3E8; stroke-opacity:.22; stroke-width:4.5; stroke-linejoin:round; vector-effect:non-scaling-stroke; pointer-events:none; }
.wm .oceans text { font-style:italic; font-weight:500; fill:#CDE9F5; fill-opacity:.82; stroke:none; letter-spacing:.02em; }
.wm .land { animation:we-rise .5s ease-out both; }
@keyframes we-rise { from { fill-opacity:0; } }
.wm text { font-family:"Segoe UI","Inter",system-ui,-apple-system,Arial,sans-serif; font-weight:700; fill:#13202E;
           stroke:#FFFFFF; stroke-opacity:.92; stroke-linejoin:round; paint-order:stroke; text-anchor:middle; pointer-events:none; }
.wm > svg { touch-action:pan-y; }
.wm.zoomed > svg { cursor:grab; }
.wm-zoom { position:absolute; right:10px; bottom:10px; display:flex; flex-direction:column; gap:6px; line-height:normal; }
.wm-zoom button { width:40px; height:40px; border-radius:12px; border:1px solid rgba(255,255,255,.35); background:rgba(11,32,52,.82);
  color:#FFFFFF; font:600 22px/1 "Segoe UI",system-ui,-apple-system,sans-serif; display:flex; align-items:center; justify-content:center;
  cursor:pointer; padding:0; box-shadow:0 2px 8px rgba(0,0,0,.25); -webkit-tap-highlight-color:transparent; }
.wm-zoom button:hover:not(:disabled) { background:rgba(20,60,92,.95); }
.wm-zoom button:focus-visible { outline:3px solid #F2C94E; outline-offset:2px; }
.wm-zoom button:disabled { opacity:.38; cursor:default; }
@media (max-width:700px) and (orientation:portrait) {   /* small, so the map stays the picture */
  .wm-zoom { left:6px !important; bottom:6px !important; gap:4px !important; }
  .wm .wm-zoom button { width:32px; height:32px; font-size:18px; border-radius:10px; }
}
@media (max-width:700px) { .wm-zoom { right:auto; left:8px; bottom:8px; flex-direction:row; gap:6px; }
  .wm-zoom button { width:36px; height:36px; font-size:20px; } }

@media (prefers-reduced-motion:reduce) { .wm .land { transition:none; animation:none; } }
"""

JS = r"""
const NS = "http://www.w3.org/2000/svg";
function el(name, attrs) { const n = document.createElementNS(NS, name); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; }

function setLabel(t, text, narrow, size) {
  // Two-word names go on two lines on small maps ("North / America"), like a printed atlas.
  t.setAttribute("data-text", text);
  while (t.firstChild) t.removeChild(t.firstChild);
  const words = text.split(" ");
  if (!narrow || words.length !== 2) { t.textContent = text; return; }
  const x = t.getAttribute("x");
  words.forEach((word, i) => {
    const s = document.createElementNS(NS, "tspan");
    s.setAttribute("x", x); s.setAttribute("dy", i ? (size * 1.05).toFixed(1) : (-size * 0.45).toFixed(1));
    s.textContent = word; t.appendChild(s);
  });
}

function installZoom(root, svg, base) {
  // Smooth zoom and pan without distortion: the viewBox keeps the map's own proportions. Pinch (touch), Ctrl/⌘ +
  // wheel or a trackpad pinch (desktop), the + / − buttons; drag to pan once zoomed. At the whole-world view one
  // finger still scrolls the page. A drag never counts as a tap on a continent.
  const MAX = 8;
  let view = base.slice(), anim = null, dragged = false;
  const pointers = new Map();
  const aspect = () => base[2] / base[3];   // the view always has the map's own shape
  const fullW = () => Math.max(base[2], base[3] * aspect());   // the smallest view that shows the whole world
  const zoom = () => fullW() / view[2];
  const clampView = (v) => {
    const a = aspect(), w = Math.min(fullW(), Math.max(base[2] / MAX, v[2])), h = w / a;
    const axis = (pos, size, b0, bs) => size >= bs ? b0 - (size - bs) / 2 : Math.min(b0 + bs - size, Math.max(b0, pos));
    return [axis(v[0], w, base[0], base[2]), axis(v[1], h, base[1], base[3]), w, h];
  };
  const whole = () => clampView([0, 0, fullW(), 0]);
  const apply = (v) => {
    view = clampView(v);
    svg.setAttribute("viewBox", view.map(n => n.toFixed(2)).join(" "));
    const zoomed = zoom() > 1.001;
    svg.style.touchAction = zoomed ? "none" : "pan-y";
    root.classList.toggle("zoomed", zoomed);
    // the relief texture is for the overview; zoomed in (or in the viewer) it is switched off, which keeps drawing fast
    // and avoids tiling glitches some browsers show for large filtered areas
    const relief = svg.querySelector("g.relief");
    if (relief && !root.__weLite) relief.setAttribute("filter", zoomed ? "none" : "url(#we-relief)");
    root.querySelector(".zout").disabled = !zoomed;
    root.querySelector(".zall").disabled = !zoomed;
    root.querySelector(".zin").disabled = zoom() >= MAX - 0.01;
    if (root.__weFit) root.__weFit();
  };
  const toMap = (cx, cy) => {
    const m = svg.getScreenCTM();
    if (!m) return [view[0] + view[2] / 2, view[1] + view[3] / 2];
    const p = new DOMPoint(cx, cy).matrixTransform(m.inverse());
    return [p.x, p.y];
  };
  const zoomAt = (factor, mx, my, v) => {
    v = v || view;
    const w = Math.min(fullW(), Math.max(base[2] / MAX, v[2] / factor)), k = w / v[2];
    return [mx - (mx - v[0]) * k, my - (my - v[1]) * k, w, w / aspect()];
  };
  const animate = (target) => {
    const from = view.slice(), to = clampView(target), t0 = performance.now(), ms = 260;
    if (anim) cancelAnimationFrame(anim);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { apply(to); return; }
    const step = (now) => {
      const p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 3);
      apply(from.map((f, i) => f + (to[i] - f) * e));
      anim = p < 1 ? requestAnimationFrame(step) : null;
    };
    anim = requestAnimationFrame(step);
  };
  const centre = () => [view[0] + view[2] / 2, view[1] + view[3] / 2];
  root.querySelector(".zin").onclick = () => { const [x, y] = centre(); animate(zoomAt(2, x, y)); };
  root.querySelector(".zout").onclick = () => { const [x, y] = centre(); animate(zoomAt(0.5, x, y)); };
  root.querySelector(".zall").onclick = () => animate(whole());
  root.__weWhole = () => animate(whole());
  root.__weGo = (box) => {   // zoom to a continent so it fills the frame (a little padded), map proportions kept
    const a = aspect(), r = svg.getBoundingClientRect(), ca = r.height > 0 ? r.width / r.height : a;
    let w;
    if (ca <= a) w = Math.max(box[2], box[3] * ca) * 1.12;          // taller frame: the width decides
    else w = Math.max(box[3], box[2] / ca) * 1.12 * a;              // wider frame: the height decides
    const h = w / a;
    animate([box[0] + box[2] / 2 - w / 2, box[1] + box[3] / 2 - h / 2, w, h]);
  };
  svg.addEventListener("wheel", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey)) return;          // plain scrolling keeps scrolling the page
    ev.preventDefault();
    const [x, y] = toMap(ev.clientX, ev.clientY);
    apply(zoomAt(Math.exp(-ev.deltaY * 0.01), x, y));
  }, { passive: false });
  let last = null;
  svg.addEventListener("pointerdown", (ev) => {
    pointers.set(ev.pointerId, [ev.clientX, ev.clientY]);
    dragged = false;
    last = null;
  });
  const move = (ev) => {
    if (!pointers.has(ev.pointerId)) return;
    const prev = pointers.get(ev.pointerId);
    pointers.set(ev.pointerId, [ev.clientX, ev.clientY]);
    if (pointers.size >= 2) {
      const [a, b] = Array.from(pointers.values());
      const dist = Math.hypot(a[0] - b[0], a[1] - b[1]), mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      if (last) {
        const [mx, my] = toMap(mid[0], mid[1]);
        apply(zoomAt(dist / last.dist, mx, my));
        const [nx, ny] = toMap(last.mid[0], last.mid[1]), [cx, cy] = toMap(mid[0], mid[1]);
        apply([view[0] - (cx - nx), view[1] - (cy - ny), view[2], view[3]]);
      }
      last = { dist, mid };
      dragged = true;
      ev.preventDefault();
      return;
    }
    if (zoom() <= 1.001) return;                       // whole world: let the page scroll
    const m = svg.getScreenCTM(), dx = ev.clientX - prev[0], dy = ev.clientY - prev[1];
    if (!m) return;
    if (Math.abs(dx) + Math.abs(dy) > 0) {
      if (!dragged) {
        const start = prev;
        dragged = Math.hypot(ev.clientX - start[0], ev.clientY - start[1]) > 3 || dragged;
      }
      apply([view[0] - dx / m.a, view[1] - dy / m.d, view[2], view[3]]);
      if (Math.abs(dx) + Math.abs(dy) > 2) dragged = true;
    }
  };
  const up = (ev) => { pointers.delete(ev.pointerId); if (pointers.size < 2) last = null; };
  // The page-wide pointer listeners are added once per page; they always drive the map that is shown now. (Adding them
  // for every new map kept each earlier map alive and added three more listeners per return to Explore.)
  window.__weZoomNow = { move, up };
  if (!window.__weZoomListeners) {
    window.__weZoomListeners = true;
    window.addEventListener("pointermove", (ev) => window.__weZoomNow && window.__weZoomNow.move(ev), { passive: false });
    window.addEventListener("pointerup", (ev) => window.__weZoomNow && window.__weZoomNow.up(ev));
    window.addEventListener("pointercancel", (ev) => window.__weZoomNow && window.__weZoomNow.up(ev));
  }
  svg.addEventListener("click", (ev) => { if (dragged) { ev.stopPropagation(); ev.preventDefault(); dragged = false; } }, true);
  apply(base);
}

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

function syncDetail(data) {
  // Phones: the chosen country replaces the list inside the box. Focus its name (bring it into view if needed);
  // when going back to the list, focus that country's arrow again.
  const s = viewState();
  const before = s.detail;
  s.detail = data.detail || null;
  if (before === s.detail) return;
  let tries = 0;
  (function settle() {
    const target = s.detail ? visible(".st-key-stage_detail .detail-name") : visible(".st-key-discover_" + before + " button");
    if (target) {
      target.focus({ preventScroll: true });
      const panel = visible(".st-key-stage_panel") || visible("[class*='st-key-explore_stage']");
      const top = panel ? panel.getBoundingClientRect().top : 0;
      if (panel && (top < 0 || top > window.innerHeight - 120)) panel.scrollIntoView({ block: "start" });
      return;
    }
    if (tries++ < 40) setTimeout(settle, 50);
  })();
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
  syncDetail(data);
  if (!cache.continents) { setTriggerValue("need_map", Date.now()); return; }

  let root = parentElement.querySelector(".wm");
  if (!root) {
    root = document.createElement("div");
    root.className = "wm";
    const W = cache.viewbox[2], H = cache.viewbox[3];
    const vb = [0, -16, W, H + 16 + 4];    // just enough room for the Arctic Ocean name; Antarctica's name sits on the ice
    const svg = el("svg", { viewBox: vb.join(" "), preserveAspectRatio: "xMidYMid meet", role: "img" });
    // Phones and touch screens get the light version: no texture filters (sea-floor shading, land relief, coastal
    // glow), which are the costly part to draw on mobile GPUs. Colours, labels and taps are identical.
    const lite = window.matchMedia("(max-width:700px), (pointer:coarse)").matches;
    root.__weLite = lite;
    const defs = el("defs", {});
    defs.innerHTML =
      '<linearGradient id="we-ocean" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0E4A72"/><stop offset=".55" stop-color="#0B3D61"/><stop offset="1" stop-color="#082F4D"/></linearGradient>' +
      // sea-floor texture: soft lighter patches like depth shading
      '<filter id="we-depth" x="0" y="0" width="100%" height="100%" filterUnits="objectBoundingBox">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.008 0.012" numOctaves="3" seed="11"/>' +
      '<feColorMatrix values="0 0 0 0 0.55  0 0 0 0 0.82  0 0 0 0 1  1.1 0 0 0 -0.5"/></filter>' +
      // land relief: a gentle hill-shade texture over the flat colour
      '<filter id="we-relief" x="-2%" y="-2%" width="104%" height="104%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="3" seed="4" result="n"/>' +
      '<feDiffuseLighting in="n" surfaceScale="2.2" lighting-color="#FFFFFF" result="l"><feDistantLight azimuth="225" elevation="52"/></feDiffuseLighting>' +
      '<feComponentTransfer in="l" result="s"><feFuncR type="linear" slope=".32" intercept=".72"/><feFuncG type="linear" slope=".32" intercept=".72"/><feFuncB type="linear" slope=".32" intercept=".72"/></feComponentTransfer>' +
      '<feBlend in="SourceGraphic" in2="s" mode="multiply" result="b"/><feComposite in="b" in2="SourceGraphic" operator="in"/></filter>' +
      '<filter id="we-glow" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="2.2"/></filter>' +
      '<clipPath id="we-west"><path d="' + data.split.west + '"/></clipPath><clipPath id="we-east"><path d="' + data.split.east + '"/></clipPath>';
    svg.appendChild(defs);
    // the sea reaches past the frame, so a wide box (desktop) shows ocean at the sides, never empty bands
    svg.appendChild(el("rect", { x: -700, y: vb[1] - 900, width: vb[2] + 1400, height: vb[3] + 1800, fill: "url(#we-ocean)" }));
    if (!lite) svg.appendChild(el("rect", { x: -700, y: vb[1] - 900, width: vb[2] + 1400, height: vb[3] + 1800, filter: "url(#we-depth)", opacity: ".38", "pointer-events": "none" }));
    const coast = el("path", { class: "coast", d: Object.values(cache.continents).join("") + (cache.antarctica || "") });
    if (!lite) coast.setAttribute("filter", "url(#we-glow)");
    svg.appendChild(coast);
    const relief = el("g", lite ? { class: "relief" } : { class: "relief", filter: "url(#we-relief)" });
    if (cache.antarctica) relief.appendChild(el("path", { d: cache.antarctica, class: "ant", fill: data.antarctica_fill }));
    for (const name of Object.keys(cache.continents)) {
      const pieces = name === "Europe" ? [["Europe", "url(#we-west)"], ["Asia", "url(#we-east)"]] : [[name, null]];
      for (const [owner, clip] of pieces) {
        const p = el("path", { d: cache.continents[name], class: "land", "data-continent": owner });
        if (clip) p.setAttribute("clip-path", clip);
        p.appendChild(el("title", {}));
        p.addEventListener("click", () => setTriggerValue("select", owner));
        relief.appendChild(p);
      }
    }
    svg.appendChild(relief);
    svg.appendChild(el("g", { class: "oceans", "aria-hidden": "true" }));
    const labels = el("g", { class: "labels", "aria-hidden": "true" });
    for (const name of Object.keys(cache.labels)) {
      const [x, y] = (data.label_at || {})[name] || cache.labels[name];
      labels.appendChild(el("text", { x: x, y: y, "data-continent": name }));
    }
    const antLabel = el("text", { class: "ant-label", x: W / 2, y: H - 4 });
    labels.appendChild(antLabel);
    svg.appendChild(labels);
    root.appendChild(svg);
    // Zoom controls: always one tap back to the complete world.
    const controls = document.createElement("div");
    controls.className = "wm-zoom";
    controls.innerHTML = '<button type="button" class="zin" aria-label="' + (data.zoom_labels || {}).in + '" title="' + (data.zoom_labels || {}).in + '">+</button>' +
      '<button type="button" class="zout" aria-label="' + (data.zoom_labels || {}).out + '" title="' + (data.zoom_labels || {}).out + '">\u2212</button>' +
      '<button type="button" class="zall" aria-label="' + (data.zoom_labels || {}).all + '" title="' + (data.zoom_labels || {}).all + '">' +
      '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8.5"/><ellipse cx="12" cy="12" rx="3.6" ry="8.5"/><path d="M3.5 12h17"/></svg></button>';
    root.appendChild(controls);
    parentElement.appendChild(root);
    installZoom(root, svg, vb);
    const fit = () => {
      const w = svg.getBoundingClientRect().width || 1;
      const ctm = svg.getScreenCTM();
      const scale = (ctm && ctm.a) || (w / vb[2]);   // screen pixels per map unit (follows the zoom)
      const px = w < 380 ? 12 : w < 560 ? 13 : w < 760 ? 14.5 : 16;
      root.__weNarrow = w < 560;
      svg.querySelectorAll(".labels text").forEach(t => {
        t.setAttribute("font-size", (px / scale).toFixed(1)); t.setAttribute("stroke-width", (3.4 / scale).toFixed(1));
        setLabel(t, t.getAttribute("data-text") || "", root.__weNarrow, px / scale);
      });
      const og = svg.querySelector(".oceans");
      og.style.display = w < 300 ? "none" : "";
      og.querySelectorAll("text").forEach(t => {
        t.setAttribute("font-size", ((w < 420 ? 9.5 : w < 760 ? 11.5 : 13.5) / scale).toFixed(1));
        t.setAttribute("x", t.getAttribute("data-x"));
        try {   // keep every ocean name inside the frame
          const b = t.getBBox(), pad = 6 / scale;
          if (b.x < pad) t.setAttribute("x", (+t.getAttribute("data-x") + pad - b.x).toFixed(1));
          else if (b.x + b.width > vb[2] - pad) t.setAttribute("x", (+t.getAttribute("data-x") - (b.x + b.width - vb[2] + pad)).toFixed(1));
        } catch (e) {}
      });
    };
    root.__weFit = fit;
    if (window.ResizeObserver) {   // one observer for the map on the page (an earlier map's observer is let go)
      if (window.__weResize) window.__weResize.disconnect();
      window.__weResize = new ResizeObserver(fit);
      window.__weResize.observe(svg);
    }
    fit();
  }
  // Fresh handlers each render, so a click always reports through the current component instance.
  root.querySelectorAll(".land").forEach(p => { p.onclick = () => setTriggerValue("select", p.getAttribute("data-continent")); });
  root.style.display = data.hidden ? "none" : "";
  root.classList.toggle("tall", !!data.tall);
  const focusKey = data.focus_key || "";
  if (root.__weFocusKey !== focusKey) {   // zoom to the chosen continent; back to the whole world when it closes
    const first = root.__weFocusKey === undefined;
    root.__weFocusKey = focusKey;
    // phones keep the whole world (a zoomed map would catch one-finger scrolling on a small screen)
    const phone = window.matchMedia("(max-width:700px)").matches;
    if (focusKey && data.focus_box && !phone && root.__weGo) requestAnimationFrame(() => root.__weGo(data.focus_box));
    else if (!first && root.__weWhole) root.__weWhole();
  }
  const svg = root.querySelector("svg");
  svg.setAttribute("aria-label", data.aria_label || "");
  root.classList.toggle("has-sel", !!data.selected);
  root.querySelectorAll(".land").forEach(p => {
    const name = p.getAttribute("data-continent");
    const sel = name === data.selected;
    p.classList.toggle("sel", sel);
    p.setAttribute("fill", sel && data.selected_fill ? data.selected_fill : (data.fills[name] || "#CCCCCC"));
    p.querySelector("title").textContent = (data.labels && data.labels[name]) || name;
  });
  const og = root.querySelector(".oceans");
  if (og && og.getAttribute("data-sig") !== JSON.stringify(data.oceans || [])) {  // ocean names (translated)
    og.setAttribute("data-sig", JSON.stringify(data.oceans || []));
    og.innerHTML = "";
    for (const [name, x, y] of (data.oceans || [])) { const t = el("text", { x: x, y: y, "data-x": x }); t.textContent = name; og.appendChild(t); }
  }
  root.querySelectorAll(".labels text").forEach(t => {
    const text = t.classList.contains("ant-label") ? (data.antarctica_label || "") : ((data.labels && data.labels[t.getAttribute("data-continent")]) || "");
    if (t.getAttribute("data-text") !== text) setLabel(t, text, !!root.__weNarrow, +t.getAttribute("font-size") || 14);
  });
  if (root.__weFit) root.__weFit();
}
"""



def _need_map() -> None:
    st.session_state.world_map_sent = False


def render(selected: str | None, labels: dict[str, str], aria_label: str, *, on_select, on_close, hidden: bool = False,
           view: str | None = None, detail: str | None = None, oceans: dict[str, str] | None = None,
           antarctica_label: str = "Antarctica", zoom_labels: dict[str, str] | None = None, focus: str | None = None) -> None:
    """Draw the map. The outlines (about 100 kB) are sent once per browser session; the page caches them."""
    ss = st.session_state
    payload = {"selected": selected, "labels": labels, "aria_label": aria_label, "fills": FILLS,
               "selected_fill": SELECTED_FILL, "stack_max": STACK_MAX_WIDTH, "hidden": hidden,
               "split": SPLIT, "label_at": LABEL_AT, "antarctica_fill": ANTARCTICA_FILL,
               "antarctica_label": antarctica_label, "zoom_labels": zoom_labels or ZOOM_LABELS,
               "view_open": bool(view), "view_key": view, "detail": detail, "tall": bool(view),
               "focus_key": focus if focus in FOCUS_BOXES else None, "focus_box": FOCUS_BOXES.get(focus),
               "oceans": [[(oceans or {}).get(name, name), x, y] for name, pts in OCEAN_POINTS.items() for x, y in pts]}
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
