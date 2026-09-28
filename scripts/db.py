"""Run SQL against the Supabase Postgres database from the command line.

Reads DATABASE_SESSION_POOL_URL (or DATABASE_URL) from the project's .env. Transactions are read-only unless
--write is passed, so exploratory queries can't change data by accident.

Usage:
  python scripts/db.py "select now()"
  python scripts/db.py --tables                 # list tables in public
  python scripts/db.py --describe clients       # columns of a table
  python scripts/db.py --write -f migration.sql # run a file with writes allowed
  echo "select 1" | python scripts/db.py
"""

import argparse
import re
import sys
from pathlib import Path

import psycopg

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def database_url() -> str:
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(?:DATABASE_SESSION_POOL_URL|DATABASE_URL)\s*=\s*(.*)\s*$", line)
        if match:
            return match[1].strip().strip('"').strip("'")
    sys.exit(f"DATABASE_SESSION_POOL_URL not found in {ENV_PATH}")


def print_rows(cur: psycopg.Cursor) -> None:
    if cur.description is None:
        print(f"OK ({cur.rowcount} rows affected)")
        return
    headers = [col.name for col in cur.description]
    rows = [["" if v is None else str(v) for v in row] for row in cur.fetchall()]
    widths = [min(60, max(len(h), *(len(r[i]) for r in rows))) if rows else len(h)
              for i, h in enumerate(headers)]
    print(" | ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(" | ".join(v[:w].ljust(w) for v, w in zip(row, widths)))
    print(f"({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sql", nargs="?", help="SQL to run (or use -f, or pipe via stdin)")
    parser.add_argument("-f", "--file", help="run SQL from a file")
    parser.add_argument("--write", action="store_true", help="allow writes (default is read-only)")
    parser.add_argument("--tables", action="store_true", help="list tables in the public schema")
    parser.add_argument("--describe", metavar="TABLE", help="show columns of a public table")
    args = parser.parse_args()

    if args.tables:
        sql = ("select table_name, table_type from information_schema.tables "
               "where table_schema = 'public' order by table_name")
    elif args.describe:
        sql = ("select column_name, data_type, is_nullable, column_default "
               "from information_schema.columns where table_schema = 'public' "
               f"and table_name = '{args.describe.replace(chr(39), '')}' order by ordinal_position")
    elif args.file:
        sql = Path(args.file).read_text(encoding="utf-8")
    elif args.sql:
        sql = args.sql
    elif not sys.stdin.isatty():
        sql = sys.stdin.read()
    else:
        parser.error("no SQL given")

    with psycopg.connect(database_url(), connect_timeout=15) as conn:
        conn.read_only = not args.write
        with conn.cursor() as cur:
            cur.execute(sql)
            print_rows(cur)
            while cur.nextset():
                print_rows(cur)


if __name__ == "__main__":
    main()
