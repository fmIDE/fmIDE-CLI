# fmIDE CLI

Call [fmIDE](https://github.com/fmIDE/fmIDE) in FileMaker Pro from your terminal:

1. **[Show](#1-show)** — call the fmIDE **Name that Thing API** to show something in your solution.
2. **[Act](#2-act)** — run an **fmIDE Action Script (fmIDEAS)**.
3. **[Link](#3-link)** — open an FMP URL, repairing a mangled link when necessary.
4. **[Modify link](#4-modify-link)** — adapt an existing link to another FileMaker client, server or file, or add parameters and frontmatter.

Implements [fmIDE: CLI #135](https://github.com/fmIDE/fmIDE/issues/135).

## Install with Homebrew

```sh
brew tap fmide/cli https://github.com/fmIDE/fmIDE-CLI.git
brew install fmide/cli/fmide
```

Both `fmide` and `fmIDE` work. FileMaker Pro and the fmIDE script are installed
separately. See [installation details](#installation-details) for Python
requirements and alternatives to Homebrew.

## Before you start

For **Show** and **Act**, open your database in FileMaker. It must contain the
`fmIDE` script and your account must have the `fmurlscript` extended privilege.
The examples below target the `fmIDE` demo file; replace `-file fmIDE` with your
own database name when working in another solution.

Quote URLs and `$` expressions with **single quotes** in POSIX shells.
The `-$` option itself needs no quotes in zsh or bash; keep its assignment value quoted.
`--variable` is a long alias for `-$`.

## 1. Show

Name a thing in your solution and let fmIDE take you to it. Pass each
**Name that Thing** parameter with `-$`; no URL is needed.

```sh
# Show a layout.
fmide -file fmIDE -$ 'layout_name=fmIDE Examples'

# Show the fmIDE script at step 5.
fmide -file fmIDE -$ 'script_name=fmIDE' -$ 'script_step_number=5'

# Build a Name that Thing call manually from an FMP URL.
fmide -url 'fmp26://$/MyFile' -$ 'script_name=Hello' -$ 'script_step_number=4'
```

When the URL does not already have a `script` parameter, the CLI adds
`?script=fmIDE`. It also encodes the `-$` parameters for you, so names and values
can be entered directly without manually URL-encoding them.

Add `-fmp fmp26` to choose FileMaker 26. On macOS, you can omit `-file` to use
the frontmost database in the selected FileMaker client, when its permissions
allow discovery. See [choosing the target](docs/cli.md#choosing-the-target).

## 2. Act

Pass an **fmIDEAS** to execute FileMaker development actions. Supply its text
inline, read it from a UTF-8 file, or pipe it into the command.

```sh
# Run an inline action script.
fmide -file fmIDE '[+].Go to Layout = "fmIDE Examples"'

# Run an action script saved in a file.
fmide -file fmIDE --parameter-file actions.fmJAML

# Run an action script from stdin.
cat actions.fmJAML | fmide -file fmIDE -
```

Use `-frontmatter` to supply FileMaker variable assignments to an action script.
See [Act in the command guide](docs/cli.md#2-act) for an example and details of
frontmatter merging.

### Agent loop: run an fmIDEAS and return its result

An agent can ask fmIDE to write the result of an asynchronous action to a file
that it monitors. The fmIDEAS stays the same as it would be for a normal call
from inside FileMaker; the result destination is supplied through frontmatter.

For example, this runs an action in `MyFile` using FileMaker 26 and writes the
current timestamp to the user's Desktop:

```sh
fmide -fmp fmp26 -file MyFile \
  -frontmatter '$fmide_on_exit_script_write_data_to_file_path = Get ( DesktopPath ) & "script_result.txt"' \
  '[+].Exit Script = == Get ( CurrentTimestamp )'
```

The agent can monitor `script_result.txt` and read the value after FileMaker
has run the action. Add the debugger variable when diagnosing an action:

```sh
fmide -fmp fmp26 -file MyFile \
  -frontmatter '$fmide_debugger = 1; $fmide_on_exit_script_write_data_to_file_path = Get ( DesktopPath ) & "script_result.txt"' \
  '[+].Exit Script = == Get ( CurrentTimestamp )'
```

To collect the result and error details together, point fmIDE at a folder:

```sh
fmide -fmp fmp26 -file MyFile \
  -frontmatter '$fmide_on_exit_script_write_data_to_folder_path = Get ( DesktopPath ) & "fmIDE_results/"' \
  '[+].Exit Script = == Get ( CurrentTimestamp )'
```

The folder form writes `script_result.txt`, `last_error.txt`,
`last_error_detail.txt`, `last_error_location.txt` and
`last_error_description.txt`. FileMaker creates these before `Exit Script`
returns. Replace `MyFile` with another open or hosted file; use `-server HOST`
when the file should be opened from a server instead of through `$` (the
currently open file).

This closes the agent loop:

```text
AI agent → fmide CLI → FMP URL → fmIDE script → fmIDEAS → result file → AI agent
```

## 3. Link

Open an existing FMP URL with `-url`. Supported mangled prefixes are repaired
automatically, so a copied link can be used directly.

```sh
# Open an FMP link.
fmide -url 'fmp26://$/fmIDE?script=fmIDE&$layout_name=fmIDE Examples'

# Open the same link after its protocol was mangled.
fmide -url 'https://fmp26//$/fmIDE?script=fmIDE&$layout_name=fmIDE Examples'
```

Short **thingamajig URIs** also work, such as
`fmide -url 'fmIDE&$script_name=fmIDE'`.
See [Link in the command guide](docs/cli.md#3-link) for supported repairs.

## 4. Modify link

Combine `-url` with options when you want to adapt a link. Only the specified
parts change; for example, choose another FileMaker client, open the file from
a server, or add frontmatter to the linked action script.

```sh
# Use FileMaker 26 for a link that names another client version.
fmide -url 'fmp19://$/fmIDE?script=fmIDE&$script_name=fmIDE' -fmp fmp26

# Open the linked file from your server instead of an already-open local file.
# Replace fm.example.com with your FileMaker Server address.
fmide -url 'fmp://$/MySolution?script=fmIDE' -server fm.example.com

# Supply a variable to the action script carried in a link.
fmide -url 'fmp://$/fmIDE?script=fmIDE&param=%5B%2B%5D.Exit%20Script%20%3D%20%3D%3D%20%24greeting' \
  -frontmatter '$greeting = "Hello"'
```

You can also change the file or port, replace Name that Thing parameters, or
replace the script parameter. See [Modify link in the command guide](docs/cli.md#4-modify-link)
for examples and precedence rules.

## Preview and results

Add `--dry-run` to any of the four use cases to print the resulting URL without
running it. Supplying `-file` also avoids querying FileMaker during preview.

```sh
fmide -file fmIDE -$ 'layout_name=fmIDE Examples' --dry-run
```

**Exit status 0 means the URL was printed or accepted by the operating system.**
FileMaker runs asynchronously. The CLI does not return a script result or
confirm that an action succeeded; check FileMaker for results and dialogs.

## Installation details

This repository is also its own Homebrew tap; the explicit tap URL is necessary
because its name does not start with `homebrew-`. Homebrew installation targets
macOS. On case-sensitive filesystems, an alias provides the `fmIDE` spelling.
Windows supports explicit-file URL dispatch; Linux supports URL previews.

The CLI uses only Python's standard library: it needs **Python 3.10+**, but no
additional Python packages from pip. With a compatible Python already installed,
you can run `./fmide` or `python3 -m fmide_cli` from a checkout, or install it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/fmide --help
```

The **Homebrew formula depends on `python@3.14`**. Homebrew may install or upgrade
Python and its native dependencies: certificate and TLS libraries, decimal
arithmetic, SQLite, command-line editing and compression libraries. These belong
to the full Python runtime and its dependency chain; the CLI does not directly
use most of their features. The exact list depends on Homebrew's Python build.
See [Homebrew's Python formula](https://formulae.brew.sh/formula/python@3.14).

## Reference and development

- [Show, Act, Link and Modify link: command guide and options](docs/cli.md)
- [Tests, live verification and releases](docs/development.md)
- [Initial verification results](docs/verification.md)

```sh
python3 -m unittest discover -v
```

The live integration test is opt-in. The ordinary suite never opens FileMaker.

## Local HTTPS forwarding

Run separately configured localhost forwarding servers for different FileMaker
versions or databases:

```sh
fmide server add start -tag new
fmide server add start -tag old -fmp fmp19
fmide server list
curl -k --get 'https://localhost:43103/' --data-urlencode '-file=fmIDE' --data-urlencode '$layout_name=fmIDE Actions'
fmide server old tail
fmide server all terminate
```

New servers use HTTPS by default and have a stable index, a unique optional tag,
saved target overrides and their own log. The default port is `43103 + index`.
The first start creates a self-signed localhost certificate; follow the guide to
configure a browser-trusted certificate for warning-free links.
Identify servers by index, tag, saved port, or `all`. See the
[forwarding server guide](docs/servers.md) for lifecycle commands, URL encoding,
certificates, configuration and logging.

Version 0.3.0 accepts both native FMP query parameters and CLI-style options:

```text
https://localhost:43103/?-file=MyFile&$layout_name=Home&$fmide_debugger=1
https://localhost:43103/?-file=MyFile&-$=layout_name=Home
```

Use `-url` for an embedded FMP URL; the original `url` spelling remains supported.
Saved target overrides take priority over request options. Requests do not change
settings. After upgrading, stop and start existing workers to load the new code.

The CLI dispatches HTTPS inputs through the same FMP URL builder and OS dispatcher
as immediate commands. Forwarding servers currently require macOS or Linux;
FileMaker dispatch requires macOS. Forwarding servers are included in Homebrew version 0.2.0 and later.
Upgrade an existing installation with `brew update && brew upgrade fmide/cli/fmide`.

## License

[MIT](LICENSE).
