"""Build the School Learning diagrams: data/school/geography/figures/*.svg.

Usage:  python tools/build_school_figures.py <folder with Natural Earth 10m GeoJSON files>

Source: Natural Earth 1:10m vectors (public domain) from github.com/nvkelso/natural-earth-vector, folder geojson/:
ne_10m_admin_0_countries, ne_10m_admin_1_states_provinces (Nigeria's 36 states and the FCT),
ne_10m_rivers_lake_centerlines and ne_10m_lakes. Outlines are simplified (Douglas–Peucker) and projected with
Natural Earth I, like the Explore map. Places are positioned from their latitude and longitude; zone boundaries are
simplified and labelled as such in each caption. The app never downloads map data: it only shows the generated SVGs.

Colours are not stored in the files: every shape and label carries a class (sea, land, ng, river, …) that
assets/styles.css colours for the light and the dark theme. The app inlines the SVG, so the classes apply.
"""
import json
import math
import sys

sys.setrecursionlimit(100000)
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "school" / "geography" / "figures"


def raw(lon, lat):
    lam, phi = math.radians(lon), math.radians(lat)
    p2 = phi * phi
    p4 = p2 * p2
    return (lam * (0.870700 - 0.131979 * p2 - 0.013791 * p4 + 0.003971 * p4 * p4 * p2 - 0.001529 * p4 * p4 * p4),
            phi * (1.007226 + 0.015085 * p2 - 0.044475 * p4 * p2 + 0.028874 * p4 * p4 - 0.005916 * p4 * p4 * p2))


SCALE = 500 / raw(180, 0)[0]
TOP = raw(0, 84)[1]


def P(lon, lat):
    """Longitude/latitude to map units, exactly like the Explore map (ui/world_map.py)."""
    x, y = raw(lon, lat)
    return round(x * SCALE + 500, 2), round((TOP - y) * SCALE, 2)


def _dp(points, tol):
    """Douglas–Peucker simplification (degrees)."""
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-12
    best, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        x0, y0 = points[i]
        d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [points[0], points[-1]]
    return _dp(points[:idx + 1], tol)[:-1] + _dp(points[idx:], tol)


