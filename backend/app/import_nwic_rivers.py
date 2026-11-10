import argparse
import json
from pathlib import Path

from app.services.nwic_river_import import import_nwic_kml
from app.services.nwic_snapshot_review import abandon_snapshot, compare_snapshots, snapshot_history, stage_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a locally supplied NWIC river-network KML.")
    parser.add_argument("path", type=Path, nargs="?")
    parser.add_argument("--source-version", help="Operator-recorded source dataset version or date")
    parser.add_argument("--max-features", type=int, help="Stop after this many additional records")
    parser.add_argument("--stage-review", action="store_true", help="Stage a snapshot without changing the explorer")
    parser.add_argument("--compare", nargs=2, metavar=("OLD_SHA256", "NEW_SHA256"), help="Compare two staged snapshots")
    parser.add_argument("--abandon", metavar="SHA256", help="Retain but stop blocking on an incomplete snapshot")
    parser.add_argument("--history", action="store_true", help="Show staged snapshot history")
    parser.add_argument("--offset", type=int, default=0, help="Comparison result offset")
    parser.add_argument("--limit", type=int, default=100, help="Comparison page size")
    args = parser.parse_args()
    if args.history:
        print(json.dumps(snapshot_history(offset=args.offset, limit=args.limit)))
    elif args.abandon:
        abandon_snapshot(args.abandon)
        print(json.dumps({"sha256": args.abandon, "status": "abandoned"}))
    elif args.compare:
        print(json.dumps(compare_snapshots(*args.compare, offset=args.offset, limit=args.limit)))
    else:
        if args.path is None or not args.source_version:
            parser.error("path and --source-version are required for imports")
        importer = stage_snapshot if args.stage_review else import_nwic_kml
        print(json.dumps(importer(args.path, args.source_version, max_features=args.max_features)))


if __name__ == "__main__":
    main()
