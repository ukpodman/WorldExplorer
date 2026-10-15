"""A throwaway local PostgreSQL for testing supabase/rewards_schema.sql (used only by the tests).

It starts a private cluster in a temporary folder, creates the Supabase roles (anon, authenticated, service_role)
and loads the schema into a template database. PsqlStore talks to it through the psql command line with the same
six primitives as the real SupabaseStore, so every RewardsStore operation is exercised against the real SQL
(triggers, functions, constraints). Skipped automatically when PostgreSQL is not installed.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from core.rewards_store import RewardsStore, StoreError

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "supabase" / "rewards_schema.sql"
MIGRATION = ROOT / "supabase" / "withdrawals_migration.sql"   # V21 cash withdrawals (loaded after the schema)


def _bin(name: str) -> str | None:
    found = sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{name}"))
    return found[-1] if found else shutil.which(name)


def available() -> bool:
    return bool(_bin("initdb") and _bin("pg_ctl") and shutil.which("psql") and SCHEMA.exists())


class Cluster:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="we-pg-")
        self.port = str(55000 + os.getpid() % 900)
        self.root = os.geteuid() == 0
        os.chmod(self.dir, 0o777)
        self._as_owner(f"{_bin('initdb')} -D {self.dir}/data -A trust -U postgres -E UTF8")
        self._as_owner(f"{_bin('pg_ctl')} -D {self.dir}/data -w -l {self.dir}/log "
                       f"-o '-p {self.port} -k {self.dir} -c listen_addresses= -c fsync=off'  start")
        for statement in ("create role anon nologin", "create role authenticated nologin",
                          "create role service_role nologin bypassrls", "create database rt_template"):
            self.psql("postgres", statement)
        self.psql_file("rt_template", SCHEMA)
        if MIGRATION.exists():
            self.psql_file("rt_template", MIGRATION)
        self.count = 0

    def _as_owner(self, command: str) -> None:
        if self.root:
            subprocess.run(["su", "postgres", "-c", command], check=True, capture_output=True)
        else:
            subprocess.run(command, shell=True, check=True, capture_output=True)

    def psql(self, db: str, sql: str, role: str | None = None) -> str:
        if role:
            sql = f"set role {role};\n{sql}"
        result = subprocess.run(["psql", "-h", self.dir, "-p", self.port, "-U", "postgres", "-d", db, "-At", "-q",
                                 "-v", "ON_ERROR_STOP=1", "-c", sql], capture_output=True, text=True)
        if result.returncode != 0:
            match = re.search(r"ERROR:\s+(.*)", result.stderr)
            raise StoreError(match.group(1).strip() if match else result.stderr.strip())
        return result.stdout.strip()

    def psql_file(self, db: str, path: Path) -> None:
        result = subprocess.run(["psql", "-h", self.dir, "-p", self.port, "-U", "postgres", "-d", db, "-q",
                                 "-v", "ON_ERROR_STOP=1", "-f", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)

    def fresh_db(self) -> str:
        self.count += 1
        name = f"rt_{self.count}"
        self.psql("postgres", f"create database {name} template rt_template")
        return name

    def stop(self) -> None:
        try:
            self._as_owner(f"{_bin('pg_ctl')} -D {self.dir}/data -m immediate stop")
        finally:
            time.sleep(0.2)
            shutil.rmtree(self.dir, ignore_errors=True)


def literal(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value)
    return "'" + str(value).replace("'", "''") + "'"


def where_sql(where: dict | None) -> str:
    parts = []
    for col, cond in (where or {}).items():
        if isinstance(cond, tuple):
            op, arg = cond
            if op == "in":
                parts.append(f"{col} in ({', '.join(literal(a) for a in arg)})")
            else:
                parts.append(f"{col} {dict(gte='>=', lte='<=', neq='<>')[op]} {literal(arg)}")
        elif cond is None:
            parts.append(f"{col} is null")
        else:
            parts.append(f"{col} = {literal(cond)}")
    return (" where " + " and ".join(parts)) if parts else ""


class PsqlStore(RewardsStore):
    kind = "psql"

    def __init__(self, cluster: Cluster, db: str, role: str = "service_role"):
        self.cluster, self.db, self.role = cluster, db, role

    def _json(self, sql: str):
        out = self.cluster.psql(self.db, sql, self.role)
        return json.loads(out) if out else None

    def select(self, table, where=None, order=None, limit=None):
        order_sql = ""
        if order:
            order_sql = " order by " + ", ".join(
                p.split(".")[0] + (" desc" if p.endswith(".desc") else "") for p in order.split(","))
        limit_sql = f" limit {int(limit)}" if limit is not None else ""
        return self._json(f"select coalesce(json_agg(t), '[]') from (select * from public.{table}"
                          f"{where_sql(where)}{order_sql}{limit_sql}) t")

    def insert(self, table, row, ignore_duplicates=False, conflict=None):
        cols = ", ".join(row)
        conflict_sql = f" on conflict ({conflict}) do nothing" if ignore_duplicates and conflict else (
            " on conflict do nothing" if ignore_duplicates else "")
        payload = json.dumps(row, default=str).replace("'", "''")
        return self._json(f"with ins as (insert into public.{table} ({cols}) select {cols} from "
                          f"json_populate_record(null::public.{table}, '{payload}'::json){conflict_sql} returning *) "
                          f"select coalesce(json_agg(ins), '[]') from ins")

    def update(self, table, where, changes):
        sets = ", ".join(f"{c} = (json_populate_record(null::public.{table}, {literal(json.dumps({c: v}, default=str))}::json)).{c}"
                         for c, v in changes.items())
        return self._json(f"with up as (update public.{table} set {sets}{where_sql(where)} returning *) "
                          f"select coalesce(json_agg(up), '[]') from up")

    def delete(self, table, where):
        out = self._json(f"with d as (delete from public.{table}{where_sql(where)} returning 1) "
                         f"select count(*) from d")
        return int(out or 0)

    def rpc(self, name, args):
        call = ", ".join(f"{k} => {literal(v)}" for k, v in args.items())
        return self._json(f"select to_json(public.{name}({call}))")