def _rings(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        return c
    if t == "MultiPolygon":
        return [r for poly in c for r in poly]
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return c
    return []


def _path(geom, tol, close=True, bbox=None):
    parts = []
    for ring in _rings(geom):
        if bbox and not any(bbox[0] <= x <= bbox[1] and bbox[2] <= y <= bbox[3] for x, y in ring):
            continue
        ring = [tuple(p[:2]) for p in ring]
        if close and len(ring) > 3:  # a closed ring starts and ends at the same point: simplify its two halves
            half = len(ring) // 2
            pts = _dp(ring[:half + 1], tol)[:-1] + _dp(ring[half:], tol)
        else:
            pts = _dp(ring, tol)
        if len(pts) < 2 or (close and len(pts) < 4):
            continue
        xy = []
        for x, y in pts:
            q = "%.1f,%.1f" % P(x, y)
            if not xy or xy[-1] != q:
                xy.append(q)
        if len(xy) >= (3 if close else 2):
            parts.append("M" + "L".join(xy) + ("Z" if close else ""))
    return "".join(parts)


NE = Path(sys.argv[1]) if len(sys.argv) > 1 else None


def _load(name):
    return json.loads((NE / f"{name}.geojson").read_text())["features"]


VIEW = (2.3, 15.2, 3.7, 14.3)  # lon min, lon max, lat min, lat max for the Nigeria maps
if NE:
    _countries = _load("ne_10m_admin_0_countries")
    _c = {f["properties"]["ADM0_A3"]: f for f in _countries}
    NIGERIA = _path(_c["NGA"]["geometry"], 0.012)
    WIDE = (VIEW[0] - 3, VIEW[1] + 3, VIEW[2] - 3, VIEW[3] + 3)
    NEIGHBOURS = "".join(_path(f["geometry"], 0.05, bbox=WIDE) for k, f in _c.items() if k != "NGA")
    STATES = "".join(_path(f["geometry"], 0.03) for f in _load("ne_10m_admin_1_states_provinces") if f["properties"].get("adm0_a3") == "NGA")
    _rivers = _load("ne_10m_rivers_lake_centerlines")
    RIVER_PATHS = {}
    for f in _rivers:
        n = f["properties"].get("name")
        if n in ("Niger", "Benue", "Bénoué", "Kaduna", "Sokoto", "Gongola", "Hadejia", "Komadugu Yobe", "Ogun"):
            d = _path(f["geometry"], 0.02, close=False, bbox=WIDE)
            if d:
                RIVER_PATHS.setdefault("Benue" if n == "Bénoué" else n, []).append(d)
    LAKES = "".join(_path(f["geometry"], 0.01, bbox=WIDE) for f in _load("ne_10m_lakes")
                    if f["properties"].get("name") in ("Lake Chad", "Kainji Reservoir"))
    WA_BOX = (-18.5, 22.5, 1.0, 23.5)
    WEST_AFRICA = "".join(_path(f["geometry"], 0.12, bbox=WA_BOX) for f in _countries
                          if f["properties"].get("CONTINENT") == "Africa")
    WA_LAND = WEST_AFRICA

# Places (longitude, latitude). Approximate positions, accurate to a few kilometres at this scale.
CITY = {"Lagos": (3.39, 6.45), "Abuja": (7.49, 9.06), "Kano": (8.52, 12.0), "Ibadan": (3.93, 7.38),
        "Port Harcourt": (7.01, 4.82), "Enugu": (7.5, 6.45), "Maiduguri": (13.16, 11.85), "Sokoto": (5.24, 13.06),
        "Jos": (8.9, 9.9), "Calabar": (8.32, 4.95), "Kaduna": (7.44, 10.52), "Lokoja": (6.74, 7.8),
        "Makurdi": (8.53, 7.73), "Yola": (12.48, 9.2), "Benin City": (5.62, 6.34), "Warri": (5.75, 5.52),
        "Onitsha": (6.78, 6.15), "Ilorin": (4.55, 8.5), "Zaria": (7.7, 11.1), "Aba": (7.37, 5.1),
        "Abeokuta": (3.35, 7.16), "Bauchi": (9.84, 10.31), "Gombe": (11.17, 10.29), "Minna": (6.55, 9.6),
        "Owerri": (7.03, 5.48), "Katsina": (7.6, 12.99), "Akure": (5.2, 7.25)}



def _box():
    x0, y0 = P(VIEW[0], VIEW[3])
    x1, y1 = P(VIEW[1], VIEW[2])
    return x0, y0, x1 - x0, y1 - y0


def _line(pts, cls, extra=""):
    d = "M" + "L".join(f"{x},{y}" for x, y in (P(*p) for p in pts))
    return f'<path class="{cls}" d="{d}" fill="none"{extra}/>'


def _text(lon, lat, s, cls="lbl", anchor="start", dx=0.0, dy=0.0):
    x, y = P(lon, lat)
    return f'<text class="{cls}" x="{x + dx:.2f}" y="{y + dy:.2f}" text-anchor="{anchor}">{escape(s)}</text>'


def _city(name, anchor="start", dx=0.55, dy=0.35, cls="lbl-sm"):
    lon, lat = CITY[name]
    x, y = P(lon, lat)
    return (f'<circle class="city" cx="{x}" cy="{y}" r="0.32"/>'
            f'<text class="{cls}" x="{x + (dx if anchor == "start" else -dx):.2f}" y="{y + dy:.2f}" text-anchor="{anchor}">{escape(name)}</text>')


def _base(defs=""):
    x, y, w, h = _box()
    neighbours = f'<path class="land" d="{NEIGHBOURS}"/>'
    return (x, y, w, h,
            f'<defs><clipPath id="ngclip"><path d="{NIGERIA}"/></clipPath>{defs}</defs>'
            f'<rect class="sea" x="{x}" y="{y}" width="{w}" height="{h}"/>{neighbours}')


def _wrap(name, title, body, box):
    x, y, w, h = box
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" class="sl-map" viewBox="{x:.2f} {y:.2f} {w:.2f} {h:.2f}" '
           f'role="img" aria-label="{escape(title, quote=True)}" preserveAspectRatio="xMidYMid meet">{body}</svg>')
    (OUT / f"{name}.svg").write_text(svg)


def _neighbour_labels():
    return (_text(2.55, 9.6, "BENIN", "lbl-n") + _text(7.6, 14.05, "NIGER", "lbl-n") + _text(14.1, 14.0, "CHAD", "lbl-n")
            + _text(13.15, 7.6, "CAMEROON", "lbl-n") + _text(4.0, 4.15, "Gulf of Guinea", "lbl-sea")
            + _text(14.55, 13.55, "Lake Chad", "lbl-sm", "middle"))


