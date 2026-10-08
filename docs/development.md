# Development and verification

Python 3.10+ and its standard library are sufficient to run the code and tests.

```sh
python3 -m unittest discover -v
python3 -W error::DeprecationWarning -m unittest discover -q
./fmide -file fmIDE --dry-run
```

CI runs unit tests on Linux, macOS and Windows with Python 3.10 and 3.14,
and checks wheel installation and both command names. The live test is skipped
unless explicitly enabled.

## Live FileMaker integration test

Open the intended `fmIDE.fmp12` database in FileMaker Pro, with fmIDE available
and no unsaved-script or modal dialog. Then:

```sh
FMIDE_LIVE_FILE=fmIDE FMIDE_LIVE_PROTOCOL=fmp26 \
  python3 -m unittest tests.test_live -v
```

The test verifies **Act** by running an fmIDEAS that writes the database name,
fmIDE version, merged text and a variable into a unique temporary JSON file.
Assertions validate those contents, proving execution rather than only OS
dispatch. The same test also exercises **Link** and **Modify link** by supplying
a mangled URL, replacing its protocol/file and duplicate variables, and
prepending frontmatter to an existing block. **Show** navigation was verified
separately in the [initial live verification](verification.md).
It does not edit database records, layouts, scripts or schema. It requires
fmIDE's native data-file actions and FileMaker's ConvertToFileMakerPath function.
The temporary directory is removed after the test. Inspect FileMaker if it
times out; resolve the dialog before trying again.

To check frontmost targeting without executing a script:

```sh
fmide -fmp fmp26 --dry-run
```

## Packaging

```sh
python3 -m venv .venv
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

The distribution exposes `fmide` and `fmIDE`. On case-insensitive systems the
names refer to the same command. Homebrew installs the standard-library-only
package into `libexec`, pins its interpreter to the declared Python dependency,
and links the commands into `bin`; no global pip install is needed.

## Releasing

1. Update `__version__`, `pyproject.toml`, documentation and tests.
2. Run the ordinary suite and opt-in live suite; review the changes.
3. Commit and create the matching `vX.Y.Z` Git tag, then push it.
4. Download the tag archive from GitHub and calculate its SHA-256.
5. Update `Formula/fmide.rb` with that tag URL and checksum in a subsequent commit.
   Keeping the formula update outside the tagged source avoids a checksum cycle.
6. Test `brew install --build-from-source fmide/cli/fmide` and `brew test fmide/cli/fmide`.
7. Publish the GitHub release and the tested formula update.

Keep release tags immutable. A new code change needs a new version/tag/checksum.
The formula's tests only use previews and do not require FileMaker on the build
machine. The formula is hosted here using an explicit tap URL; a second
`homebrew-*` repository is not required.

## Forwarding server verification

The ordinary suite exercises real HTTP listeners with an injected dispatcher,
and separate background CLI processes with isolated `FMIDE_SERVER_HOME` folders.
It covers lookup by index/tag/port, holes and reset, concurrent allocation, saved
overrides, log redaction and tailing, authenticated control, graceful and forced
shutdown, port conflicts, and rollback after a failed port change. These tests
never open FileMaker. Background-process tests run on POSIX; HTTP forwarding
and existing immediate-command tests also run on Windows.
