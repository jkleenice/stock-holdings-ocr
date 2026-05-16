from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extractor import extract_from_image
from .reporter import build_report, render_markdown
from .schemas import HoldingsSnapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdings-ocr")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract", help="Extract holdings from an image into a snapshot JSON.")
    ex.add_argument("image", type=Path)
    ex.add_argument("-o", "--output", type=Path, help="Write snapshot JSON here (else stdout).")

    rp = sub.add_parser("report", help="Render an aggregated report from a snapshot JSON.")
    rp.add_argument("snapshot", type=Path)
    rp.add_argument("--format", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args(argv)

    if args.cmd == "extract":
        snapshot = extract_from_image(args.image)
        data = snapshot.model_dump_json(indent=2)
        if args.output:
            args.output.write_text(data)
        else:
            print(data)
        return 0

    if args.cmd == "report":
        snapshot = HoldingsSnapshot.model_validate_json(args.snapshot.read_text())
        try:
            report = build_report(snapshot)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.format == "json":
            print(report.model_dump_json(indent=2))
        else:
            print(render_markdown(report))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
