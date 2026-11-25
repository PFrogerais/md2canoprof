"""Command line entry points: md2canoprof, scar2md, canoprof-check."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def _parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _report(warnings: list[str], skipped: list[str] = ()) -> None:
    for message in warnings:
        print(f"warning: {message}", file=sys.stderr)
    for message in skipped:
        print(f"skipped: {message}", file=sys.stderr)


def md2canoprof(argv: list[str] | None = None) -> int:
    from .markdown_to_scar import convert_file

    parser = _parser("md2canoprof", "Convert Markdown files into Canoprof archives (.scar).")
    parser.add_argument("markdown", type=Path, nargs="+", help="source Markdown file(s)")
    parser.add_argument("-o", "--output", type=Path,
                        help="output .scar (single input) or folder (several inputs)")
    args = parser.parse_args(argv)

    status = 0
    for source in args.markdown:
        if not source.is_file():
            print(f"error: {source} not found", file=sys.stderr)
            status = 1
            continue
        output = args.output
        if output is not None and (len(args.markdown) > 1 or output.is_dir()):
            output.mkdir(parents=True, exist_ok=True)
            output = output / f"{source.stem}.scar"
        written, conv, title = convert_file(source, output)
        _report([f"{source}: {w}" for w in conv.warnings])
        print(f"{written}: '{title}' ({len(conv.resources)} embedded resource(s))")
    return status


def scar2md(argv: list[str] | None = None) -> int:
    from .scar_to_markdown import convert_archive

    parser = _parser("scar2md", "Convert a Canoprof export (.scar) into Markdown files.")
    parser.add_argument("scar", type=Path, help="Canoprof export (.scar)")
    parser.add_argument("-o", "--output", type=Path, default=Path("docs"),
                        help="output folder (default: docs)")
    parser.add_argument("--force", action="store_true", help="overwrite existing .md files")
    args = parser.parse_args(argv)

    if not args.scar.is_file():
        print(f"error: {args.scar} not found", file=sys.stderr)
        return 1
    conv = convert_archive(args.scar, args.output, force=args.force)
    _report(conv.warnings, conv.skipped)
    print(f"{len(conv.written)} Markdown file(s) written to {args.output}, "
          f"{len(conv.copied)} resource(s) copied, {len(conv.skipped)} item(s) skipped")
    return 0


def canoprof_check(argv: list[str] | None = None) -> int:
    from . import structure

    parser = _parser("canoprof-check",
                     "Check that generated .scar files only use nestings Canoprof knows.")
    parser.add_argument("scar", type=Path, nargs="+", help="archive(s) to check")
    parser.add_argument("--learn", type=Path, metavar="KNOWN_FILE",
                        help="instead of checking, write the nestings found in the given "
                             "Canoprof export(s) to KNOWN_FILE")
    args = parser.parse_args(argv)

    if args.learn:
        pairs: set = set()
        for archive in args.scar:
            pairs |= structure.learn(archive)
        structure.save_known(pairs, args.learn)
        print(f"{len(pairs)} nesting(s) written to {args.learn}")
        return 0

    known = structure.load_known()
    status = 0
    for archive in args.scar:
        unknown = structure.unknown_nestings(archive, known)
        for parent, child in sorted(unknown):
            print(f"{archive}: unknown nesting {parent} > {child}")
        status |= bool(unknown)
    if not status:
        print(f"OK: {len(args.scar)} archive(s) only use known nestings")
    return status
