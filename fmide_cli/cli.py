"""CLI compatible with fmIDE/fmIDE issue #135."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import __version__
from .system import open_url
from .urls import InputError, Options, build_url


_LATEST_RELEASE_URL = "https://api.github.com/repos/fmIDE/fmIDE-CLI/releases/latest"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="fmide", allow_abbrev=False,
        description="Call fmIDE using a FileMaker URL. Specify the target database with -file or in -url.",
        epilog="Use fmide server --help for localhost HTTP(S) forwarding, fmide update to check or update this installation, or fmide brew upgrade for Homebrew. Quote URLs, variable assignments and FileMaker calculations to protect them from your shell. "
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


def brew_upgrade() -> int:
    executable = shutil.which('brew')
    if executable is None:
        print("fmide brew upgrade: Homebrew's 'brew' command was not found on PATH.", file=sys.stderr)
        return 1
    print('fmide: running brew upgrade fmide/cli/fmide')
    try:
        result = subprocess.run([executable, 'upgrade', 'fmide/cli/fmide'], check=False)
    except OSError as exc:
        print(f'fmide brew upgrade: could not run Homebrew: {exc}', file=sys.stderr)
        return 1
    if result.returncode == 0:
        print('fmide: Homebrew upgrade finished; check the installed version with fmide --version.')
    return result.returncode


def is_homebrew_install() -> bool:
    """Identify the active CLI code inside a Homebrew formula keg."""
    parts = Path(__file__).resolve().parts
    return any(
        parts[index] == "Cellar"
        and parts[index + 1] == "fmide"
        and parts[index + 3] == "libexec"
        for index in range(max(0, len(parts) - 3))
    )


def latest_release_version() -> str:
    request = Request(
        _LATEST_RELEASE_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "fmIDE-CLI"},
    )
    with urlopen(request, timeout=5) as response:
        release = json.load(response)
    if not isinstance(release, dict):
        raise ValueError("GitHub returned an invalid release response")
    tag = release.get("tag_name", "")
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", tag):
        raise ValueError("GitHub returned an invalid release version")
    return tag.removeprefix("v")


def update() -> int:
    if is_homebrew_install():
        print("fmide update: this copy is managed by Homebrew.")
        return brew_upgrade()

    print(f"fmide update: this copy is not managed by Homebrew (installed version {__version__}).")
    try:
        latest = latest_release_version()
    except (OSError, URLError, TimeoutError, ValueError, TypeError, AttributeError) as exc:
        print(f"Could not check the latest GitHub release: {exc}")
        print("Check https://github.com/fmIDE/fmIDE-CLI/releases for the latest version.")
        print("Update this copy using the same method you used to install it.")
        return 0

    if tuple(map(int, latest.split("."))) <= tuple(map(int, __version__.split("."))):
        print(f"You already have the latest release (v{__version__}).")
        return 0

    print(f"The latest stable release is v{latest}.")
    print("Update this copy using the same method you used to install it.")
    print("For a Homebrew-managed installation, run: fmide brew upgrade")
    print("For a source checkout, pull the release and reinstall it in your environment:")
    print("  git pull --ff-only")
    print("  .venv/bin/python -m pip install .")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "server":
        from .servers import main as server_main
        return server_main(argv[1:])
    if argv and argv[0] == 'brew':
        if argv[1:] == ['--help'] or not argv[1:]:
            print('usage: fmide brew upgrade\n\nUpgrade the fmIDE CLI installed by Homebrew.')
            return 0
        if argv[1:] == ['upgrade']:
            return brew_upgrade()
        print('usage: fmide brew upgrade', file=sys.stderr)
        return 2
    if argv and argv[0] == 'update':
        if argv[1:] in (['--help'], ['-h']):
            print("usage: fmide update\n\nUpgrade this copy through Homebrew, or check the latest release and show installation guidance.")
            return 0
        if argv[1:]:
            print('usage: fmide update', file=sys.stderr)
            return 2
        return update()
    cli = parser()
    if not argv:
        cli.print_help()
        return 0
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
        url = build_url(options)
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
