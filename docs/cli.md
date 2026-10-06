# Command reference

```text
fmide [-fmp PROTOCOL] [-server SERVER] [-port PORT] [-file FILE]
      [-url URL] [-$ NAME=VALUE]... [-frontmatter ASSIGNMENTS]...
      [--parameter-file PATH] [--dry-run] [--] [SCRIPT-PARAMETER]
```

| Option | Meaning |
| --- | --- |
| `-fmp`, `--fmp` | `fmp`, `fmp26`, `26`, or `fmp26://`; defaults to URL scheme, then `fmp`. |
| `-server`, `--server` | Host/IP, `$` for an open file, or `~` for Documents; defaults to URL host, then `$`. |
| `-port`, `--port` | Integer 1–65535; replaces a port in the chosen server. Requires a host/IP. |
| `-file`, `--file` | Database name, optionally with `.fmp12`; defaults to URL file, then frontmost file. |
| `-url`, `--url` | Base FMP URL or thingamajig URI. |
| `-$`, `--variable` | `NAME=VALUE`, with optional leading `$` on NAME. Repeatable, last wins. |
| `-frontmatter`, `--frontmatter` | FileMaker `Let` variable assignments. Repeatable, prepended in argument order. |
| `--parameter-file` | UTF-8 file (optional BOM), or `-` for stdin. Mutually exclusive with positional parameter. |
| `--dry-run`, `--print-url` | Print the constructed URL instead of dispatching. |
| `--version` | CLI version, independent of the installed fmIDE script version. |
| `-h`, `--help` | Usage. |
| Positional parameter | Literal script parameter; `-` reads stdin. Replaces the URL's `param`, including when empty. |

## Precedence

Explicit options override the corresponding URL components. Unspecified
components stay as supplied. A server override replaces the entire authority,
including embedded credentials; credentials from an old host are never copied
to a new host. A port override preserves the selected authority's other parts.
IPv6 addresses must use brackets, for example `[::1]:5003`.

The default script is `fmIDE`. An existing nonempty `script` query parameter is
preserved, so `-url` can also open a URL for another script. Existing options such
as `option=3` are retained. Variable replacement is case-insensitive (as in
FileMaker); every duplicate of the supplied name is replaced. Other parameters
are retained, including blank values. Values may contain `=`.

No file, an empty file, or the literal placeholder `«file»` requests frontmost-file
detection. On macOS the CLI resolves the app registered for the selected FMP
scheme and matches its frontmost document window to its database. It uses the
database name, not a guessed window title. It does not launch FileMaker merely
to discover a target. If detection is unavailable, ambiguous, denied or times
out, it fails with an instruction to use `-file`. It never silently chooses a
different database. macOS may request Automation access for the terminal.
FileMaker can also reject Apple events when its `fmextscriptaccess` extended
privilege is disabled; use an explicit file in that case.
On Windows supply `-file` explicitly.

## Supported URL repairs

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

## Frontmatter and line endings

Frontmatter is FileMaker calculation syntax, not YAML. The CLI does not evaluate
it. It normalizes script CRLF/LF line endings to FileMaker CR line endings,
adds a `---` block if absent, or inserts assignments at the beginning of an
existing block. Semicolon separators are inserted between added blocks and
existing assignments, on separate lines to accommodate trailing `//` comments.
An unterminated existing block is rejected when adding frontmatter.

An existing assignment appears after newly prepended assignments: FileMaker
therefore evaluates it later. This is prepend semantics, not an override of
existing variables. Empty `-frontmatter` strings have no effect.

## Exit codes and operational limits

- `0`: URL printed or accepted for dispatch; not proof of script completion.
- `1`: invalid target, input-file error, discovery failure or dispatch failure.
- `2`: command-line syntax error.
- `130`: interrupted.

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