def relief():
    x, y, w, h, base = _base()
    ell = []
    for (lon, lat, rx, ry, label, anchor, dx, dy) in [
        (8.95, 9.65, 0.9, 0.7, "Jos Plateau", "middle", 0, 1.6), (11.3, 6.75, 0.55, 0.45, "Mambilla Plateau", "end", -0.9, 0.0),
        (9.25, 6.4, 0.32, 0.28, "Obudu Plateau", "end", -0.6, 0.6), (7.45, 6.7, 0.45, 0.6, "Udi–Nsukka Plateau", "end", -0.8, 0.0),
        (12.2, 8.3, 0.45, 0.7, "Adamawa / Shebshi highlands", "end", -0.8, -1.4), (5.1, 7.9, 1.2, 0.7, "Western uplands", "middle", 0, 0.0)]:
        cx, cy = P(lon, lat)
        _, cy2 = P(lon, lat - ry)
        sx = (P(lon + rx, lat)[0] - cx)
        sy = abs(cy2 - cy)
        ell.append(f'<ellipse class="high" cx="{cx}" cy="{cy}" rx="{sx:.2f}" ry="{sy:.2f}"/>')
        ell.append(_text(lon, lat, label, "lbl-hi", anchor, dx, dy))
    rivers = "".join(f'<path class="river" d="{d}" fill="none"/>' for v in RIVER_PATHS.values() for d in v)
    pk = P(11.71, 7.03)
    peak = (f'<path class="peak" d="M{pk[0]},{pk[1] - 0.55}L{pk[0] - 0.45},{pk[1] + 0.3}L{pk[0] + 0.45},{pk[1] + 0.3}Z"/>'
            + _text(11.71, 7.03, "Chappal Waddi 2,419 m", "lbl-sm", "start", 0.6, 1.25))
    lakes = _text(4.45, 10.3, "Kainji Lake", "lbl-sm", "end", -0.75, 0.3)
    labels = (_text(8.0, 11.6, "High Plains of Hausaland", "lbl-region", "middle") + _text(13.0, 12.2, "Chad Basin", "lbl-region", "middle")
              + _text(5.1, 12.0, "Sokoto Plains", "lbl-region", "middle") + _text(6.15, 5.2, "Niger Delta", "lbl-region", "middle")
              + _text(4.35, 6.05, "Coastal lowlands", "lbl-region", "start")
              + _text(5.1, 9.05, "R. Niger", "lbl-riv", "middle") + _text(10.4, 8.45, "R. Benue", "lbl-riv", "middle")
              + _text(6.6, 10.0, "R. Kaduna", "lbl-riv", "end", -0.3) + _text(5.6, 13.45, "R. Sokoto", "lbl-riv", "middle"))
    conf = _city("Lokoja", "start", 0.5, -0.35, "lbl-sm")
    body = (base + f'<path class="ng" d="{NIGERIA}"/>' + "".join(ell) + rivers + lakes + peak + labels + conf
            + _city("Abuja", "start", 0.5, 0.35) + _city("Lagos", "start", 0.5, 0.45) + _city("Kano") + _city("Maiduguri", "end")
            + _city("Port Harcourt", "start", 0.5, 0.6) + f'<path class="states" d="{STATES}" fill="none"/><path class="lake" d="{LAKES}"/><path class="ng-line" d="{NIGERIA}" fill="none"/>' + _neighbour_labels())
    _wrap("nigeria_relief", "Map of Nigeria showing the main highlands, plains and the Niger and Benue rivers", body, (x, y, w, h))


def _band_rects(bands):
    x, y, w, h = _box()
    out = []
    for lat_top, lat_bottom, cls, lon_min in bands:
        _, yt = P(0, lat_top)
        _, yb = P(0, lat_bottom)
        xs = P(lon_min, 0)[0] if lon_min is not None else x
        out.append(f'<rect class="{cls}" x="{xs:.2f}" y="{yt:.2f}" width="{x + w - xs:.2f}" height="{yb - yt:.2f}"/>')
    return "".join(out)


