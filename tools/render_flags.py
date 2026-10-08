"""Rasterise the upstream SVG flags to small WebP images bundled in one file, assets/flags.json
({id: base64 WebP}). One file keeps the project small enough for a single GitHub browser upload.

Usage:  python tools/render_flags.py <path to mledoze/countries clone> [ids...]
Requires Playwright with Chromium and Pillow. Run once when the dataset is updated;
the app itself only reads the bundled WebP files.
"""
import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WIDTH = 320


def main(clone: Path, ids: list[str]) -> None:
    bundle_path = ROOT / "assets" / "flags.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8")) if bundle_path.exists() else {}
    upstream_ids = json.loads((ROOT / "data" / "reference" / "curation.json").read_text(encoding="utf-8"))["id_mapping"]
    reverse = {v: k for k, v in upstream_ids.items()}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=1)
        for app_id in ids:
            svg = clone / "data" / f"{reverse.get(app_id, app_id).lower()}.svg"
            if not svg.exists():
                print("missing", app_id)
                continue
            page.set_content(f'<html><body style="margin:0;background:transparent">'
                             f'<img id="f" src="data:image/svg+xml;base64,'
                             f'{base64.b64encode(svg.read_bytes()).decode()}" style="width:{WIDTH}px;display:block"></body></html>')
            page.wait_for_function("document.getElementById('f').complete")
            png = page.locator("#f").screenshot(omit_background=True)
            buffer = io.BytesIO()
            Image.open(io.BytesIO(png)).save(buffer, "WEBP", quality=88, method=6)
            bundle[app_id] = base64.b64encode(buffer.getvalue()).decode()
        browser.close()
    bundle_path.write_text(json.dumps(dict(sorted(bundle.items())), separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    clone_path = Path(sys.argv[1])
    wanted = sys.argv[2:] or [c["id"] for c in json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))]
    main(clone_path, wanted)
