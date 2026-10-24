"""Test-only: completed sample legal documents and the owner settings that publish them.

The real documents in legal/ are drafts (DRAFT notice, [open items], draft version), so they can never be published by
the rules in core/legal.py. Tests that need published documents point WORLD_EXPLORER_LEGAL_DIR at completed copies
made here, and use secrets() for the matching approvals.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "2026-11-01-test"
_DIR: str | None = None


def completed_dir() -> str:
    """A folder with the three documents made complete: no DRAFT notice, no [open items], final version."""
    global _DIR
    if _DIR is None:
        _DIR = tempfile.mkdtemp(prefix="we-legal-")
        for name in ("PRIVACY_POLICY.md", "TERMS_OF_USE.md", "PILOT_TERMS.md"):
            text = (ROOT / "legal" / name).read_text(encoding="utf-8")
            text = "\n".join(line for line in text.splitlines() if not line.startswith(">"))   # the DRAFT notice
            text = re.sub(r"\[[^\]\n]+\](?!\()", "(confirmed)", text)                         # open decisions
            text = re.sub(r"\*Version:[^*]*\*", f"*Version: {VERSION}*", text)
            (Path(_DIR) / name).write_text(text, encoding="utf-8")
    return _DIR


def use_completed() -> None:
    os.environ["WORLD_EXPLORER_LEGAL_DIR"] = completed_dir()


def use_real() -> None:
    os.environ.pop("WORLD_EXPLORER_LEGAL_DIR", None)


FILES = {"privacy": "PRIVACY_POLICY.md", "terms": "TERMS_OF_USE.md", "pilot": "PILOT_TERMS.md"}


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
    return {"operator_verified": verified, "contact_email": "privacy@example.com",
            "registered_address": "1 Example Street, Lagos, Nigeria", "approved": {d: checksum(d) for d in docs}}
