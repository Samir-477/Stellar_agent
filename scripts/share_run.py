"""Build the share bundle for a run and create a share link.

Usage:
  python scripts/share_run.py --run <run_id> [--include-proposed] [--days 30]
--include-proposed makes an internal preview with patches not yet approved.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.core.blobstore import make_blob_store  # noqa: E402
from engine.core.config import get_settings  # noqa: E402
from engine.output.bundle import build_share_bundle  # noqa: E402
from engine.output.share import create_share  # noqa: E402
from engine.store import PostgresStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--include-proposed", action="store_true")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    settings = get_settings()
    bundle = build_share_bundle(args.run, PostgresStore(), make_blob_store(settings),
                                include_proposed=args.include_proposed)
    token = create_share(args.run, bundle["prefix"], days=args.days, created_by="cli")
    for page in bundle["manifest"]["pages"]:
        placed = sum(c["placed"] for c in page["changes"])
        print(f"{page['url']}: {placed}/{len(page['changes'])} changes placed; "
              f"{len(page['under_the_hood'])} under the hood; not placed: {page['not_placed']}")
    print(f"site-file changes: {len(bundle['manifest']['site_files'])}")
    print(f"share link: {settings.app_base_url}/r/{token}")


if __name__ == "__main__":
    main()
