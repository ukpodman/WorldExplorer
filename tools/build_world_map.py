"""Build assets/world_map.json, the outline map on the Explore page.

Usage:  python tools/build_world_map.py <path to ne_50m_admin_0_countries.geojson>

Source: Natural Earth 1:50m Cultural Vectors, Admin 0 – Countries (public domain), taken from
github.com/nvkelso/natural-earth-vector (geojson/ne_50m_admin_0_countries.geojson). See COVERAGE.md.

Every outline is coloured by the continent the app's own dataset (data/countries.json) gives that place, so the
map always agrees with Explore, Learn, the quiz and the continent badges. Overseas parts that Natural Earth draws
inside France or the Netherlands are assigned to the continent of the matching territory in the dataset.
The projection is Natural Earth I; coordinates are simplified (Douglas–Peucker) for a small, fast file.
The app never downloads map data: it only reads the generated JSON.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIDTH = 1000
TOLERANCE = 0.6  # in map units (the map is 1000 units wide)
# Natural Earth features without an ISO code that the dataset covers under another id or as part of a country.
ALIASES = {"KOS": "XKX", "SOL": "SOM", "CYN": "CYP", "KAS": "IND"}
# Anchors (longitude, latitude) for the continent labels.
LABELS = {"North America": (-101, 47), "South America": (-60, -14), "Europe": (16, 53), "Africa": (19, 6),
          "Asia": (92, 47), "Oceania": (134, -25)}


def project(lon, lat):
    """Natural Earth I projection (Šavrič et al.), in radians-based units."""
    lam, phi = math.radians(lon), math.radians(lat)
    p2 = phi * phi
    p4 = p2 * p2
    x = lam * (0.870700 - 0.131979 * p2 - 0.013791 * p4 + 0.003971 * p4 * p4 * p2 - 0.001529 * p4 * p4 * p4)
    y = phi * (1.007226 + 0.015085 * p2 - 0.044475 * p4 * p2 + 0.028874 * p4 * p4 - 0.005916 * p4 * p4 * p2)
    return x, y


SCALE = WIDTH / 2 / project(180, 0)[0]
TOP = project(0, 84)[1]
HEIGHT = round((TOP - project(0, -90)[1]) * SCALE, 1)


def to_map(lon, lat):
    x, y = project(lon, lat)
    return x * SCALE + WIDTH / 2, (TOP - y) * SCALE


def simplify(points, tol):
    """Douglas–Peucker on an open polyline."""
    if len(points) < 3:
        return points
    (ax, ay), (bx, by) = points[0], points[-1]
    length = math.hypot(bx - ax, by - ay) or 1e-9
    best, index = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
        if d > best:
            best, index = d, i
    if best <= tol:
        return [points[0], points[-1]]
    return simplify(points[:index + 1], tol)[:-1] + simplify(points[index:], tol)


def ring_path(ring):
    pts = [to_map(lon, lat) for lon, lat in ring]
    half = len(pts) // 2
    pts = simplify(pts[:half + 1], TOLERANCE)[:-1] + simplify(pts[half:], TOLERANCE)  # closed rings: split first
    out = []
    for x, y in pts[:-1]:
        p = (round(x, 1), round(y, 1))
        if not out or out[-1] != p:
            out.append(p)
    if len(out) < 3:
        return ""
    return "M" + "L".join(f"{x:g},{y:g}" for x, y in out) + "Z"


def overseas_continent(admin, lon, lat):
    """Continent for overseas parts drawn inside France or the Netherlands (by location)."""
    if admin in ("FRA", "NLD") and lon < -30:
        return "South America" if lat < 10 else "North America"
    if admin == "FRA" and lon > 40 and lat < 0:
        return "Africa"
    return None


def main(source: str) -> None:
    countries = {c["id"]: c for c in json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))}
    features = json.loads(Path(source).read_text(encoding="utf-8"))["features"]
    paths: dict[str, list[str]] = {}
    antarctica: list[str] = []
    unmatched = []
    for feature in features:
        props = feature["properties"]
        code = next((c for c in (props.get("ADM0_A3"), props.get("ISO_A3"), props.get("ISO_A3_EH"))
                     if c in countries), None) or ALIASES.get(props.get("ADM0_A3"))
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        if props.get("ADM0_A3") == "ATA":
            antarctica += [ring_path(ring) for polygon in polygons for ring in polygon]
            continue
        if code not in countries:
            unmatched.append(props.get("ADMIN"))
            continue
        for polygon in polygons:
            lon = sum(p[0] for p in polygon[0]) / len(polygon[0])
            lat = sum(p[1] for p in polygon[0]) / len(polygon[0])
            continent = overseas_continent(code, lon, lat) or countries[code]["continent"]
            paths.setdefault(continent, []).extend(filter(None, (ring_path(ring) for ring in polygon)))
    out = {
        "source": "Natural Earth 1:50m Admin 0 – Countries (public domain), simplified; projection Natural Earth I",
        "source_url": "https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/",
        "viewbox": [0, 0, WIDTH, HEIGHT],
        "continents": {c: "".join(paths[c]) for c in sorted(paths)},
        "antarctica": "".join(filter(None, antarctica)),
        "labels": {c: [round(v, 1) for v in to_map(*ll)] for c, ll in LABELS.items()},
    }
    target = ROOT / "assets" / "world_map.json"
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size:,} bytes); not on the map (not in the dataset): {unmatched}")


if __name__ == "__main__":
    main(sys.argv[1])
