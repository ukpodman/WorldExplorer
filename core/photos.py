"""Country photographs (Wikimedia Commons), with verified attribution and mobile-friendly loading.

data/photos.json holds one record per country, keyed by the country id:

    "PER": {"file": "File:Machu_Picchu,_Peru.jpg", "caption": "Machu Picchu, Cusco Region",
            "author": "...", "license": "CC BY-SA 4.0", "license_url": "https://...",
            "page": "https://commons.wikimedia.org/wiki/File:...", "url": "https://upload.wikimedia.org/...",
            "width": 4000, "height": 2667, "verified": "2026-10-22"}

Only "file" and "caption" are chosen by hand. Everything about the photograph itself (photographer, licence,
size, original URL) comes from Wikimedia Commons: either stored by tools/photo_credits.py ("verified"), or looked
up once on the server when a record is not verified yet (cached; never in the browser). A photograph is shown only
when its photographer and an allowed reuse licence are known; otherwise the page shows the locator-map fallback.
Extending coverage to all 195 countries means adding records; the interface does not change.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

PHOTOS_FILE = Path(__file__).resolve().parent.parent / "data" / "photos.json"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "WorldExplorer/1.0 (educational geography app; https://github.com/ukpodman/WorldExplorer)"
# Wikimedia's standard thumbnail widths (other widths may be refused or slow). A thumbnail is only requested when
# the original is wider; otherwise the original itself is used.
THUMB_WIDTHS = (330, 500, 960, 1280)
DEFAULT_WIDTH = 960
# Reuse licences we accept (Commons LicenseShortName values). Anything else, or no licence, is not shown.
ALLOWED_LICENCE = re.compile(r"^(cc0( 1\.0)?|public domain|pd[- ].*|cc[- ]by( |-)(sa( |-))?\d\.\d.*)$", re.I)
REMOTE_TIMEOUT = 4.0
OK_TTL, FAIL_TTL = 7 * 86400, 600     # seconds: a successful lookup is kept a week, a failed one 10 minutes

_cache: dict[str, tuple[float, dict | None]] = {}
_lock = threading.Lock()


def load_records() -> dict[str, dict]:
    return json.loads(PHOTOS_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Commons file names and URLs (deterministic)

def file_name(record_or_title) -> str:
    """'File:Machu Picchu, Peru.jpg' → 'Machu_Picchu,_Peru.jpg' (the name Commons stores, underscores for spaces)."""
    title = record_or_title.get("file", "") if isinstance(record_or_title, dict) else str(record_or_title)
    if not title and isinstance(record_or_title, dict) and record_or_title.get("page"):
        title = urllib.parse.unquote(record_or_title["page"].rsplit("/wiki/", 1)[-1])
    name = title.split(":", 1)[1] if title.lower().startswith("file:") else title
    name = name.strip().replace(" ", "_")
    return name[:1].upper() + name[1:]


def _hash_path(name: str) -> str:
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    return f"{digest[0]}/{digest[:2]}"


def original_url(name: str) -> str:
    return f"https://upload.wikimedia.org/wikipedia/commons/{_hash_path(name)}/{urllib.parse.quote(name)}"


def page_url(name: str) -> str:
    return f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(name)}"


def thumb_url(name: str, width: int) -> str:
    quoted = urllib.parse.quote(name)
    suffix = ".png" if name.lower().endswith((".svg", ".tif", ".tiff")) else ""
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{_hash_path(name)}/{quoted}/{width}px-{quoted}{suffix}"


def sources(record: dict) -> tuple[str, str]:
    """(src, srcset) for an <img>: Commons thumbnails narrower than the original, the original only if needed."""
    name = file_name(record)
    width = record.get("width") or 0
    if not name or not width:
        return record.get("url", ""), ""
    widths = [w for w in THUMB_WIDTHS if w < width]
    if not widths:
        return record.get("url") or original_url(name), ""
    src = thumb_url(name, DEFAULT_WIDTH if DEFAULT_WIDTH in widths else widths[-1])
    return src, ", ".join(f"{thumb_url(name, w)} {w}w" for w in widths)


# ---------------------------------------------------------------- validation

def licence_ok(licence: str | None) -> bool:
    return bool(licence) and bool(ALLOWED_LICENCE.match(licence.strip()))


def complete(record: dict | None) -> bool:
    """Shown only with a photographer, an allowed licence, its licence page (if not public domain) and a source page."""
    if not record or not record.get("author") or not record.get("page") or not (record.get("url") or record.get("file")):
        return False
    lic = record.get("license", "")
    if not licence_ok(lic):
        return False
    return bool(record.get("license_url")) or lic.lower().startswith(("public domain", "pd", "cc0"))


def _plain(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


# ---------------------------------------------------------------- Commons lookups (server side, cached)

def _fetch(titles: list[str]) -> dict[str, dict]:
    """imageinfo for up to 50 file titles → {file name: metadata}. Raises on network errors."""
    query = urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": "2", "prop": "imageinfo",
        "iiprop": "url|size|extmetadata", "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Credit",
        "titles": "|".join("File:" + t for t in titles)})
    req = urllib.request.Request(f"{COMMONS_API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = {}
    for page in data.get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        meta = info.get("extmetadata", {})
        name = file_name(page.get("title", ""))
        out[name] = {"author": _plain(meta.get("Artist", {}).get("value")) or _plain(meta.get("Credit", {}).get("value")),
                     "license": _plain(meta.get("LicenseShortName", {}).get("value")),
                     "license_url": _plain(meta.get("LicenseUrl", {}).get("value")),
                     "url": info.get("url", ""), "page": info.get("descriptionurl", "") or page_url(name),
                     "width": info.get("width"), "height": info.get("height")}
    return out


def remote_metadata(name: str, fetch=None) -> dict | None:
    """Commons metadata for one file, cached (a week on success, ten minutes after a failure)."""
    now = time.time()
    with _lock:
        hit = _cache.get(name)
        if hit and hit[0] > now:
            return hit[1]
    try:
        meta = (fetch or _fetch)([name]).get(name)
        ttl = OK_TTL if meta else FAIL_TTL
    except Exception:
        meta, ttl = None, FAIL_TTL
    with _lock:
        _cache[name] = (now + ttl, meta)
    return meta


def resolve(record: dict | None, fetch=None) -> dict | None:
    """The record ready to show, or None. Verified records are used as stored (no network). Unverified ones take
    photographer, licence, size and URLs from Commons; stored hand-written fields (caption) are kept."""
    if not record:
        return None
    name = file_name(record)
    if record.get("verified") and complete(record) and record.get("width"):
        return record
    remote = remote_metadata(name, fetch) if name else None
    if remote:
        merged = {**record, **{k: v for k, v in remote.items() if v}}
        if record.get("author") and record.get("license"):      # credits already recorded by hand stay authoritative
            merged.update({k: record[k] for k in ("author", "license", "license_url") if record.get(k)})
        if complete(merged):
            return merged
    return record if complete(record) else None
