"""Fill, extend and check the country photographs in data/photos.json from Wikimedia Commons.

Usage (from the project folder, on a computer with internet access):
    python tools/photo_credits.py               # look up every record that is not verified yet, then save
    python tools/photo_credits.py --refresh     # look up every record again (credits recorded by hand are kept)
    python tools/photo_credits.py --add         # add the countries in tools/photo_candidates.json that have no
                                                #   record yet: the first candidate file that passes is saved
    python tools/photo_credits.py --landscape   # replace a verified photo that is not landscape (France, Italy,
                                                #   USA) only if a candidate passes; the old record is kept inside
    python tools/photo_credits.py --add --min-width 1024   # last resort for a country with no 1280 px photo
    python tools/photo_credits.py --check-urls --only TCD,FRA --url-delay 3   # re-check a few, more slowly
    python tools/photo_credits.py --check-urls  # request each verified photo's 960 px thumbnail and report failures
    python tools/photo_credits.py --check       # no network: coverage summary and records that cannot be shown

Options combine, e.g.  python tools/photo_credits.py --add --landscape --check-urls

A candidate passes when Commons reports a photographer, an allowed reuse licence (CC0, public domain, CC BY,
CC BY-SA) with its licence page, and a size of at least MIN_WIDTH px that is landscape (width / height ≥ 1.15).
Existing verified records are never overwritten by --add. Nothing is invented: a country whose candidates all
fail stays without a record and the app shows its locator-map fallback. The coverage summary counts only the
195 states and only records that are verified (credits and size stored in the file).

To add a country by hand: add  "ISO3": {"file": "File:<exact Commons file name>", "caption": "<short description>"}
to data/photos.json (or a candidate list to tools/photo_candidates.json) and run this script.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import photos  # noqa: E402

CANDIDATES_FILE = ROOT / "tools" / "photo_candidates.json"
MIN_WIDTH = 1280
LANDSCAPE = 1.15
MAX_RATIO = 2.4      # wider than this (panoramas, Wikivoyage banners) becomes a thin strip in the photo frame


def load_countries() -> list[dict]:
    return json.loads((ROOT / "data" / "countries.json").read_text(encoding="utf-8"))


def state_ids(countries: list[dict]) -> set[str]:
    from core.data import STATES        # the same definition the app uses
    return {c["id"] for c in STATES}


def load_candidates(path: Path = CANDIDATES_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_landscape(rec: dict) -> bool:
    return bool(rec.get("width") and rec.get("height")) and rec["width"] / rec["height"] >= LANDSCAPE


def verified(rec: dict | None) -> bool:
    return bool(rec) and bool(rec.get("verified")) and photos.complete(rec) and bool(rec.get("width"))


def attribution(rec: dict) -> str:
    """'Photographer · licence · via Wikimedia Commons', or '' when either is missing (never raises)."""
    author, licence = (rec.get("author") or "").strip(), (rec.get("license") or "").strip()
    return f"{author} · {licence} · via Wikimedia Commons" if author and licence else ""


def fetch_all(names: list[str], fetch=None) -> dict[str, dict]:
    fetch = fetch or photos._fetch
    found: dict[str, dict] = {}
    for i in range(0, len(names), 50):
        found.update(fetch(names[i:i + 50]))
    return found


def build_record(cid: str, country: str, caption: str, name: str, meta: dict, today: str) -> dict:
    rec = {"country": country, "file": "File:" + name, "caption": caption,
           **{k: v for k, v in meta.items() if v}, "verified": today}
    rec.setdefault("url", photos.original_url(name))
    rec.setdefault("page", photos.page_url(name))
    return rec            # "attribution" is added by choose() only after every check has passed


def choose(cid: str, entry: dict, found: dict[str, dict], today: str,
           min_width: int = MIN_WIDTH) -> tuple[dict | None, list[str]]:
    """The first candidate that passes every rule (landscape and wide enough), or None with the reasons.
    An entry may give a file its own caption in "captions" ({"File:...": "..."}); otherwise "caption" is used."""
    reasons = []
    for title in entry["files"]:
        name = photos.file_name(title)
        meta = found.get(name)
        if not meta:
            reasons.append(f"{name}: not found on Commons")
            continue
        caption = entry.get("captions", {}).get(title) or entry["caption"]
        rec = build_record(cid, entry.get("country", cid), caption, name, meta, today)
        if not photos.complete(rec):
            reasons.append(f"{name}: licence '{meta.get('license')}' / author '{meta.get('author')}' not allowed")
        elif (rec.get("width") or 0) < min_width:
            reasons.append(f"{name}: only {rec.get('width')} px wide")
        elif not is_landscape(rec):
            reasons.append(f"{name}: not landscape ({rec.get('width')}×{rec.get('height')})")
        elif rec["width"] / rec["height"] > MAX_RATIO:
            reasons.append(f"{name}: too wide for the frame ({rec.get('width')}×{rec.get('height')})")
        else:
            rec["attribution"] = attribution(rec)
            return rec, reasons
    return None, reasons


def add_from_candidates(records: dict, cands: dict, fetch=None, landscape_review=False, today=None,
                        min_width: int = MIN_WIDTH) -> list[str]:
    """Add missing countries (and, with landscape_review, improve non-landscape ones). Returns log lines."""
    today = today or date.today().isoformat()
    jobs = {cid: e for cid, e in cands.get("add", {}).items() if not verified(records.get(cid))}
    if landscape_review:
        for cid, e in cands.get("landscape_review", {}).items():
            if verified(records.get(cid)) and not is_landscape(records[cid]):
                jobs[cid] = e
    names = sorted({photos.file_name(t) for e in jobs.values() for t in e["files"]})
    found = fetch_all(names, fetch) if names else {}
    log = []
    for cid, entry in sorted(jobs.items()):
        rec, reasons = choose(cid, entry, found, today, min_width)
        old = records.get(cid)
        if rec and verified(old):                       # landscape replacement: keep the old verified metadata
            rec["previous"] = {k: v for k, v in old.items() if k != "previous"}
            log.append(f"{cid}: replaced with landscape {photos.file_name(rec)} · {rec['author']} · {rec['license']}")
        elif rec:
            log.append(f"{cid}: added {photos.file_name(rec)} · {rec['author']} · {rec['license']} · {rec['width']}×{rec['height']}")
        else:
            log.append(f"{cid}: UNRESOLVED · " + "; ".join(reasons))
            continue
        records[cid] = rec
    return log


def refresh(records: dict, everything: bool, fetch=None) -> list[str]:
    todo = {cid: rec for cid, rec in records.items() if everything or not rec.get("verified")}
    names = {photos.file_name(rec): cid for cid, rec in todo.items()}
    found = fetch_all(list(names), fetch) if names else {}
    today, log = date.today().isoformat(), []
    for name, cid in names.items():
        rec, meta = records[cid], found.get(name)
        if not meta:
            log.append(f"{cid}: {name} not found on Commons")
            continue
        kept = {k: rec[k] for k in ("author", "license", "license_url") if rec.get(k)} if rec.get("author") and rec.get("license") else {}
        merged = {**rec, **{k: v for k, v in meta.items() if v}, **kept, "file": "File:" + name}
        if photos.complete(merged):
            merged["verified"] = today
            merged["attribution"] = attribution(merged)
            records[cid] = merged
            log.append(f"{cid}: ok · {merged['author']} · {merged['license']} · {merged.get('width')}×{merged.get('height')}")
        else:
            log.append(f"{cid}: NOT shown · licence '{meta.get('license')}' / author '{meta.get('author')}'")
            records[cid] = {**rec, **{k: meta[k] for k in ("url", "page", "width", "height") if meta.get(k)}}
    return log


URL_DELAY = 1.0          # seconds between requests: Wikimedia throttles fast automated thumbnail requests (HTTP 429)
URL_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}


def _probe(url: str, opener, sleep, retries: int = URL_RETRIES) -> int | str:
    """HTTP status of a HEAD request (GET of one byte if HEAD is refused), retrying throttling and server errors with
    the Retry-After delay or a growing pause. Returns the status code, or the exception name for network failures."""
    method, wait = "HEAD", 5.0
    for attempt in range(retries + 1):
        headers = {"User-Agent": photos.USER_AGENT}
        if method == "GET":
            headers["Range"] = "bytes=0-0"
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with opener(req, timeout=15) as resp:
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            status = exc.code
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after and str(retry_after).isdigit():
                wait = min(float(retry_after), 60.0)
        except Exception as exc:                        # noqa: BLE001 — DNS, timeout, proxy: reported, never fatal
            if attempt < min(retries, 1):
                sleep(wait)
                continue
            return type(exc).__name__
        if status == 405 and method == "HEAD":
            method = "GET"
            continue
        if status in RETRY_STATUSES and attempt < retries:
            sleep(wait)
            wait = min(wait * 2, 60.0)
            continue
        return status
    return status


def explain(status: int | str, original: int | str | None = None) -> str:
    if status == 429:
        return "rate-limited by Wikimedia (not a broken link; re-check later or with a longer --url-delay)"
    if status == 404:
        if isinstance(original, int) and original < 400:
            return "thumbnail not available, but the original file exists"
        return "file not found on Commons (renamed or deleted: choose another file)"
    if status == 403:
        return "refused by Wikimedia (User-Agent policy or blocked network)"
    if isinstance(status, str):
        return f"network error ({status}); check the internet connection or proxy"
    return f"HTTP {status}"


def check_urls(records: dict, opener=None, sleep=None, delay: float = URL_DELAY, only: set[str] | None = None) -> list[str]:
    """Request the thumbnail the app shows by default for every verified record, slowly enough not to be throttled.
    Returns one line per failure with the status code and its meaning; a 404 is double-checked on the original."""
    import time
    opener = opener or urllib.request.urlopen
    sleep = sleep or time.sleep
    bad, first = [], True
    for cid, rec in sorted(records.items()):
        if not verified(rec) or (only and cid not in only):
            continue
        if not first:
            sleep(delay)
        first = False
        src, _ = photos.sources(rec)
        status = _probe(src, opener, sleep)
        if isinstance(status, int) and status < 400:
            continue
        original = _probe(rec.get("url") or photos.original_url(photos.file_name(rec)), opener, sleep) if status == 404 else None
        bad.append(f"{cid}: {status if isinstance(status, int) else 'ERR'} · {explain(status, original)} · {src}")
    return bad


def url_summary(bad: list[str]) -> list[str]:
    limited = sum(" 429 · " in b for b in bad)
    lines = [f"Image URLs: {len(bad)} failed" + ("" if bad else " (all verified thumbnails answered)")]
    if limited:
        lines.append(f"  {limited} of them were rate limiting (429), not broken links. Re-check only those with "
                     "--check-urls --only ID,ID --url-delay 3")
    return lines + ["  " + b for b in bad]


def same_url(a: str, b: str) -> bool:
    """Commons writes some characters literally that we percent-encode (e.g. ',' '(' ')' "'"): compare decoded."""
    return urllib.parse.unquote(a) == urllib.parse.unquote(b)


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
        elif rec.get("height") and rec["width"] / rec["height"] < LANDSCAPE:
            problems.append(f"{cid}: not a landscape photo ({rec['width']}×{rec['height']}); prefer a wider one")
        if rec.get("url") and rec.get("file") and not same_url(rec["url"], photos.original_url(photos.file_name(rec))):
            problems.append(f"{cid}: image URL does not match the Commons file name")
        if rec.get("page") and not rec["page"].startswith("https://commons.wikimedia.org/wiki/File:"):
            problems.append(f"{cid}: source page is not a Commons file page")
    return problems


def coverage(records: dict, states: set[str]) -> dict:
    ok = sorted(cid for cid in states if verified(records.get(cid)))
    pending = sorted(cid for cid in states if cid in records and not verified(records[cid]))
    missing = sorted(states - set(records))
    return {"states": len(states), "verified": ok, "pending": pending, "missing": missing}


def summary_lines(cov: dict) -> list[str]:
    lines = [f"Coverage: {len(cov['verified'])}/{cov['states']} states have a verified photograph record"]
    if cov["pending"]:
        lines.append(f"  {len(cov['pending'])} with a record not verified yet: {' '.join(cov['pending'])}")
    if cov["missing"]:
        lines.append(f"  {len(cov['missing'])} with no record (locator-map fallback): {' '.join(cov['missing'])}")
    if len(cov["verified"]) == cov["states"]:
        lines.append("  All states verified.")
    return lines


def save(records: dict) -> None:
    photos.PHOTOS_FILE.write_text(json.dumps(dict(sorted(records.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    records = photos.load_records()
    countries = load_countries()
    ids = {c["id"] for c in countries}
    log: list[str] = []
    if "--check" not in argv:
        log += refresh(records, "--refresh" in argv)
        if "--add" in argv or "--landscape" in argv:
            cands = load_candidates()
            if "--add" not in argv:
                cands = {"landscape_review": cands.get("landscape_review", {})}
            min_width = int(argv[argv.index("--min-width") + 1]) if "--min-width" in argv else MIN_WIDTH
            log += add_from_candidates(records, cands, landscape_review="--landscape" in argv, min_width=min_width)
        save(records)
    for line in log:
        print(line)
    if "--check-urls" in argv:
        only = set(argv[argv.index("--only") + 1].upper().split(",")) if "--only" in argv else None
        delay = float(argv[argv.index("--url-delay") + 1]) if "--url-delay" in argv else URL_DELAY
        for line in url_summary(check_urls(records, delay=delay, only=only)):
            print(line)
    problems = check(records, ids)
    print(f"{len(records)} records · {sum(photos.complete(r) for r in records.values())} with credits")
    for p in problems:
        print("  " + p)
    for line in summary_lines(coverage(records, state_ids(countries))):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