def vegetation():
    x, y, w, h, base = _base()
    bands = _band_rects([(20, 5.6, "z1", None), (5.6, 4.0, "z5", None), (7.4, 5.6, "z4", None), (11.0, 7.4, "z3", None),
                         (13.0, 11.0, "z2", None), (20, 12.8, "z1", 10.5)])
    # Sudan savanna above 11N; Sahel savanna in the far north-east only.
    bands = _band_rects([(20, 11.0, "z2", None), (20, 12.8, "z1", 10.5), (11.0, 7.4, "z3", None), (7.4, 5.6, "z4", None), (5.6, 2.0, "z5", None)])
    mont = "".join(f'<circle class="montane" cx="{P(lo, la)[0]}" cy="{P(lo, la)[1]}" r="0.55"/>' for lo, la in [(8.95, 9.65), (11.3, 6.75), (9.25, 6.4)])
    labels = (_text(8.0, 12.0, "Sudan savanna", "lbl-zone", "middle") + _text(12.2, 13.25, "Sahel savanna", "lbl-zone", "middle")
              + _text(7.2, 9.0, "Guinea savanna", "lbl-zone", "middle") + _text(4.6, 6.8, "Rainforest", "lbl-zone", "middle")
              + _text(6.2, 4.85, "Mangrove and", "lbl-zone", "middle") + _text(6.2, 4.4, "freshwater swamp", "lbl-zone", "middle")
              + _text(8.95, 10.45, "Montane (highlands)", "lbl-sm", "middle"))
    body = (base + f'<path class="ng" d="{NIGERIA}"/><g clip-path="url(#ngclip)">{bands}</g>' + mont
            + f'<path class="states" d="{STATES}" fill="none"/><path class="lake" d="{LAKES}"/><path class="ng-line" d="{NIGERIA}" fill="none"/>' + labels + _neighbour_labels())
    _wrap("nigeria_vegetation", "Simplified map of Nigeria's vegetation belts from mangrove swamp in the south to Sahel savanna in the north-east", body, (x, y, w, h))


def population():
    x, y, w, h, base = _base()
    dense = [(4.0, 7.1, 1.3, 0.9, "South-west"), (7.25, 5.75, 1.0, 0.85, "South-east"), (8.1, 12.2, 1.2, 0.85, "Kano–Katsina–Zaria")]
    sparse = [(6.0, 9.6, 1.8, 0.9, "Middle Belt"), (12.6, 12.6, 1.3, 1.0, "Chad Basin")]
    shapes = ""
    for (lon, lat, rx, ry, label), cls in [(d, "dense") for d in dense] + [(s, "sparse") for s in sparse]:
        cx, cy = P(lon, lat)
        sx = P(lon + rx, lat)[0] - cx
        sy = abs(P(lon, lat - ry)[1] - cy)
        shapes += f'<ellipse class="{cls}" cx="{cx}" cy="{cy}" rx="{sx:.2f}" ry="{sy:.2f}"/>' + _text(lon, lat + (0.45 if label.startswith("Kano") else 0), label, "lbl-zone", "middle", 0, 0.3)
    body = (base + f'<path class="ng" d="{NIGERIA}"/><g clip-path="url(#ngclip)">{shapes}</g>'
            + f'<path class="states" d="{STATES}" fill="none"/><path class="lake" d="{LAKES}"/><path class="ng-line" d="{NIGERIA}" fill="none"/>' + _city("Lagos", "start", 0.5, 0.45) + _city("Kano", "end")
            + _city("Abuja") + _city("Onitsha", "end") + _city("Ibadan", "start", 0.5, -0.2) + _neighbour_labels())
    _wrap("nigeria_population", "Simplified map of Nigeria showing densely populated areas in the south-west, south-east and around Kano, and sparsely populated areas in the Middle Belt and Chad Basin", body, (x, y, w, h))


