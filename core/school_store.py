"""Saved School Learning progress for signed-in students (dedicated tables; nothing shared with rewards).

Off by default. Progress is saved to Supabase only when BOTH are true:
  * the existing profile storage is configured ([profiles] url and server_key, core/accounts.py), and
  * the owner has switched School Learning storage on after running supabase/school_learning_migration.sql:
        [school]
        progress_storage = "supabase"
Until then (and always for guests) progress is not saved to any account, and the page says so. That way the app
never sends requests to tables that do not exist yet.

Two access modes (SCHOOL_LEARNING_SETUP.md explains the choice):
  * access = "server" (default): requests use the existing server key, from the server only, always filtered to the
    signed-in student's own id, exactly like the existing profile table.
  * access = "user_token" (recommended once [school] jwt_secret and anon_key are set): for each request the server
    signs a short-lived token that carries only the student's one-way id (claim "we_profile_id", role
    "authenticated"). The database's row-level security policies then allow that token to read and write only that
    student's rows, so even an application bug cannot reach another student's progress.

Tables (see the migration): school_lesson_progress (one row per student and lesson) and school_practice_attempts
(one row per finished practice). Practice answers are stored as question ids and right/wrong only, never names,
e-mails or free text.

This module never touches world_explorer_profiles, reward_* tables, points, badges or quiz statistics.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import urllib.parse
import urllib.request

PROGRESS_TABLE = "school_lesson_progress"
ATTEMPTS_TABLE = "school_practice_attempts"
_ID = re.compile(r"^[a-z0-9-]{1,64}$")
_USER = re.compile(r"^[0-9a-f]{64}$")
COLUMNS = ("page", "page_id", "furthest", "completed", "completed_at", "revision", "best", "last", "attempts", "answered",
           "correct", "recent_questions", "content_version", "practised_at", "updated_at")
# record key in core/school.py → column name
RENAMED = {"recent": "recent_questions", "version": "content_version"}
TOKEN_SECONDS = 300


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


def access_mode() -> str:
    config = _settings()
    if str(config.get("access", "")).strip().lower() == "user_token" and config.get("jwt_secret") and config.get("anon_key"):
        return "user_token"
    return "server"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def user_token(user_id: str, secret: str, now: float | None = None) -> str:
    """A short-lived HS256 token for one student: role 'authenticated' and the one-way id only (no name or e-mail)."""
    if not _USER.match(user_id or ""):
        raise ValueError("bad identifier")
    now = int(time.time() if now is None else now)
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"role": "authenticated", "we_profile_id": user_id, "iat": now, "exp": now + TOKEN_SECONDS,
                              "aud": "authenticated"}, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{header}.{claims}".encode(), hashlib.sha256).digest()
    return f"{header}.{claims}.{_b64(signature)}"


def _call(method: str, route: str, body=None, prefer: str | None = None, user_id: str | None = None):
    from . import accounts
    url, key = accounts._storage()
    if access_mode() == "user_token" and user_id:
        config = _settings()
        headers = {"apikey": str(config["anon_key"]), "Content-Type": "application/json",
                   "Authorization": "Bearer " + user_token(user_id, str(config["jwt_secret"]))}
    else:
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
    rows = _call("GET", f"/rest/v1/{PROGRESS_TABLE}?{q}", user_id=user_id)
    if not isinstance(rows, list):
        raise ValueError("unexpected response")
    out = {}
    for row in rows:
        if isinstance(row, dict) and _ID.match(str(row.get("lesson_id", ""))):
            back = {v: k for k, v in RENAMED.items()}
            out[row["lesson_id"]] = {back.get(k, k): row[k] for k in COLUMNS if row.get(k) is not None}
    return out


def row(user_id: str, subject: str, lesson_id: str, rec: dict) -> dict:
    """The row written for one lesson (only known columns; timestamps as ISO text)."""
    _check(user_id, subject, lesson_id)
    out = {"user_id": user_id, "subject": subject, "lesson_id": lesson_id}
    for key, value in rec.items():
        column = RENAMED.get(key, key)
        if column in COLUMNS:
            out[column] = value
    return out


def save(user_id: str, subject: str, lesson_id: str, rec: dict) -> None:
    """Insert or update one lesson's progress (one small request, only when something changed)."""
    _call("POST", f"/rest/v1/{PROGRESS_TABLE}?on_conflict=user_id,subject,lesson_id", row(user_id, subject, lesson_id, rec),
          prefer="resolution=merge-duplicates,return=minimal", user_id=user_id)


def attempt_row(user_id: str, subject: str, lesson_id: str, score: int, total: int, answers: list[dict],
                content_version: int = 1) -> dict:
    _check(user_id, subject, lesson_id)
    clean = [{"q": str(a["id"])[:32], "ok": bool(a["correct"])} for a in answers][:50]
    return {"user_id": user_id, "subject": subject, "lesson_id": lesson_id, "score": int(score), "total": int(total),
            "answers": clean, "content_version": int(content_version)}


def record_attempt(user_id: str, subject: str, lesson_id: str, score: int, total: int, answers: list[dict],
                   content_version: int = 1) -> None:
    _call("POST", f"/rest/v1/{ATTEMPTS_TABLE}", attempt_row(user_id, subject, lesson_id, score, total, answers, content_version),
          prefer="return=minimal", user_id=user_id)
