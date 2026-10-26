"""Build the Nigerian History / Citizenship diagrams: data/school/nigerian-history/figures/*.svg.

Usage:  python tools/build_history_figures.py

The base map (Nigeria's outline, neighbouring land, Lake Chad) is read from the existing Geography figure
data/school/geography/figures/nigeria_tourism_environment.svg, which tools/build_school_figures.py generated from Natural
Earth 1:10m vectors (public domain), with the same projection. Site positions are approximate (a few kilometres).

The map shows MODERN Nigeria for reference only: it marks where historical sites are today and draws no ancient
political boundaries. The evidence illustrations are original drawings made for World Explorer.

Colours are not stored in the files: shapes carry classes that assets/styles.css colours for light and dark themes.
"""
import math
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "school" / "geography" / "figures" / "nigeria_tourism_environment.svg"
OUT = ROOT / "data" / "school" / "nigerian-history" / "figures"


def raw(lon, lat):
    lam, phi = math.radians(lon), math.radians(lat)
    p2 = phi * phi
    p4 = p2 * p2
    return (lam * (0.870700 - 0.131979 * p2 - 0.013791 * p4 + 0.003971 * p4 * p4 * p2 - 0.001529 * p4 * p4 * p4),
            phi * (1.007226 + 0.015085 * p2 - 0.044475 * p4 * p2 + 0.028874 * p4 * p4 - 0.005916 * p4 * p4 * p2))


SCALE = 500 / raw(180, 0)[0]
TOP = raw(0, 84)[1]


def P(lon, lat):
    x, y = raw(lon, lat)
    return round(x * SCALE + 500, 2), round((TOP - y) * SCALE, 2)


# Historical sites (longitude, latitude), approximate. Label side: 1 = right, -1 = left; dy moves the label.
SITES = [
    ("nok", "Nok", (8.0, 9.5), 1, 0.3),
    ("igbo-ukwu", "Igbo-Ukwu", (7.02, 6.02), 1, 0.3),
    ("ife", "Ile-Ife", (4.56, 7.47), 1, 0.55),
    ("osogbo", "Osun-Osogbo Grove", (4.55, 7.76), 1, -0.15),
    ("benin", "Benin City", (5.62, 6.34), 1, 0.4),
    ("sukur", "Sukur", (13.57, 10.73), -1, 0.3),
]


def base():
    svg = BASE.read_text(encoding="utf-8")
    view = re.search(r'viewBox="([^"]+)"', svg).group(1)
    nigeria = re.search(r'<clipPath id="ngclip"><path d="([^"]+)"', svg).group(1)
    sea = re.search(r'<rect class="sea"[^>]*/>', svg).group(0)
    land = re.search(r'<path class="land" d="[^"]*"/>', svg).group(0)
    lake = re.search(r'<path class="lake" d="[^"]*"/>', svg).group(0)
    labels = "".join(re.findall(r'<text class="lbl-(?:n|sea)"[^>]*>[^<]*</text>', svg))
    return view, sea + land + f'<path class="ng" d="{nigeria}"/>' + lake + f'<path class="ng-line" d="{nigeria}" fill="none"/>' + labels


def site_map(numbered: bool) -> str:
    view, body = base()
    marks = ""
    for i, (key, name, (lon, lat), side, dy) in enumerate(SITES, 1):
        x, y = P(lon, lat)
        marks += f'<circle class="site" cx="{x}" cy="{y}" r="{0.45 if numbered else 0.32}"/>'
        if numbered:
            marks += f'<text class="lbl-num" x="{x}" y="{y + 0.2:.2f}" text-anchor="middle">{i}</text>'
        else:
            anchor = "start" if side > 0 else "end"
            marks += f'<text class="lbl-sm" x="{x + 0.55 * side:.2f}" y="{y + dy:.2f}" text-anchor="{anchor}">{escape(name)}</text>'
    note = '<text class="lbl-xs" x="{:.2f}" y="{:.2f}">Modern Nigeria (for reference) · site positions approximate</text>'.format(*P(2.45, 3.82))
    title = ("Map of modern Nigeria with six historical sites numbered 1 to 6" if numbered else
             "Map of modern Nigeria showing the historical sites Nok, Igbo-Ukwu, Ile-Ife, Osun-Osogbo Sacred Grove, Benin City and Sukur")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="sl-map" viewBox="{view}" role="img" '
            f'aria-label="{escape(title, quote=True)}" preserveAspectRatio="xMidYMid meet">{body}{marks}{note}</svg>')


def evidence_icons() -> str:
    """Four original drawings: an elder telling a story (oral tradition), a broken pot in an excavation trench
    (archaeology), a manuscript page (written source) and a relief plaque on a wall (art). Numbered A–D."""
    def panel(x, label, inner):
        return (f'<g transform="translate({x},0)"><rect class="panel" x="2" y="2" width="56" height="56" rx="6"/>{inner}'
                f'<text class="lbl-sm" x="30" y="72" text-anchor="middle" style="font-size:8px;font-weight:800">{label}</text></g>')
    elder = ('<circle class="house" cx="22" cy="20" r="6"/><path class="house" d="M13 48 Q22 26 31 48 Z"/>'
             '<path class="road" d="M34 18 q6 4 0 8 M39 15 q9 7 0 14 M44 12 q12 10 0 20" fill="none" stroke-linecap="round"/>')
    dig = ('<path class="field" d="M6 30 H54" fill="none"/><rect class="hz-desert" x="10" y="31" width="40" height="22"/>'
           '<path class="house" d="M18 46 a12 8 0 0 1 24 0 Z"/><path class="panel" d="M27 40 l4 6 l-6 0 Z"/>'
           '<path class="road" d="M44 12 L44 30 M40 12 H48" fill="none"/>')
    page = ('<rect class="chart-bg" x="14" y="8" width="32" height="44" rx="2" stroke-width=".8"/>'
            + "".join(f'<path class="road" d="M18 {14 + 5 * i} H{42 - (i % 3) * 4}" fill="none" stroke-width=".9"/>' for i in range(7)))
    plaque = ('<rect class="hz-desert" x="12" y="8" width="36" height="44" rx="2"/>'
              '<circle class="house" cx="30" cy="20" r="4.5"/><path class="house" d="M23 46 L26 27 H34 L37 46 Z"/>'
              '<circle class="panel" cx="15" cy="11" r="1.4"/><circle class="panel" cx="45" cy="11" r="1.4"/>')
    body = (panel(0, "A", elder) + panel(64, "B", dig) + panel(128, "C", page) + panel(192, "D", plaque))
    return ('<svg xmlns="http://www.w3.org/2000/svg" class="sl-chart" viewBox="0 0 252 78" role="img" '
            'aria-label="Four drawings labelled A to D: A, an elder speaking with sound waves; B, a broken pot in an '
            'excavation trench beside a measuring pole; C, a page of handwritten text; D, a cast relief plaque showing a '
            'standing figure" preserveAspectRatio="xMidYMid meet">' + body + "</svg>")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ng_historic_sites.svg").write_text(site_map(False), encoding="utf-8")
    (OUT / "ng_historic_sites_numbered.svg").write_text(site_map(True), encoding="utf-8")
    (OUT / "evidence_types.svg").write_text(evidence_icons(), encoding="utf-8")
    print("\n".join(f"{p.name}: {p.stat().st_size:,} bytes" for p in sorted(OUT.glob("*.svg"))))


if __name__ == "__main__":
    main()
