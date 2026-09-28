"""Apply SQL migrations in supabase/migrations/ in order, once each.

Usage:
  python scripts/migrate.py --status        # show applied / pending (read-only)
  python scripts/migrate.py --apply         # apply pending migrations
  python scripts/migrate.py --apply --skip 0002_supabase_storage.sql   # e.g. plain Postgres
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

from engine.core.config import get_settings  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--skip", action="append", default=[])
    args = parser.parse_args()

    files = sorted(MIGRATIONS.glob("*.sql"))
    with psycopg.connect(get_settings().database_url, prepare_threshold=None) as conn:
        conn.execute("create table if not exists schema_migrations "
                     "(name text primary key, applied_at timestamptz not null default now())")
        conn.execute("alter table schema_migrations enable row level security")
        applied = {row[0] for row in conn.execute("select name from schema_migrations")}
        conn.commit()
        for file in files:
            state = "applied" if file.name in applied else ("skipped" if file.name in args.skip else "pending")
            if args.status or state != "pending":
                print(f"{state:8} {file.name}")
                continue
            with conn.transaction():
                conn.execute(file.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations (name) values (%s)", (file.name,))
            print(f"applied  {file.name}")


if __name__ == "__main__":
    main()
