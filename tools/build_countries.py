"""Build data/countries.json and data/reference/coverage.json.

Usage:  python tools/build_countries.py <path to a mledoze/countries clone>

Inputs (all bundled):
  upstream countries.json            mledoze/countries (ODbL 1.0)
  data/reference/un_membership.json  reference list of UN members and observers
  data/reference/curation.json       documented corrections and editorial decisions
  data/reference/curated_facts.json  hand-checked facts from the original collection

The app never calls an external API: it only reads the generated JSON.
"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"
LANG_KEYS = {"Deutsch": "deu", "Español": "spa", "中文（普通话）": "zho"}
AMERICAS = {"South America": "South America"}  # every other Americas subregion maps to North America


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def continent_of(region, subregion):
    if region == "Americas":
        return AMERICAS.get(subregion, "North America")
    return region


def calling_codes(idd):
    root, suffixes = idd.get("root") or "", idd.get("suffixes") or []
    if not root:
        return []
    if root == "+1":
        return ["+1"]  # North American Numbering Plan: suffixes are area codes
    if len(suffixes) > 1 and all(len(s) == 1 for s in suffixes):
        return [root]  # e.g. +7: suffixes are number ranges inside one country code
    return [root + s for s in suffixes] or [root]


def main(clone: Path) -> None:
    upstream = load(clone / "countries.json")
    commit = subprocess.run(["git", "-C", str(clone), "log", "-1", "--format=%H %cs"],
                            capture_output=True, text=True).stdout.split()
    un, cur, facts = load(REF / "un_membership.json"), load(REF / "curation.json"), load(REF / "curated_facts.json")["records"]
    members, observers = un["members"], un["observers"]
    idmap = cur["id_mapping"]

    upstream_ids = [c["cca3"] for c in upstream]
    duplicates = [k for k, n in Counter(upstream_ids).items() if n > 1]
    records = []
    for src in upstream:
        uid = src["cca3"]
        cid = idmap.get(uid, uid)
        if uid in cur["excluded"]:
            continue
        if cid in members:
            status, note = "un_member", ""
        elif cid in observers:
            status, note = "un_observer", ""
        elif cid in cur["status_overrides"]:
            status, note = cur["status_overrides"][cid]
        else:
            status, note = "territory", cur["territory_notes"].get(cid, "")
        primary = continent_of(src["region"], src["subregion"])
        continents = cur["continents"].get(cid, [primary])
        fact = facts.get(cid, {})
        capitals = (cur["capitals"].get(cid, {}).get("capitals") or fact.get("capitals")
                    or [{"name": n, "role": "capital"} for n in src.get("capital", [])])
        capital_source = cur["capitals"].get(cid, {}).get("source") or fact.get("capital_source")
        rec = {
            "id": cid,
            "name": src["name"]["common"],
            "official_name": src["name"]["official"],
            "names": {lang: src.get("translations", {}).get(key, {}).get("common") for lang, key in LANG_KEYS.items()},
            "status": status,
            "status_note": note,
            "continent": continents[0],
            "continents": continents,
            "region": src["subregion"] or "",
            "capitals": capitals,
            "capital_question": cid not in cur["no_capital_question"] and (len(capitals) == 1 or bool(capital_source)),
            "currencies": [{"code": k, "name": v["name"]} for k, v in (src.get("currencies") or {}).items()],
            "currency_question": cid not in cur["no_currency_question"],
            "languages": cur["languages"].get(cid, list((src.get("languages") or {}).values())),
            "borders": [idmap.get(b, b) for b in cur["borders"].get(cid, src.get("borders") or [])],
            "landlocked": bool(src.get("landlocked")),
            "area_km2": src.get("area") if (src.get("area") or 0) > 0 else None,
            "domains": src.get("tld") or [],
            "calling_codes": cur["calling_codes"].get(cid, calling_codes(src.get("idd") or {})),
            "landmarks": fact.get("landmarks", []),
            "tier": fact.get("tier", 3),
            "source": "https://github.com/mledoze/countries",
            "source_version": commit[0] if commit else "",
            "data_date": commit[1] if len(commit) > 1 else "",
        }
        if capital_source:
            rec["capital_source"] = capital_source
        if cid in cur["no_currency_question"]:
            rec["currency_note"] = cur["no_currency_question"][cid]
        if cid in cur["no_capital_question"]:
            rec["capital_note"] = cur["no_capital_question"][cid]
        records.append(rec)

    ids = {r["id"] for r in records}
    for r in records:  # drop borders with places not in the collection
        r["borders"] = [b for b in r["borders"] if b in ids]
    asymmetric = sorted({tuple(sorted((r["id"], b))) for r in records for b in r["borders"]
                         if r["id"] not in next(x for x in records if x["id"] == b)["borders"]})
    records.sort(key=lambda r: r["name"])
    (ROOT / "data" / "countries.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    reference = set(members) | set(observers)
    report = {
        "upstream": {"repository": "https://github.com/mledoze/countries", "commit": commit[0] if commit else "",
                     "date": commit[1] if len(commit) > 1 else "", "entries": len(upstream), "licence": "ODbL 1.0"},
        "reference": {"un_members": len(members), "un_observers": len(observers), "checked_on": un["checked_on"]},
        "missing_from_collection": sorted(reference - ids),
        "duplicate_upstream_ids": duplicates,
        "holy_see_mapping": "UN observer 'Holy See' and ISO 'Vatican City' are the single record VAT.",
        "upstream_un_member_flag_disagreements": sorted(
            idmap.get(c["cca3"], c["cca3"]) for c in upstream
            if bool(c.get("unMember")) != (idmap.get(c["cca3"], c["cca3"]) in members)),
        "excluded": cur["excluded"],
        "asymmetric_borders": asymmetric,
        "counts": dict(Counter(r["status"] for r in records), total=len(records)),
    }
    (REF / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["counts"]), "missing:", report["missing_from_collection"],
          "dupes:", duplicates, "asymmetric:", asymmetric, "flag disagreements:", report["upstream_un_member_flag_disagreements"])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
