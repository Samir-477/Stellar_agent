"""Delete every run except the newest N, for good, with the same delete the Sessions page uses.

    python scripts/prune_runs.py --keep 5          # list what would be deleted
    python scripts/prune_runs.py --keep 5 --yes    # back up the rows to .data/backups/, then delete

The backup holds the database rows (runs, tasks, findings, patches, reports, microsites and the
snapshots, pages and evidence only those runs used), not the stored files.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.core.blobstore import make_blob_store  # noqa: E402
from engine.core.config import get_settings  # noqa: E402
from engine.core.db import connection  # noqa: E402
from engine.orchestrator.retention import delete_run  # noqa: E402

BY_RUN = ("tasks", "findings", "patches", "reports", "microsites")


def backup(run_ids: list[str]) -> Path:
    rows: dict[str, list] = {}
    with connection() as conn:
        rows["runs"] = conn.execute("select * from runs where id = any(%s)", (run_ids,)).fetchall()
        for table in BY_RUN:
            rows[table] = conn.execute(f"select * from {table} where run_id = any(%s)", (run_ids,)).fetchall()
        snapshots = [r["snapshot_id"] for r in rows["runs"]]
        rows["snapshots"] = conn.execute("select * from snapshots where id = any(%s)", (snapshots,)).fetchall()
        rows["pages"] = conn.execute("select * from pages where snapshot_id = any(%s)", (snapshots,)).fetchall()
        rows["evidence"] = conn.execute("select * from evidence where snapshot_id = any(%s)", (snapshots,)).fetchall()
        clients = list({r["client_id"] for r in rows["runs"]})
        rows["clients"] = conn.execute("select * from clients where id = any(%s)", (clients,)).fetchall()
    folder = ROOT / ".data" / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"runs-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json.gz"
    path.write_bytes(gzip.compress(json.dumps(rows, default=str).encode("utf-8")))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", type=int, required=True, help="how many of the newest runs to keep")
    parser.add_argument("--yes", action="store_true", help="delete (without it, only list)")
    args = parser.parse_args()

    with connection() as conn:
        runs = conn.execute("select r.id, r.status, r.created_at, c.name from runs r join clients c on c.id = r.client_id "
                            "order by r.created_at desc").fetchall()
    doomed = runs[args.keep:]
    for run in runs[:args.keep]:
        print(f"keep    {run['id']}  {run['created_at']:%d %b %H:%M}  {run['name']}")
    print(f"{len(doomed)} run(s) to delete")
    if not args.yes or not doomed:
        return

    print(f"backup  {backup([str(r['id']) for r in doomed]).relative_to(ROOT)}")
    blobs = make_blob_store(get_settings())
    deleted = sum(delete_run(str(run["id"]), blobs) for run in doomed)
    print(f"deleted {deleted} of {len(doomed)} (a run still in progress is skipped)")


if __name__ == "__main__":
    main()
