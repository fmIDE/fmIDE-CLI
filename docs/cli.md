# Show, Act, Link and Modify link

Choose the command form that matches what you want to do:

| Use case | Command form |
| --- | --- |
| **Show** a thing in your solution | `fmide -file FILE -$ 'NAME=VALUE'` |
| **Act** by running an fmIDEAS | `fmide -file FILE 'SCRIPT-PARAMETER'` |
| **Link** to an existing FMP URL | `fmide -url 'URL'` |
| **Modify link** for a different target or input | `fmide -url 'URL' [MODIFIERS]` |

For Show and Act, the target database must contain the `fmIDE` script and allow
URL script execution through the `fmurlscript` extended privilege. The examples
use the `fmIDE` demo database. Quote `$` expressions and URLs with single quotes
in POSIX shells. The `-$` option itself needs no quotes in zsh or bash. A target
database must be supplied with `-file` or included in the `-url`; the CLI never
tries to discover an open FileMaker database. Running `fmide` with no arguments
prints usage.

## 1. Show

Call the fmIDE **Name that Thing API** by supplying parameters that identify
the object you want to show. The CLI constructs the call to fmIDE for you.

```sh
fmide -file fmIDE -$ 'layout_name=fmIDE Examples'
fmide -file fmIDE -$ 'script_name=fmIDE' -$ 'script_step_number=5'

# Supply Name that Thing parameters alongside a manually chosen FMP URL.
fmide -url 'fmp26://$/MyFile' -$ 'script_name=Hello' -$ 'script_step_number=4'
```

If the URL has no `script` parameter, the CLI adds `?script=fmIDE`. It appends
and URL-encodes the `-$` parameters, so you can type their names and values
directly instead of encoding them yourself.

Each `-$ NAME=VALUE` supplies a local variable to fmIDE. `--variable` is an
alias for `-$`, and an optional leading `$` on NAME is accepted. Repeat the
option to name more aspects of the thing. Values may be empty or contain `=`.
If the same name is supplied more than once, the last value wins; name matching
is case-insensitive, as in FileMaker.

