"""Test-only legal fixtures: both synthetic DRAFT documents and completed samples.

The real private pilot documents may be final. Safety tests must use deliberately incomplete copies rather
than assuming that the real legal documents always remain drafts.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "2026-11-01-test"
_DIR: str | None = None
_DRAFT_DIR: str | None = None


def completed_dir() -> str:
    """A folder with the three documents made complete: no DRAFT notice, no [open items], final version."""
    global _DIR
    if _DIR is None:
        _DIR = tempfile.mkdtemp(prefix="we-legal-")
        for name in ("PRIVACY_POLICY.md", "TERMS_OF_USE.md", "PILOT_TERMS.md", "PILOT_PRIVACY_NOTICE.md"):
            text = (ROOT / "legal" / name).read_text(encoding="utf-8")
            text = "\n".join(line for line in text.splitlines() if not line.startswith(">"))   # the DRAFT notice
            text = re.sub(r"\[[^\]\n]+\](?!\()", "(confirmed)", text)                         # open decisions
            text = re.sub(r"\*Version:[^*]*\*", f"*Version: {VERSION}*", text)
            (Path(_DIR) / name).write_text(text, encoding="utf-8")
    return _DIR


def draft_dir() -> str:
    """Create explicitly incomplete test copies of ALL four legal documents.

    This preserves fail-closed coverage after the owner adopts the actual private-pilot agreement.
    The real files are never modified.
    """
    global _DRAFT_DIR
    if _DRAFT_DIR is None:
        _DRAFT_DIR = tempfile.mkdtemp(prefix="we-legal-draft-")
        for name in ("PRIVACY_POLICY.md", "TERMS_OF_USE.md", "PILOT_TERMS.md", "PILOT_PRIVACY_NOTICE.md"):
            text = (ROOT / "legal" / name).read_text(encoding="utf-8")
            # Last version label wins in core/legal.py; enforce a draft version and one explicit open issue.
            text = ("> DRAFT for legal review - SYNTHETIC TEST FIXTURE ONLY\n\n"
                    + text.rstrip() + "\n\n[unresolved test decision]\n\n*Version: draft-test*\n")
            (Path(_DRAFT_DIR) / name).write_text(text, encoding="utf-8")
    return _DRAFT_DIR


def use_draft() -> None:
    os.environ["WORLD_EXPLORER_LEGAL_DIR"] = draft_dir()


def use_completed() -> None:
    os.environ["WORLD_EXPLORER_LEGAL_DIR"] = completed_dir()


def use_real() -> None:
    os.environ.pop("WORLD_EXPLORER_LEGAL_DIR", None)


FILES = {"privacy": "PRIVACY_POLICY.md", "terms": "TERMS_OF_USE.md", "pilot": "PILOT_TERMS.md",
         "pilot_privacy": "PILOT_PRIVACY_NOTICE.md"}
APPROVED_BY = "Test Legal Officer"
APPROVED_ON = "2026-10-20"


def checksum(key: str, folder: str | None = None) -> str:
    """SHA-256 of a document's content, computed independently of core/legal.py (same line-ending rule)."""
    import hashlib
    text = (Path(folder or completed_dir()) / FILES[key]).read_text(encoding="utf-8")
    return hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


def pilot_terms_id(folder: str | None = None) -> str:
    return f"{VERSION}#{checksum('pilot', folder)[:16]}"


def secrets(docs=("privacy", "terms", "pilot"), verified=True) -> dict:
    """[legal] settings that publish the completed documents (call use_completed() as well): the approvals are the
    documents' content checksums."""
    use_completed()
    cfg = {"operator_verified": verified, "contact_email": "privacy@example.com",
           "registered_address": "1 Example Street, Lagos, Nigeria",
           "approved": {d: checksum(d) for d in docs if d in ("privacy", "terms")}}
    if "pilot" in docs:   # the private pilot's own approval record (agreement + privacy notice)
        cfg["pilot_approval"] = pilot_approval()
    return cfg


def pilot_approval(**changes) -> dict:
    record = {"approved_by": APPROVED_BY, "approved_on": APPROVED_ON}
    for key in ("pilot", "pilot_privacy"):
        record[f"{key}_version"] = VERSION
        record[f"{key}_sha256"] = checksum(key)
    record.update(changes)
    return record
