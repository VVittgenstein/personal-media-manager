from __future__ import annotations

import argparse
import logging
import signal
import sys

from .inventory import scan_inventory, write_inventory_json


def main(argv: list[str] | None = None) -> int:
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="Scan MediaRoot inventory (safe sandbox).")
    parser.add_argument("--media-root", required=True, help="Absolute path to MediaRoot directory.")
    parser.add_argument(
        "--output",
        default="-",
        help="Output JSON path, or '-' for stdout (default: stdout).",
    )
    parser.add_argument(
        "--include-trash",
        action="store_true",
        help="Include MediaRoot/_trash in scan (default: skipped).",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help="Python logging level (default: WARNING).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))

    result = scan_inventory(args.media_root, skip_trash=not args.include_trash)
    write_inventory_json(result, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