See the [Name that Thing API parameters](https://github.com/fmIDE/fmIDE/wiki/fmIDE-'Name-that-Thing'-API-Parameters)
for the objects and parameters supported by your fmIDE version.

## 2. Act

Run an **fmIDE Action Script (fmIDEAS)** by passing its text as the script
parameter. The CLI sends it to the `fmIDE` script in the chosen database.

```sh
# Inline fmIDEAS.
fmide -file fmIDE '[+].Go to Layout = "fmIDE Examples"'

# A saved UTF-8 action script (an optional BOM is accepted).
fmide -file fmIDE --parameter-file actions.fmJAML

# An action script supplied through stdin.
cat actions.fmJAML | fmide -file fmIDE -
```

`--parameter-file -` also reads stdin. A parameter file and an inline parameter
are mutually exclusive. Put `--` before an inline parameter beginning with `-`,
including one that starts with a `---` frontmatter block.

### Supply variables with frontmatter

Use `-frontmatter` to supply FileMaker `Let` variable assignments before the
actions run. This works directly with an fmIDEAS; it does not require a URL.

```sh
fmide -file fmIDE -frontmatter '$greeting = "Hello"' \
  '[+].Exit Script = == $greeting'
```

The example returns a value within FileMaker; the CLI does not print the
FileMaker script result. See [preview and results](#preview-and-results).

Frontmatter is FileMaker calculation syntax, not YAML. The CLI does not evaluate
it. It normalizes script CRLF/LF line endings to FileMaker CR line endings,
adds a `---` block if absent, or inserts assignments at the beginning of an
existing block. Semicolon separators are inserted between added blocks and
existing assignments, on separate lines to accommodate trailing `//` comments.
An unterminated existing block is rejected when adding frontmatter.

An existing assignment appears after newly prepended assignments: FileMaker
therefore evaluates it later. This is prepend semantics, not an override of
existing variables. Empty `-frontmatter` strings have no effect.

## 3. Link

Open a supplied FMP URL using `-url`. Known mangled protocol prefixes are
repaired automatically; no extra modifier is needed just to follow the link.

```sh
fmide -url 'fmp26://$/fmIDE?script=fmIDE&$layout_name=fmIDE Examples'
fmide -url 'https://fmp26//$/fmIDE?script=fmIDE&$layout_name=fmIDE Examples'
```

An existing nonempty `script` parameter is preserved, so a link can call a
script other than fmIDE. If no script is specified, the CLI adds `script=fmIDE`.
URL script execution requires the corresponding FileMaker privileges.

Short **thingamajig URIs** are expanded into full FMP URLs:

```sh
fmide -url 'fmIDE&$script_name=fmIDE'
```

### Supported repairs and short forms

| Input | Canonical target |
| --- | --- |
| `fmp26://$/DB` | `fmp26://$/DB` |
| `fmp26:/$/DB` | `fmp26://$/DB` |
| `fmp26//$/DB` | `fmp26://$/DB` |
| `https://fmp26//$/DB` | `fmp26://$/DB` |
| `http://fmp26://$/DB` | `fmp26://$/DB` |
| `fmp26%3A%2F%2F$/DB` | `fmp26://$/DB` |
| `DB&$script_name=Hello` | `fmp://$/DB?script=fmIDE&$script_name=Hello` |
| `host/DB&$script_name=Hello` | `fmp://host/DB?script=fmIDE&$script_name=Hello` |
| `fmp19/host/DB` | `fmp19://host/DB` |
| `fmp19//DB` | `fmp19://$/DB` |

Only known prefix repairs are performed. Unrelated HTTP, file, or JavaScript
URLs are rejected. URL fragments are rejected: encode literal `#` as `%23` in
an input URL. Existing encoded components are decoded once and re-encoded once;
`%2520` stays a literal `%20`. A `+` in an input FMP query is a literal plus,
not an HTML-form space. Use `%20` for spaces. Newly supplied values are literal,
so do not pre-encode `-file`, variables, or a script parameter.

## 4. Modify link

Start with `-url` and add options to adapt the link to your current task.
These are the same targeting and input options used by Show and Act; when a
URL is supplied, they modify the corresponding parts of that link.

```sh
# Choose a FileMaker client version.
fmide -url 'fmp19://$/fmIDE?script=fmIDE&$script_name=fmIDE' -fmp fmp26

# Open the linked file from your FileMaker Server.
# Replace fm.example.com with your server address.
fmide -url 'fmp://$/MySolution?script=fmIDE' -server fm.example.com

# Change the target file and the thing to show.
fmide -url 'fmp://$/OldFile?script=fmIDE&$layout_name=OldLayout' \
  -file fmIDE -$ 'layout_name=fmIDE Examples'

# Add frontmatter to the action script carried in a link.
fmide -url 'fmp://$/fmIDE?script=fmIDE&param=%5B%2B%5D.Exit%20Script%20%3D%20%3D%3D%20%24greeting' \
  -frontmatter '$greeting = "Hello"'

# Replace the link's script parameter with an inline fmIDEAS.
fmide -url 'fmp://$/fmIDE?script=fmIDE&param=old' \
  '[+].Go to Layout = "fmIDE Examples"'
```

The encoded script in the frontmatter example is
`[+].Exit Script = == $greeting`. Existing frontmatter is merged using the same
prepend rules described under Act.

### Override rules

Explicit options override the corresponding URL components. Unspecified
components stay as supplied. A server override replaces the entire authority,
including embedded credentials; credentials from an old host are never copied
to a new host. A port override preserves the selected authority's other parts.

A positional parameter or `--parameter-file` replaces the URL's `param`,
including when the supplied text is empty. Supplying `-$` replaces every
existing occurrence of that variable name, using case-insensitive matching.
Other query parameters, including `option=3` and blank values, are retained.
An existing nonempty `script` name remains unchanged.

## Choosing the target

These options apply to all four use cases:

- `-file` chooses the database, with or without `.fmp12`. If omitted, the `-url`
  must already contain a database name.
- `-fmp` chooses the FileMaker client: for example `fmp26` or `26`.
  The default is `fmp`, which uses the client's registered URL handler.
- `-server` chooses a host/IP, `$` for an already-open file, or `~` for the
  Documents folder. The default is `$`.
- `-port` chooses a port from 1 to 65535 for a host/IP. IPv6 addresses must use
  brackets, for example `[::1]:5003`.

When following a link, its target details are used unless an option overrides
them. Protocol and server have defaults when absent; the database does not.
If a link has no database name, supply `-file`.

## Preview and results

Add `--dry-run` (or `--print-url`) to any use case to print the resulting URL
without opening it. Specify `-file`, or use a link containing a file name.

```sh
fmide -file fmIDE -$ 'layout_name=fmIDE Examples' --dry-run
fmide -file fmIDE '[+].Go to Layout = "fmIDE Examples"' --dry-run
fmide -url 'https://fmp26//$/fmIDE?script=fmIDE' --dry-run
fmide -url 'fmp19://$/fmIDE?script=fmIDE' -fmp fmp26 --dry-run
```

FileMaker executes asynchronously. A successful dispatch means the operating
system accepted the URL; it does not confirm completion or return a script
result. Check FileMaker for results and dialogs.

## Option reference

```text
fmide [-file FILE] [-$ NAME=VALUE]...
      [--parameter-file PATH] [-frontmatter ASSIGNMENTS]...
      [-url URL] [-fmp PROTOCOL] [-server SERVER] [-port PORT]
      [--dry-run] [--] [SCRIPT-PARAMETER]
```

The positional script parameter appears at most once; options can precede it.

| Option | Meaning |
| --- | --- |
| `-$`, `--variable` | Name that Thing `NAME=VALUE`; repeatable, last wins. |
| Positional parameter | Script parameter; `-` reads stdin. |
| `--parameter-file` | UTF-8 script file (optional BOM), or `-` for stdin. Mutually exclusive with positional parameter. |
| `-frontmatter`, `--frontmatter` | Prepend FileMaker `Let` assignments; repeatable in argument order. |
| `-url`, `--url` | Open an FMP URL or thingamajig URI; combine with other options to modify it. |
| `-file`, `--file` | Database name, optionally with `.fmp12`; uses the file in `-url` when present. Required if the URL has no file. |
| `-fmp`, `--fmp` | `fmp`, `fmp26`, `26`, or `fmp26://`; defaults to link's scheme, then `fmp`. |
| `-server`, `--server` | Host/IP, `$` or `~`; defaults to link's host, then `$`. |
| `-port`, `--port` | Integer 1–65535; replaces a port in the chosen server. Requires a host/IP. |
| `--dry-run`, `--print-url` | Print the constructed URL without opening it. |
| `--version` | CLI version, independent of the installed fmIDE script version. |
| `-h`, `--help` | Usage. |

## Exit codes and operational limits

- `0`: URL printed or accepted for dispatch; not proof of script completion.
- `1`: invalid target, input-file error or dispatch failure.
- `2`: command-line syntax error.
- `130`: interrupted.

## Upgrade the Homebrew installation

Run `fmide brew upgrade` to upgrade the `fmide/cli/fmide` Homebrew formula.
The command delegates to Homebrew and returns its exit status. It does not
update installations made from a Python package or source checkout.

The command sends the URL once and does not retry. FileMaker privilege checks,
login, unsaved script dialogs, script errors and URL/payload size limits remain
FileMaker/OS responsibilities. A parameter file changes how text is read; it does
not bypass URL size limits. Live tests use a scratch result file to prove actual
execution. The CLI does not log dispatched URLs; preview output may contain
credentials or other values from the supplied URL.

## Protocol sources

- [Original requirements: fmIDE #135](https://github.com/fmIDE/fmIDE/issues/135)
- [Claris Apple-event permissions](https://help.claris.com/en/pro-help/content/scripting-apple-events.html)
- [Claris FMP URL format](https://help.claris.com/en/pro-help/content/opening-files-url.html)
- [fmIDE Name that Thing API](https://github.com/fmIDE/fmIDE/wiki/fmIDE-'Name-that-Thing'-API)
- [Homebrew custom taps](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)

## HTTPS forwarding servers

Use `fmide server --help` or the [server guide](servers.md) for persistent
localhost forwarders. New servers use HTTPS by default; immediate `-server` and
`-port` keep their existing target meanings, while `server -listen-port` selects
the HTTP(S) listener. To pass the literal
script parameter `server` to the immediate CLI, use `fmide -- server`.
