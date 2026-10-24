"""Legal information: the proposed operator, the documents and the rules that keep them in draft until approved.

Owner settings (Streamlit secrets), all off/empty by default:

    [legal]
    operator_verified = false    # the company's role as operator and data controller has been confirmed
    contact_email = ""           # privacy / legal contact shown in the documents
    registered_address = ""      # the company's registered address (from the CAC records)

    [legal.approved]             # the owner confirms the completed legal review of each document's EXACT content
    privacy = ""                 # the document's SHA-256 checksum, shown in Owner dashboard → ⚖️ Legal & switches
    terms = ""
    pilot = ""

A document is published ("live") only when ALL of these hold:
  * operator_verified is true (the company is never presented as operator or data controller before that);
  * contact_email is a valid address and registered_address is filled in;
  * the document itself is complete: no "DRAFT" notice, no [bracketed] open decisions, no unfilled {{fields}},
    and a final version (not "draft-...");
  * the owner approved exactly that content: the approval is the SHA-256 checksum of the document file, so ANY change
    to an approved document (even one character, even with the same version line) unpublishes it until the owner
    approves the new checksum. The version line is the human-readable label.

The Privacy Policy and Terms of Use can be published on their own (for every user, independently of the pilot or
any rewards programme). The Friends & Family Pilot additionally needs its pilot terms; public rewards and every money
switch need the Privacy Policy and Terms of Use (see ui/rewards_hooks.py).
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

BRAND = "World Explorer"
OPERATOR = {
    "name": "OKETORIAH KÖNIGREICH LTD",
    "rc": "RC 7160552",
    "incorporated": "30 September 2023",
    "type": "Private Company Limited by Shares",
    "country": "Nigeria",
}
DOCUMENTS = {   # key: (title, file)
    "privacy": ("Privacy Policy", "PRIVACY_POLICY.md"),
    "terms": ("Terms of Use", "TERMS_OF_USE.md"),
    "pilot": ("Friends & Family Pilot terms", "PILOT_TERMS.md"),
}
GENERAL = ("privacy", "terms")            # for every user; also required before public rewards or any money switch
PILOT = ("privacy", "terms", "pilot")     # required before the Friends & Family Pilot opens
PILOT_MAX_PLACES = 50                     # the Friends & Family Pilot: at most 50 individually approved adults
TO_CONFIRM = "[to be confirmed]"
DRAFT_MARK = "DRAFT for legal review"
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}")
VERSION = re.compile(r"^\*Version:\s*([^*]+?)\s*\*\s*$", re.M)
OPEN_BRACKET = re.compile(r"\[[^\]\n]+\](?!\()")          # [open decision] — but not a Markdown link [text](url)


def config() -> dict:
    try:
        import streamlit as st
        return dict(st.secrets.get("legal", {}))
    except Exception:
        return {}


def legal_dir() -> Path:
    """legal/ in the project. WORLD_EXPLORER_LEGAL_DIR is a test-only override (completed sample documents)."""
    return Path(os.environ.get("WORLD_EXPLORER_LEGAL_DIR") or Path(__file__).resolve().parent.parent / "legal")


def operator_verified(cfg: dict | None = None) -> bool:
    return (cfg if cfg is not None else config()).get("operator_verified") is True


def contact_email(cfg: dict) -> str:
    v = str(cfg.get("contact_email") or "").strip()
    return v if EMAIL.fullmatch(v) else ""


def registered_address(cfg: dict) -> str:
    v = str(cfg.get("registered_address") or "").strip()
    return v if len(v) >= 10 and "[" not in v and "{" not in v else ""


def raw_text(key: str) -> str:
    return (legal_dir() / DOCUMENTS[key][1]).read_text(encoding="utf-8")


def checksum(key: str) -> str:
    """SHA-256 of the document file's exact content (line endings normalised, so a Windows checkout gives the same
    value). This is what the owner approves."""
    text = raw_text(key).replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pilot_terms_id() -> str:
    """The identifier recorded with every pilot application (and in the database as the approved participation terms):
    the version label plus the first 16 hex characters of the content checksum, e.g. "2026-11-05#3fa1…"."""
    return f"{version('pilot')}#{checksum('pilot')[:16]}"


def version(key: str) -> str:
    found = VERSION.findall(raw_text(key))
    return found[-1].strip() if found else ""


def approved_version(key: str, cfg: dict) -> str:
    approved = cfg.get("approved") or {}
    try:
        return str(dict(approved).get(key) or "").strip()
    except Exception:
        return ""


def _fill(text: str, cfg: dict) -> str:
    return (text.replace("{{CONTACT_EMAIL}}", contact_email(cfg) or TO_CONFIRM)
                .replace("{{REGISTERED_ADDRESS}}", registered_address(cfg) or TO_CONFIRM))


def problems(key: str, cfg: dict | None = None) -> list[str]:
    """Why this document cannot be published yet (empty list = it is live)."""
    cfg = cfg if cfg is not None else config()
    out = []
    if not operator_verified(cfg):
        out.append("The company's role as operator and data controller is not confirmed ([legal] operator_verified).")
    if not contact_email(cfg):
        out.append("No valid contact email ([legal] contact_email).")
    if not registered_address(cfg):
        out.append("No registered address ([legal] registered_address).")
    text = raw_text(key)
    v = version(key)
    if DRAFT_MARK in text:
        out.append("The document still carries the DRAFT notice.")
    open_items = OPEN_BRACKET.findall(text)
    if open_items:
        out.append(f"{len(open_items)} open item(s) in [brackets], e.g. {open_items[0][:60]}")
    if re.search(r"\{\{(?!CONTACT_EMAIL\}\}|REGISTERED_ADDRESS\}\})", text):
        out.append("Unfilled {{fields}} in the document.")
    if not v or v.lower().startswith("draft"):
        out.append(f"The version is not final ({v or 'missing'}).")
    approved = approved_version(key, cfg).lower()
    if approved != checksum(key):
        out.append(("Changed since it was approved" if approved else "Not approved") + ": after the legal review, set "
                   f"[legal.approved] {key} = \"{checksum(key)}\" (the checksum of this exact text).")
    return out


def doc_live(key: str, cfg: dict | None = None) -> bool:
    return not problems(key, cfg)


def live(cfg: dict | None = None) -> bool:
    """The general documents (Privacy Policy, Terms of Use) are published. Required before public rewards enrolment,
    withdrawals or payouts can open."""
    cfg = cfg if cfg is not None else config()
    return all(doc_live(k, cfg) for k in GENERAL)


def pilot_ready(cfg: dict | None = None) -> bool:
    """Privacy Policy, Terms of Use and pilot terms are all published. Required before the pilot opens."""
    cfg = cfg if cfg is not None else config()
    return all(doc_live(k, cfg) for k in PILOT)


def live_documents(cfg: dict | None = None) -> list[str]:
    cfg = cfg if cfg is not None else config()
    return [k for k in DOCUMENTS if doc_live(k, cfg)]


def operator_line() -> str:
    """The short business identification (public only once a document is live, which needs operator_verified)."""
    return f"{BRAND} — Operated by {OPERATOR['name']}."


def identification(verified: bool = True) -> str:
    o = OPERATOR
    text = (f"{BRAND} is operated by {o['name']} ({o['rc']}), a {o['type'].lower()} incorporated in "
            f"{o['country']} on {o['incorporated']}.")
    return text if verified else ("Proposed operator, not yet verified: " + o["name"] + f" ({o['rc']}), "
                                  f"{o['type'].lower()}, {o['country']}.")


def document(key: str, cfg: dict | None = None) -> str:
    """The Markdown text of one document with the contact details filled in."""
    cfg = cfg if cfg is not None else config()
    return _fill(raw_text(key), cfg)


def status(cfg: dict | None = None) -> list[dict]:
    """For the owner dashboard: each requirement and document, and what is still missing."""
    cfg = cfg if cfg is not None else config()
    rows = [
        {"switch": "[legal] operator_verified", "on": operator_verified(cfg),
         "controls": "Confirms the company is the operator and data controller (legal/OPERATOR_VERIFICATION.md)."},
        {"switch": "[legal] contact_email", "on": bool(contact_email(cfg)), "controls": "Privacy and legal contact."},
        {"switch": "[legal] registered_address", "on": bool(registered_address(cfg)),
         "controls": "The company's registered address."},
    ]
    for key, (title, _) in DOCUMENTS.items():
        issues = problems(key, cfg)
        rows.append({"switch": f"{title} ({version(key) or 'no version'})", "on": not issues,
                     "controls": (f"Published · checksum {checksum(key)}" if not issues else
                                  " · ".join(issues) + f" · checksum {checksum(key)}")})
    return rows