def resources():
    x, y, w, h, base = _base()
    items = [("oil", (6.3, 5.0), "Crude oil and natural gas"), ("coal", (7.5, 6.45), "Coal (Enugu)"),
             ("tin", (8.9, 9.9), "Tin and columbite (Jos)"), ("lime", (3.2, 6.93), "Limestone (Ewekoro)"),
             ("lime", (6.43, 7.92), "Limestone (Obajana)"), ("iron", (6.3, 7.62), "Iron ore (Itakpe)"),
             ("bit", (4.7, 6.65), "Bitumen (Ondo)"), ("gold", (6.2, 12.1), "Gold (Zamfara)"),
             ("lead", (8.1, 6.3), "Lead and zinc (Abakaliki)")]
    sym = ""
    for kind, (lon, lat), label in items:
        px, py = P(lon, lat)
        sym += f'<rect class="res res-{kind}" x="{px - 0.38:.2f}" y="{py - 0.38:.2f}" width="0.76" height="0.76" rx="0.15"/>'
    legend_y = 5.75
    legend = ""
    seen = []
    for kind, _, label in items:
        if kind in seen:
            continue
        seen.append(kind)
    rows = [("oil", "Crude oil, natural gas"), ("coal", "Coal"), ("tin", "Tin, columbite"), ("lime", "Limestone"),
            ("iron", "Iron ore"), ("bit", "Bitumen"), ("gold", "Gold"), ("lead", "Lead, zinc")]
    bx, by = P(10.8, 6.15)
    bx2, by2 = P(15.15, 3.8)
    legend += f'<rect class="legend-bg" x="{bx:.2f}" y="{by:.2f}" width="{bx2 - bx:.2f}" height="{by2 - by:.2f}" rx="0.4"/>'
    for i, (kind, label) in enumerate(rows):
        lon, lat = 11.0 + (i % 2) * 2.2, legend_y - (i // 2) * 0.55
        px, py = P(lon, lat)
        legend += (f'<rect class="res res-{kind}" x="{px:.2f}" y="{py - 0.35:.2f}" width="0.6" height="0.6" rx="0.12"/>'
                   f'<text class="lbl-xs" x="{px + 0.85:.2f}" y="{py + 0.15:.2f}">{escape(label)}</text>')
    zx, zy = P(6.3, 5.0)
    zone = f'<ellipse class="oilzone" cx="{zx}" cy="{zy}" rx="1.9" ry="1.1"/>'
    body = (base + f'<path class="ng" d="{NIGERIA}"/>' + f'<g clip-path="url(#ngclip)">{zone}</g>' + sym
            + f'<path class="states" d="{STATES}" fill="none"/><path class="lake" d="{LAKES}"/><path class="ng-line" d="{NIGERIA}" fill="none"/>' + _text(6.3, 4.25, "Niger Delta oilfields", "lbl-sm", "middle")
            + _city("Enugu", "start", 0.55, 0.9) + _city("Jos", "start", 0.55, 0.35) + legend + _neighbour_labels())
    _wrap("nigeria_resources", "Map of Nigeria showing where major minerals are found: oil and gas in the Niger Delta, coal at Enugu, tin at Jos, limestone, iron ore, bitumen, gold, lead and zinc", body, (x, y, w, h))


def transport():
    x, y, w, h, base = _base()
    old_w = ["Lagos", "Abeokuta", "Ibadan", None, "Ilorin", None, "Minna", "Kaduna", "Zaria", "Kano"]
    west = [(3.39, 6.45), (3.35, 7.16), (3.93, 7.38), (4.56, 7.77), (4.55, 8.5), (4.82, 9.13), (6.55, 9.6), (7.44, 10.52), (7.7, 11.1), (8.52, 12.0)]
    east = [(7.01, 4.82), (7.37, 5.1), (7.5, 6.45), (8.53, 7.73), (8.52, 8.49), (8.29, 9.58), (9.84, 10.31), (11.17, 10.29), (13.16, 11.85)]
    branch = [(8.29, 9.58), (7.44, 10.52)]
    sgr = [[(3.39, 6.45), (3.93, 7.38)], [(7.3, 9.03), (7.44, 10.52)], [(5.75, 5.52), (6.65, 7.56), (6.3, 7.62)]]
    rails = (_line(west, "rail-old") + _line(east, "rail-old") + _line(branch, "rail-old")
             + "".join(_line(s, "rail-sgr") for s in sgr))
    ports = [((3.37, 6.43), "Apapa / Tin Can"), ((3.98, 6.42), "Lekki Deep Sea Port"), ((7.15, 4.77), "Onne"), ((5.75, 5.52), "Warri"), ((8.32, 4.95), "Calabar")]
    air = [(3.33, 6.58), (7.26, 9.0), (8.52, 12.05), (6.95, 5.02)]
    pt = ""
    for (lon, lat), _ in ports:
        px, py = P(lon, lat)
        pt += f'<circle class="port" cx="{px}" cy="{py}" r="0.42"/>'
    for lon, lat in air:
        px, py = P(lon, lat)
        pt += f'<path class="air" d="M{px},{py - 0.5}L{px + 0.45},{py + 0.35}L{px - 0.45},{py + 0.35}Z"/>'
    labels = (_text(2.9, 5.75, "Lagos ports: Apapa, Tin Can, Lekki", "lbl-xs", "start")
              + _text(7.15, 4.77, "Onne", "lbl-xs", "start", 0.5, 0.5) + _text(5.75, 5.52, "Warri", "lbl-xs", "end", -0.55, 0.3)
              + _text(8.32, 4.95, "Calabar", "lbl-xs", "start", 0.5, 0.3))
    bx, by = P(10.75, 6.15)
    bx2, by2 = P(15.15, 3.8)
    legend = f'<rect class="legend-bg" x="{bx:.2f}" y="{by:.2f}" width="{bx2 - bx:.2f}" height="{by2 - by:.2f}" rx="0.4"/>'
    for i, (cls, label) in enumerate([("rail-sgr", "Standard-gauge railway (2016–2021)"), ("rail-old", "Older main railway lines"),
                                      ("port", "Seaport"), ("air", "Major international airport")]):
        lon, lat = 10.9, 5.75 - i * 0.55
        px, py = P(lon, lat)
        if cls.startswith("rail"):
            legend += f'<path class="{cls}" d="M{px},{py}L{px + 1.2},{py}" fill="none"/>'
        elif cls == "port":
            legend += f'<circle class="port" cx="{px + 0.6}" cy="{py}" r="0.38"/>'
        else:
            legend += f'<path class="air" d="M{px + 0.6},{py - 0.45}L{px + 1.0},{py + 0.3}L{px + 0.2},{py + 0.3}Z"/>'
        legend += f'<text class="lbl-xs" x="{px + 1.5:.2f}" y="{py + 0.2:.2f}">{escape(label)}</text>'
    body = (base + f'<path class="ng" d="{NIGERIA}"/>' + "".join(f'<path class="river" d="{d}" fill="none"/>' for r in ("Niger", "Benue") for d in RIVER_PATHS.get(r, []))
            + rails + pt + f'<path class="states" d="{STATES}" fill="none"/><path class="lake" d="{LAKES}"/><path class="ng-line" d="{NIGERIA}" fill="none"/>' + labels
            + _city("Kano", "start", 0.6, -0.4) + _city("Kaduna", "start", 0.5, 0.2) + _city("Abuja", "start", 0.6, 0.8) + _city("Ibadan", "start", 0.5, 0.0)
            + _city("Enugu", "start", 0.5, 0.2) + _city("Maiduguri", "end") + _city("Makurdi", "start", 0.5, 0.2)
            + _text(6.3, 7.62, "Itakpe", "lbl-xs", "end", -0.5, 0.0) + legend + _neighbour_labels())
    _wrap("nigeria_transport", "Map of Nigeria's main railways, seaports and international airports", body, (x, y, w, h))


def tourism():
    x, y, w, h, base = _base()
    sites = [((10.5, 9.75), "Yankari"), ((9.37, 6.37), "Obudu"), ((3.35, 7.16), "Olumo Rock"), ((4.55, 7.76), "Osun-Osogbo Grove"),
             ((13.57, 10.73), "Sukur"), ((4.6, 9.9), "Kainji Lake N.P."), ((4.52, 12.74), "Argungu"), ((5.1, 7.1), "Idanre Hills")]
    s = ""
    for (lon, lat), label in sites:
        px, py = P(lon, lat)
        s += f'<path class="site" d="M{px},{py - 0.5}L{px + 0.15},{py - 0.15}L{px + 0.5},{py - 0.12}L{px + 0.22},{py + 0.1}L{px + 0.32},{py + 0.48}L{px},{py + 0.27}L{px - 0.32},{py + 0.48}L{px - 0.22},{py + 0.1}L{px - 0.5},{py - 0.12}L{px - 0.15},{py - 0.15}Z"/>'
        s += _text(lon, lat, label, "lbl-xs", "start" if lon < 12.5 else "end", 0.6 if lon < 12.5 else -0.6, 0.3)
    _, y12 = P(0, 12.3)
    desert = f'<rect class="hz-desert" x="{x}" y="{y}" width="{w}" height="{y12 - y:.2f}"/>'
    gx, gy = P(7.1, 5.95)
    oilx, oily = P(6.2, 4.95)
    hz = (f'<ellipse class="hz-gully" cx="{gx}" cy="{gy}" rx="1.0" ry="0.85"/>' + f'<ellipse class="hz-oil" cx="{oilx}" cy="{oily}" rx="1.6" ry="0.9"/>')
    flood = "".join(f'<path class="hz-flood" d="{d}" fill="none"/>' for r in ("Niger", "Benue") for d in RIVER_PATHS.get(r, []))
    bx, by = P(10.75, 6.7)
    bx2, by2 = P(15.15, 3.8)
    legend = f'<rect class="legend-bg" x="{bx:.2f}" y="{by:.2f}" width="{bx2 - bx:.2f}" height="{by2 - by:.2f}" rx="0.4"/>'
    for i, (cls, label) in enumerate([("site", "Tourist attraction"), ("hz-desert", "Desertification risk (far north)"),
                                      ("hz-gully", "Severe gully erosion (south-east)"), ("hz-oil", "Oil pollution (Niger Delta)"),
                                      ("hz-flood", "River flooding (Niger–Benue valleys)")]):
        lon, lat = 10.9, 6.3 - i * 0.55
        px, py = P(lon, lat)
        if cls == "hz-flood":
            legend += f'<path class="hz-flood" d="M{px},{py}L{px + 1.2},{py}" fill="none"/>'
        elif cls == "site":
            legend += f'<circle class="site" cx="{px + 0.6}" cy="{py}" r="0.35"/>'
        else:
            legend += f'<rect class="{cls}" x="{px + 0.1}" y="{py - 0.35}" width="1.0" height="0.6"/>'
        legend += f'<text class="lbl-xs" x="{px + 1.5:.2f}" y="{py + 0.2:.2f}">{escape(label)}</text>'
    body = (base + f'<path class="ng" d="{NIGERIA}"/><g clip-path="url(#ngclip)">{desert}{hz}{flood}</g>' + s
            + f'<path class="states" d="{STATES}" fill="none"/><path class="lake" d="{LAKES}"/><path class="ng-line" d="{NIGERIA}" fill="none"/>' + legend + _neighbour_labels())
    _wrap("nigeria_tourism_environment", "Map of Nigeria showing major tourist attractions and areas affected by desertification, gully erosion, oil pollution and river flooding", body, (x, y, w, h))


def itd():
    """West Africa: simplified rainfall belts and the ITD in January and August."""
    X0, Y0 = P(-18, 22.7)
    X1, Y1 = P(22, 1.5)
    w, h = X1 - X0, Y1 - Y0
    neighbours = f'<path class="land" d="{WEST_AFRICA}"/>'
    bands = ""
    for top, bottom, cls in [(30, 13, "r1"), (13, 9, "r2"), (9, 6, "r3"), (6, -5, "r4")]:
        _, yt = P(0, top)
        _, yb = P(0, bottom)
        bands += f'<rect class="{cls}" x="{X0}" y="{yt:.2f}" width="{w:.2f}" height="{yb - yt:.2f}"/>'
    _, ja = P(0, 6)
    _, au = P(0, 20)
    defs = f'<defs><clipPath id="wa"><path d="{WEST_AFRICA}"/></clipPath></defs>'
    body = (defs + f'<rect class="sea" x="{X0}" y="{Y0}" width="{w:.2f}" height="{h:.2f}"/>{neighbours}<g clip-path="url(#wa)">{bands}</g>'
            f'<path class="border" d="{WEST_AFRICA}" fill="none"/><path class="ng-line" d="{NIGERIA}" fill="none"/>'
            f'<line class="itd" x1="{X0}" y1="{au:.2f}" x2="{X1}" y2="{au:.2f}"/><line class="itd" x1="{X0}" y1="{ja:.2f}" x2="{X1}" y2="{ja:.2f}"/>'
            f'<text class="lbl-itd" x="{X1 - 0.8:.2f}" y="{au - 0.8:.2f}" text-anchor="end">ITD in August: about 20°N</text>'
            f'<text class="lbl-itd" x="{X1 - 0.8:.2f}" y="{ja - 0.8:.2f}" text-anchor="end">ITD in January: near the coast</text>'
            + _text(8.7, 9.1, "NIGERIA", "wa-lbl", "middle", 0, 0.8) + _text(-16, 3.2, "Atlantic Ocean", "wa-sea")
            + _text(-2, 21.0, "Sahara", "wa-n"))
    _wrap("west_africa_itd", "Map of West Africa: rainfall decreases northwards in belts; the ITD lies near the coast in January and at about 20 degrees north in August", body, (X0, Y0, w, h))


def rainfall_chart():
    """Mean annual rainfall at selected places (rounded figures from the references in the lesson)."""
    rows = [("Bonny (Niger Delta)", 4200), ("Calabar", 3070), ("Port Harcourt", 2400), ("Central lowlands", 1100),
            ("Sokoto", 650), ("Far north (Yobe, Borno)", 400)]
    W, H, left, bar_h, gap = 100.0, 6.0 + len(rows) * 7.5, 40.0, 5.0, 2.5
    top = 4.0
    body = f'<rect class="chart-bg" x="0" y="0" width="{W}" height="{H}"/>'
    for i, (name, mm) in enumerate(rows):
        yy = top + i * (bar_h + gap)
        bw = (W - left - 17) * mm / 4200
        body += (f'<text class="ch-lbl" x="{left - 1.5}" y="{yy + 3.4}" text-anchor="end">{escape(name)}</text>'
                 f'<rect class="bar bar-{i}" x="{left}" y="{yy}" width="{bw:.2f}" height="{bar_h}" rx="1"/>'
                 f'<text class="ch-val" x="{left + bw + 1.2:.2f}" y="{yy + 3.4}">{mm:,} mm</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" class="sl-chart" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Bar chart: mean annual rainfall falls from about 4,200 mm at Bonny to about 400 mm in the far north-east">{body}</svg>')
    (OUT / "rainfall_bars.svg").write_text(svg)


def settlement_patterns():
    """Three schematic panels: nucleated, dispersed and linear settlement."""
    import random
    rnd = random.Random(7)
    W, H = 120.0, 46.0
    body = f'<rect class="chart-bg" x="0" y="0" width="{W}" height="{H}"/>'
    for i, title in enumerate(["Nucleated", "Dispersed", "Linear"]):
        ox = 2 + i * 39.3
        body += f'<rect class="panel" x="{ox}" y="2" width="37" height="36" rx="2"/>'
        pts = []
        if i == 0:
            body += f'<path class="road" d="M{ox},20 L{ox + 37},20 M{ox + 18.5},2 L{ox + 18.5},38" fill="none"/>'
            while len(pts) < 26:
                a, r = rnd.random() * 6.283, rnd.random() ** 0.6 * 9
                pts.append((ox + 18.5 + r * math.cos(a), 20 + r * math.sin(a)))
        elif i == 1:
            body += f'<path class="field" d="M{ox + 12.3},2 L{ox + 12.3},38 M{ox + 24.6},2 L{ox + 24.6},38 M{ox},14 L{ox + 37},14 M{ox},26 L{ox + 37},26" fill="none"/>'
            for gx in range(3):
                for gy in range(3):
                    pts.append((ox + 4 + gx * 12.3 + rnd.random() * 4, 5 + gy * 12 + rnd.random() * 5))
        else:
            body += f'<path class="road" d="M{ox + 2},34 C{ox + 12},30 {ox + 22},12 {ox + 35},6" fill="none"/>'
            for k in range(16):
                tt = k / 15
                bx = (1 - tt) ** 3 * 2 + 3 * (1 - tt) ** 2 * tt * 12 + 3 * (1 - tt) * tt ** 2 * 22 + tt ** 3 * 35
                by = (1 - tt) ** 3 * 34 + 3 * (1 - tt) ** 2 * tt * 30 + 3 * (1 - tt) * tt ** 2 * 12 + tt ** 3 * 6
                side = 2.2 if k % 2 else -2.2
                pts.append((ox + bx + side * 0.6, by + side))
        for px, py in pts:
            body += f'<rect class="house" x="{px - 0.9:.2f}" y="{py - 0.9:.2f}" width="1.8" height="1.8"/>'
        body += f'<text class="lbl-sm" x="{ox + 18.5}" y="43.5" text-anchor="middle">{title}</text>'
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" class="sl-chart" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Diagram of three settlement patterns: nucleated houses clustered at a crossroads, dispersed houses scattered among farms, and linear houses along a road">{body}</svg>')
    (OUT / "settlement_patterns.svg").write_text(svg)


def main():
    if not NE:
        sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    relief()
    vegetation()
    population()
    resources()
    transport()
    tourism()
    itd()
    rainfall_chart()
    settlement_patterns()
    print("\n".join(f"{p.name}: {p.stat().st_size:,} bytes" for p in sorted(OUT.glob("*.svg"))))


if __name__ == "__main__":
    main()
