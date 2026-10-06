# Initial verification — 2026-10-06

## Python suite

Python 3.14 on macOS: 43 automated unit tests passed; one opt-in FileMaker test
is skipped in the ordinary suite. The tests cover requirement #135, URL repair,
override precedence, Unicode and reserved characters, frontmatter, input files,
stdin, process errors and preview behavior. Deprecation warnings are treated as
errors in the suite.

## Live FileMaker test

The opt-in integration test passed against the open `fmIDE` database through
`fmp26`. The returned JSON was:

```json
{
  "file": "fmIDE",
  "text": "Malmö 🦄 + & = % / done",
  "variable": "last = + & 🦄",
  "version": "0.90"
}
```

This verifies actual action execution, existing/new frontmatter together,
duplicate-variable replacement, URL repair and exact text transport.
The result was written only to a temporary scratch file.

The Name that Thing `layout_name` parameter was also tested by navigating to
`fmIDE Examples` and back to the original `fmIDE Tests` layout. The resulting
FileMaker layouts were visually verified; no blocking dialog appeared.

## Frontmost-file discovery limitation

The real macOS discovery call was attempted. FileMaker rejected the read of its
windows with `A privilege violation occurred`. Automatic targeting could not be
verified in this file's current permission configuration. The CLI reports an
actionable error and accepts `-file fmIDE`. No FileMaker privileges were changed.
[Claris documents the fmextscriptaccess requirement](https://help.claris.com/en/pro-help/content/scripting-apple-events.html).

Successful frontmost discovery is covered with a mocked operating-system
response; that is not a claim of successful live discovery. Windows dispatch is
implemented but was not tested against a live Windows FileMaker installation.

## Packaging and hosted CI

The v0.1.0 source distribution and wheel built successfully. The wheel was
installed in an isolated environment outside the checkout; both `fmide` and
`fmIDE` passed their version/preview checks. Every Python module in the wheel
was compared byte-for-byte with the published source.

[All six CI jobs passed](https://github.com/fmIDE/fmIDE-CLI/actions/runs/37423179097):
Python 3.10 and 3.14 on Linux, macOS and Windows, including package builds and
installation checks. These do not require a FileMaker installation.

The documented Homebrew tap and `brew install --build-from-source fmide/cli/fmide`
succeeded on macOS. The installed code in Homebrew's `libexec` passed the live
FileMaker integration test again, returning the exact JSON shown above.

Homebrew's normal `brew test` wrapper stopped at its dependency-version check:
it reported several installed dependencies as missing. Homebrew had installed
Python 3.14.5, while its general formula metadata described 3.14.8. No further
system-wide dependency upgrades were performed for that check. The formula's
actual `test do` block was invoked through Homebrew's Ruby `Formula#run_test`
against the installed package; all three command assertions passed. This is
separate from a successful run of the normal `brew test` wrapper.
