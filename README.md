# fmIDE CLI

Call [fmIDE](https://github.com/fmIDE/fmIDE) in FileMaker Pro from your terminal.
Build, repair, preview and open FMP URLs for the **Name that Thing API** and
**fmIDE action scripts**. Implements [fmIDE: CLI #135](https://github.com/fmIDE/fmIDE/issues/135).

## Install with Homebrew

```sh
brew tap fmide/cli https://github.com/fmIDE/fmIDE-CLI.git
brew install fmide/cli/fmide
fmide --version
```

This repository is also its own Homebrew tap; the explicit URL is necessary
because its name does not start with `homebrew-`. The formula installs Python
and the command. FileMaker Pro and the fmIDE script are installed separately.
Both `fmide` and `fmIDE` work (on case-sensitive filesystems an alias is installed).
Homebrew installation targets macOS.

Alternatively, with Python 3.10 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/fmide --help
```

There are no third-party Python runtime dependencies. From a checkout you can
also run `./fmide` or `python3 -m fmide_cli` without installing anything.
Windows supports explicit-file URL dispatch; Linux supports URL previews.

## Quick start

Open your database in FileMaker. It must contain the `fmIDE` script and your
account must have the `fmurlscript` extended privilege.

```sh
# Preview a Name that Thing URL without running it.
fmide -file fmIDE '-$' 'layout_name=fmIDE Examples' --dry-run

# Navigate to a script using FileMaker 26.
fmide -fmp fmp26 -file fmIDE '-$' 'script_name=fmIDE'

# Use the frontmost file in the selected FileMaker version (macOS).
fmide -fmp fmp26 '-$' 'layout_name=fmIDE Examples'

# Run an inline action script, or a UTF-8 file, or stdin.
fmide -file fmIDE '[+].Go to Layout = "fmIDE Examples"'
fmide -file fmIDE --parameter-file actions.fmJAML
cat actions.fmJAML | fmide -file fmIDE -

# Add FileMaker Let assignments as frontmatter.
fmide -file fmIDE -frontmatter '$greeting = "Hello"' \
  '[+].Exit Script = == $greeting'

# Repair a mangled link and replace its target and variables.
fmide -url 'https://fmp19//$/Old?script=fmIDE&$layout_name=Old' \
  -fmp fmp26 -file fmIDE '-$' 'layout_name=fmIDE Examples'
```

Quote URLs and `$` expressions with **single quotes** in POSIX shells. The long
alias `--variable` is equivalent to `-$`. Put `--` before an inline parameter
beginning with `-`, including an existing `---` frontmatter block.

**Exit status 0 means the operating system accepted the URL.** FileMaker runs
asynchronously; the CLI does not return a script result or claim that the action
succeeded. Check FileMaker for dialogs. `--dry-run` prints the complete URL and
never opens it; specifying `-file` also avoids querying FileMaker during preview.

## Reference and development

- [Options, precedence and URL repair](docs/cli.md)
- [Tests, live verification and releases](docs/development.md)
- [Initial verification results](docs/verification.md)

```sh
python3 -m unittest discover -v
```

The live integration test is opt-in. The ordinary suite never opens FileMaker.

## License

[MIT](LICENSE).
