"""Saved School Learning progress for signed-in students (dedicated tables; nothing shared with rewards).

Off by default. Progress is saved to Supabase only when BOTH are true:
  * the existing profile storage is configured ([profiles] url and server_key, core/accounts.py), and
  * the owner has switched School Learning storage on after running supabase/school_learning_migration.sql:
        [school]
        progress_storage = "supabase"
Until then (and always for guests) progress lives in this browser session only, and the page says so. That way the
app never sends requests to tables that do not exist yet.

Tables (see the migration): school_lesson_progress (one row per student and lesson) and school_practice_attempts
(one row per finished practice). Only the server key is used, from the server; the browser roles have no access.
Practice answers are stored as question ids and right/wrong only, never names, e-mails or free text.

This module never touches world_explorer_profiles, reward_* tables, points, badges or quiz statistics.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

PROGRESS_TABLE = "school_lesson_progress"
ATTEMPTS_TABLE = "school_practice_attempts"
_ID = re.compile(r"^[a-z0-9-]{1,64}$")
_USER = re.compile(r"^[0-9a-f]{64}$")
COLUMNS = ("page", "furthest", "completed", "completed_at", "revision", "best", "last", "attempts", "practised_at", "updated_at")


def _settings() -> dict:
    from . import accounts
    return accounts._secret_section("school")


def enabled() -> bool:
    """True only when the owner has switched storage on AND the profile storage is configured."""
    from . import accounts
    return str(_settings().get("progress_storage", "")).strip().lower() == "supabase" and accounts.storage_ready()


def _headers(key: str) -> dict:
    headers = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    return headers


def _call(method: str, route: str, body=None, prefer: str | None = None):
    from . import accounts
    url, key = accounts._storage()
    headers = _headers(key)
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url + route, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(1_000_000)
    return json.loads(raw) if raw else None


def _check(user_id: str, subject: str, lesson_id: str | None = None) -> None:
    if not _USER.match(user_id or "") or not _ID.match(subject or "") or (lesson_id is not None and not _ID.match(lesson_id)):
        raise ValueError("bad identifier")


def load(user_id: str, subject: str) -> dict[str, dict]:
    """{lesson_id: record} for one student and subject. Raises on network or storage errors (the caller retries)."""
    _check(user_id, subject)
    q = urllib.parse.urlencode({"user_id": f"eq.{user_id}", "subject": f"eq.{subject}", "select": "lesson_id," + ",".join(COLUMNS)})
    rows = _call("GET", f"/rest/v1/{PROGRESS_TABLE}?{q}")
    if not isinstance(rows, list):
        raise ValueError("unexpected response")
    out = {}
    for row in rows:
        if isinstance(row, dict) and _ID.match(str(row.get("lesson_id", ""))):
            out[row["lesson_id"]] = {k: row[k] for k in COLUMNS if row.get(k) is not None}
    return out


def row(user_id: str, subject: str, lesson_id: str, rec: dict) -> dict:
    """The row written for one lesson (only known columns; timestamps as ISO text)."""
    _check(user_id, subject, lesson_id)
    out = {"user_id": user_id, "subject": subject, "lesson_id": lesson_id}
    out.update({k: rec[k] for k in COLUMNS if k in rec})
    return out


def save(user_id: str, subject: str, lesson_id: str, rec: dict) -> None:
    """Insert or update one lesson's progress (one small request, only when something changed)."""
    _call("POST", f"/rest/v1/{PROGRESS_TABLE}?on_conflict=user_id,subject,lesson_id", row(user_id, subject, lesson_id, rec),
          prefer="resolution=merge-duplicates,return=minimal")


def attempt_row(user_id: str, subject: str, lesson_id: str, score: int, total: int, answers: list[dict]) -> dict:
    _check(user_id, subject, lesson_id)
    clean = [{"q": str(a["id"])[:32], "ok": bool(a["correct"])} for a in answers][:50]
    return {"user_id": user_id, "subject": subject, "lesson_id": lesson_id, "score": int(score), "total": int(total), "answers": clean}


def record_attempt(user_id: str, subject: str, lesson_id: str, score: int, total: int, answers: list[dict]) -> None:
    _call("POST", f"/rest/v1/{ATTEMPTS_TABLE}", attempt_row(user_id, subject, lesson_id, score, total, answers),
          prefer="return=minimal")
