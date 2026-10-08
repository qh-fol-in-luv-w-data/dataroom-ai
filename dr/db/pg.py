"""Project-local PostgreSQL cluster: lifecycle and connection helpers.

The cluster listens only on a unix socket inside ./pgdata/sock (no TCP).
- admin():         dr_admin (superuser, table owner) for the connector, ingest and console.
- as_principal():  app_query (NOBYPASSRLS) with app.principal_oid set for one transaction.
"""
from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg

from dr.config import settings

SCHEMA = Path(__file__).with_name("schema.sql")


def _bin(name: str) -> str:
    return str(settings.pg_bin / name)


def _running() -> bool:
    r = subprocess.run([_bin("pg_ctl"), "-D", str(settings.pgdata), "status"],
                       capture_output=True, text=True)
    return r.returncode == 0


def ensure_cluster() -> None:
    """Create (if needed), start (if needed) and migrate the local cluster."""
    pgdata = settings.pgdata
    if not (pgdata / "PG_VERSION").exists():
        pgdata.mkdir(parents=True, exist_ok=True)
        subprocess.run([_bin("initdb"), "-D", str(pgdata), "-U", "dr_admin", "--auth=trust",
                        "-E", "UTF8", "--locale=C"], check=True, capture_output=True)
    settings.sock_dir.mkdir(parents=True, exist_ok=True)
    if not _running():
        log = settings.root / "logs" / "postgres.log"
        log.parent.mkdir(exist_ok=True)
        opts = f"-k {settings.sock_dir} -p {settings.pg_port} -c listen_addresses=''"
        # macOS: postmaster aborts ("became multithreaded during startup") without a valid LC_ALL.
        env = {**os.environ, "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
        subprocess.run([_bin("pg_ctl"), "-D", str(pgdata), "-o", opts, "-l", str(log), "-w", "start"],
                       check=True, capture_output=True, env=env)
    with psycopg.connect(settings.dsn("dr_admin").replace(f"dbname={settings.pg_db}", "dbname=postgres"),
                         autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (settings.pg_db,)).fetchone():
            c.execute(f'CREATE DATABASE "{settings.pg_db}"')
    with admin() as c:
        c.execute(SCHEMA.read_text())
        c.commit()


def stop_cluster() -> None:
    if _running():
        subprocess.run([_bin("pg_ctl"), "-D", str(settings.pgdata), "-m", "fast", "stop"],
                       check=True, capture_output=True)


def admin() -> psycopg.Connection:
    return psycopg.connect(settings.dsn("dr_admin"))


@contextmanager
def as_principal(oid: str | None) -> Iterator[psycopg.Cursor]:
    """One read transaction as app_query with the principal bound transaction-locally."""
    with psycopg.connect(settings.dsn("app_query")) as conn:
        with conn.transaction():
            cur = conn.cursor()
            if oid is not None:
                cur.execute("SELECT set_config('app.principal_oid', %s, true)", (oid,))
            yield cur


def reset_all() -> None:
    """Wipe all demo data (keeps schema)."""
    with admin() as c:
        c.execute("TRUNCATE chunks, items, grants, memberships, user_roles, users_mirror, revocations, "
                  "deny_list, feed_status, item_reader, audit, sites, site_stats, term_stats, review_drafts RESTART IDENTITY CASCADE")
        c.commit()
