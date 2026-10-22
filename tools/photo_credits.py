"""Fill and check country photo credits in data/photos.json from Wikimedia Commons.

Usage (from the project folder, on a computer with internet access):
    python tools/photo_credits.py            # look up every record that is not verified yet, then save
    python tools/photo_credits.py --refresh  # look up every record again (credits recorded by hand are kept)
    python tools/photo_credits.py --check    # no network: report records that cannot be shown yet

To add a country: add  "ISO3": {"file": "File:<exact Commons file name>", "caption": "<short description>"}
to data/photos.json and run this script. Photographer, licence, size and URLs always come from Commons; a file whose
licence is not an allowed reuse licence (CC0, public domain, CC BY, CC BY-SA) is reported and stays hidden.
Prefer landscape photos (wider than tall), at least 1280 px wide, with no identifiable private people as the subject.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import photos  # noqa: E402


def check(records: dict, countries: set[str]) -> list[str]:
    problems = []
    for cid, rec in sorted(records.items()):
        if cid not in countries:
            problems.append(f"{cid}: unknown country id")
        if not rec.get("file") or not rec.get("caption"):
            problems.append(f"{cid}: needs 'file' and 'caption'")
        if not photos.complete(rec):
            problems.append(f"{cid}: credits not verified yet (run without --check)")
        elif not rec.get("width"):
            problems.append(f"{cid}: size unknown (run without --check for responsive loading)")
        elif rec.get("height") and rec["width"] / rec["height"] < 1.15:
            problems.append(f"{cid}: not a landscape photo ({rec['width']}×{rec['height']}); prefer a wider one")
    return problems


def main(argv: list[str]) -> int:
    records = photos.load_records()
    countries = {c["id"] for c in json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))}
    if "--check" not in argv:
        todo = {cid: rec for cid, rec in records.items() if "--refresh" in argv or not rec.get("verified")}
        names = {photos.file_name(rec): cid for cid, rec in todo.items()}
        found = {}
        batch = list(names)
        for i in range(0, len(batch), 50):
            found.update(photos._fetch(batch[i:i + 50]))
        today = date.today().isoformat()
        for name, cid in names.items():
            rec, meta = records[cid], found.get(name)
            if not meta:
                print(f"{cid}: {name} not found on Commons")
                continue
            kept = {k: rec[k] for k in ("author", "license", "license_url") if rec.get(k)} if rec.get("author") and rec.get("license") else {}
            merged = {**rec, **{k: v for k, v in meta.items() if v}, **kept, "file": "File:" + name}
            if photos.complete(merged):
                merged["verified"] = today
                records[cid] = merged
                print(f"{cid}: ok · {merged['author']} · {merged['license']} · {merged.get('width')}×{merged.get('height')}")
            else:
                print(f"{cid}: NOT shown · licence '{meta.get('license')}' / author '{meta.get('author')}'")
                records[cid] = {**rec, **{k: meta[k] for k in ("url", "page", "width", "height") if meta.get(k)}}
        photos.PHOTOS_FILE.write_text(json.dumps(dict(sorted(records.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    problems = check(records, countries)
    print(f"{len(records)} records · {sum(photos.complete(r) for r in records.values())} with verified credits")
    for p in problems:
        print("  " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
