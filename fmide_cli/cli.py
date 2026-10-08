"""CLI compatible with fmIDE/fmIDE issue #135."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .system import frontmost_file, open_url
from .urls import InputError, Options, build_url


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="fmide", allow_abbrev=False,
        description="Call fmIDE using a FileMaker URL. Omit -file to use the frontmost file on macOS.",
        epilog="Use fmide server --help for localhost HTTP forwarding. Quote URLs, '$' options and FileMaker calculations to protect them from your shell. "
               "Use -- before a script parameter starting with '-'. "
               "A successful exit means the URL was dispatched, not that the FileMaker script finished.",
    )
    for name, help_text in (
        ("fmp", "FMP protocol/version, e.g. fmp26 or 26 (default: fmp)"),
        ("server", "host, IP address, $ (open file) or ~ (Documents); default: $"),
        ("file", "FileMaker database name, with or without .fmp12"),
        ("url", "FMP URL or thingamajig URI to repair and open"),
    ):
        result.add_argument("-" + name, "--" + name, help=help_text)
    result.add_argument("-port", "--port", type=int, help="override the server port (1–65535)")
    result.add_argument("-$", "--variable", action="append", default=[], dest="variables", metavar="NAME=VALUE",
                        help="add/replace a Name that Thing variable; repeatable")
    result.add_argument("-frontmatter", "--frontmatter", action="append", default=[], metavar="ASSIGNMENTS",
                        help="prepend FileMaker Let assignments to frontmatter; repeatable")
    result.add_argument("--parameter-file", metavar="PATH", help="read UTF-8 script parameter from a file; - reads stdin")
    result.add_argument("--dry-run", "--print-url", action="store_true", help="print the URL without opening it")
    result.add_argument("--version", action="version", version="fmIDE CLI " + __version__)
    result.add_argument("parameter", nargs="?", help="script parameter; overrides param in -url; - reads stdin")
    return result


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "server":
        from .servers import main as server_main
        return server_main(argv[1:])
    cli = parser()
    args = cli.parse_args(argv)
    if args.parameter_file is not None and args.parameter is not None:
        cli.error("use either a script parameter or --parameter-file, not both")
    try:
        parameter = args.parameter
        if args.parameter_file is not None:
            parameter = (sys.stdin.read() if args.parameter_file == "-"
                         else Path(args.parameter_file).read_text(encoding="utf-8-sig"))
        elif parameter == "-":
            parameter = sys.stdin.read()
        options = Options(
            url=args.url, fmp=args.fmp, server=args.server, port=args.port,
            file=args.file, variables=args.variables, frontmatter=args.frontmatter, parameter=parameter,
        )
        url = build_url(options, resolve_file=frontmost_file)
        if args.dry_run:
            print(url)
        else:
            open_url(url)
        return 0
    except (InputError, OSError, UnicodeError, ValueError) as exc:
        print(f"fmide: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
