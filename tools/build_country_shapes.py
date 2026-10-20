"""Build assets/country_shapes.json: simplified country outlines for the locator map on Learn → World Geography.

Usage:  python tools/build_country_shapes.py <folder with ne_10m_admin_0_countries.geojson and
        ne_50m_admin_0_boundary_lines_land.geojson>

Source: Natural Earth 1:10m Admin 0 – Countries (public domain), github.com/nvkelso/natural-earth-vector. Outlines are
simplified (Douglas–Peucker, tolerance scaled to each country's size) and projected with Natural Earth I exactly like
the Explore map (1000 units wide, top at 84° N), so the app never downloads map data. Each entry: path "p", bounding
outline "q" (lighter, for drawing it as a neighbour), box "b" [x0, y0, x1, y1] of the main piece (the locator's view), "a" of all pieces (for drawing neighbours), and a
label point "c" [x, y] in map units. Keys are the app's country ids (ISO 3166 alpha-3).
"""
import json
import sys
from pathlib import Path

sys.setrecursionlimit(100000)
sys.path.insert(0, str(Path(__file__).resolve().parent))
_argv, sys.argv = sys.argv, sys.argv[:1]   # import the helpers without running the figure builder
from build_school_figures import P, _dp, _rings  # noqa: E402  (same projection and simplification)
sys.argv = _argv
ALIASES = {"KOS": "XKX"}   # Natural Earth code → the app's id

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "country_shapes.json"


def main(folder: Path) -> None:
    ids = {c["id"] for c in json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))}
    features = json.loads((folder / "ne_10m_admin_0_countries.geojson").read_text())["features"]
    out = {}
    for f in features:
        pr = f["properties"]
        code = next((ALIASES.get(pr.get(k), pr.get(k)) for k in ("ISO_A3", "ISO_A3_EH", "ADM0_A3", "SOV_A3")
                     if ALIASES.get(pr.get(k), pr.get(k)) in ids), None)
        if not code or code in out:
            continue
        rings = [[tuple(p[:2]) for p in r] for r in _rings(f["geometry"])]
        main = max(rings, key=len)   # size the tolerances on the main piece (overseas islands would inflate it)
        lons = [x for x, _ in main]
        lats = [y for _, y in main]
        extent = max(max(lons) - min(lons), max(lats) - min(lats))
        tol = 0.03 if extent < 25 else min(0.6, extent / 100)   # one tolerance for most countries, so shared borders line up
        parts, boxes = [], []
        for ring in rings:
            if len(ring) < 4:
                continue
            half = len(ring) // 2
            pts = _dp(ring[:half + 1], tol)[:-1] + _dp(ring[half:], tol)
            xy, rx, ry = [], [], []
            for lon, lat in pts:
                x, y = P(lon, lat)
                q = f"{x:.1f},{y:.1f}"
                if not xy or xy[-1] != q:
                    xy.append(q)
                    rx.append(x)
                    ry.append(y)
            if len(xy) >= 3:
                parts.append("M" + "L".join(xy) + "Z")
                area = abs(sum(rx[i] * ry[i - 1] - rx[i - 1] * ry[i] for i in range(len(rx)))) / 2
                boxes.append((area, min(rx), min(ry), max(rx), max(ry)))
        lx, ly = pr.get("LABEL_X"), pr.get("LABEL_Y")
        if not boxes:   # too small to draw at this scale: a marker at its label point only
            if lx is None:
                continue
            cx, cy = P(lx, ly)
            boxes = [(0, cx, cy, cx, cy)]
        # The view box: the largest piece plus the pieces close to it (so France's overseas regions or Alaska's
        # far islands do not turn the locator into a world map).
        _, x0, y0, x1, y1 = max(boxes)
        w, h = x1 - x0, y1 - y0
        for _, a0, b0, a1, b1 in boxes:
            cx, cy = (a0 + a1) / 2, (b0 + b1) / 2
            if x0 - 1.5 * w <= cx <= x1 + 1.5 * w and y0 - 1.5 * h <= cy <= y1 + 1.5 * h:
                x0, y0, x1, y1 = min(x0, a0), min(y0, b0), max(x1, a1), max(y1, b1)
        xs, ys = [x0, x1], [y0, y1]
        full = [round(min(b[1] for b in boxes), 1), round(min(b[2] for b in boxes), 1),
                round(max(b[3] for b in boxes), 1), round(max(b[4] for b in boxes), 1)]
        c = P(lx, ly) if lx is not None and ly is not None else ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        coarse = []   # a lighter outline for drawing this country as a neighbour (larger tolerance, no tiny islands)
        ctol = max(0.08, min(1.2, extent / 30))
        for ring in rings:
            if len(ring) < 4:
                continue
            lo = [x for x, _ in ring]
            la = [y for _, y in ring]
            if max(max(lo) - min(lo), max(la) - min(la)) < ctol * 3:
                continue
            half = len(ring) // 2
            pts = _dp(ring[:half + 1], ctol)[:-1] + _dp(ring[half:], ctol)
            xy = []
            for lon, lat in pts:
                q = "%.1f,%.1f" % P(lon, lat)
                if not xy or xy[-1] != q:
                    xy.append(q)
            if len(xy) >= 3:
                coarse.append("M" + "L".join(xy) + "Z")
        out[code] = {"p": "".join(parts), "q": "".join(coarse), "b": [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)],
                     "c": [round(c[0], 1), round(c[1], 1)], "a": full}
    borders = []   # land borders drawn once (shared lines), from Natural Earth 1:50m boundary lines
    lines_file = folder / "ne_50m_admin_0_boundary_lines_land.geojson"
    if lines_file.exists():
        for f in json.loads(lines_file.read_text())["features"]:
            for line in _rings(f["geometry"]):
                pts = _dp([tuple(p[:2]) for p in line], 0.04)
                xy = []
                for lon, lat in pts:
                    q = "%.1f,%.1f" % P(lon, lat)
                    if not xy or xy[-1] != q:
                        xy.append(q)
                if len(xy) >= 2:
                    xs_ = [float(v.split(",")[0]) for v in xy]
                    ys_ = [float(v.split(",")[1]) for v in xy]
                    borders.append({"d": "M" + "L".join(xy), "b": [min(xs_), min(ys_), max(xs_), max(ys_)]})
    data = {"source": "Natural Earth 1:10m Admin 0 – Countries (public domain), simplified; projection Natural Earth I",
            "source_url": "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/",
            "countries": dict(sorted(out.items())), "borders": borders}
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"{len(out)} of {len(ids)} places, {OUT.stat().st_size:,} bytes; missing: {sorted(ids - set(out))}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
