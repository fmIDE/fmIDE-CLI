# Local HTTP forwarding servers

Run independent localhost servers that accept HTTP links and dispatch FMP URLs
through the **same URL builder and OS dispatcher as the immediate `fmide` CLI**.
No shell command is constructed. Each server has persistent settings, its own
background process and a rotating debug log. Management currently supports macOS
and Linux; actual FileMaker dispatch requires macOS. Existing immediate commands
continue to support Windows.

## Start two servers

```sh
fmide server add start -tag new
fmide server add start -tag old -fmp fmp19
fmide server list
```

On an empty configuration this creates servers 0 and 1, listening on ports 43103
and 43104. Set `-file NewDatabase` or `-file OldDatabase` to enforce a database;
otherwise each link supplies its database. Without `-fmp`, the incoming scheme is
preserved (short URLs default to `fmp`, the registered FileMaker handler).

```text
INDEX  TAG  PORT   STATE    FMP    HOST  FILE
0      new  43103  running  —      —     —
1      old  43104  running  fmp19  —     —
```

`—` means preserve the incoming URL's value. `status` also shows the listening
address, target port, debug setting, settings file and log location.

## Welcome page

The fmIDE Gateway welcome page identifies the current server with its listening
port, index, tag and saved forwarding targets. It includes code-formatted API
examples, a link to the Name that Thing parameter reference, and an animated
SVG loaded from the repository on GitHub (an internet connection is required
for the image). Browsers show a gateway-specific tab title.

Open `http://localhost:43103/` to see a welcome message, an explanation of the
forwarding server, usage examples and a link to this guide. A bare `/` or `/?`
returns HTTP 200 without dispatching to FileMaker, even with a saved database.
Browsers requesting `text/html` receive HTML; `curl http://localhost:43103/`
receives the same guidance as plain text. The response uses the actual listening
port. Requests containing parameters still use normal forwarding and validation;
for example, `/?url=` remains an error.

## Send a request (0.3.0)

The dash makes the scope visible: `-file`, `-fmp`, and `-url` instruct the CLI
forwarder; `script`, `param`, and `$` variables go to FileMaker. Both styles can
be combined in one request. The server translates them into the shared CLI core;
it never constructs or runs a shell command.

### Native fmIDE parameters

```text
http://localhost:43103/?-file=MyFile&$layout_name=Home&$fmide_debugger=1
```

This produces `fmp://$/MyFile?script=fmIDE&$layout_name=Home&$fmide_debugger=1`
when the server has no saved target overrides. `script=fmIDE` is the default;
explicit `script=OtherScript` and `param=SCRIPT_PARAMETER` also work.

A server with a saved `-file` can use the shorter form:

```text
http://localhost:43103/?$layout_name=fmIDE%20Actions
```

To select a script's steps, quote the range as a FileMaker calculation string:

```text
http://localhost:43103/?-file=fmIDE&$script_name=fmIDE&$script_step_range=%221..-1%22&$fmide_debugger=0
```

The existing FMP query suffix can stay unchanged: replace
`fmp://$/MyFile?script=fmIDE` with `http://localhost:43103/?-file=MyFile`.
An explicit custom `script` must be retained.

### CLI-style parameters

The equivalent variable-option form is:

```text
http://localhost:43103/?-file=MyFile&-$=layout_name=Home&-$=fmide_debugger=1
```

An optional leading `$` in the assignment is accepted, e.g.
`-$=$layout_name=Home`. Supported options are `-file`, `-fmp`, `-server`, `-port`,
`-url`, `-$`, and `-frontmatter`. Their double-dash aliases work too (`--variable`
for `-$`). `param` supplies the script parameter; the terminal CLI's positional
script parameter does not become a new dash option.

Local file input (`--parameter-file`), preview flags, and server-management
settings/verbs are not exposed through forwarding URLs. Unsupported dash options
are errors. Other non-dash names pass through as FMP query parameters. The one
reserved compatibility name is `url`, an alias for `-url` from version 0.2.0.

### Forward an existing or mangled URL

`-url` supplies a base URL that additional request parameters can modify.
The original `url=` spelling remains supported.

```sh
curl --get 'http://localhost:43103/' \
  --data-urlencode '-url=https://fmp26//$/MyDatabase?script=fmIDE&$layout_name=Customers'
```

Encode the entire embedded URL once for the outer query: its `&` becomes `%26`
and existing percent escapes become `%25`. For example:

```text
http://localhost:43103/?-url=fmp%3A%2F%2F%24%2FMyDatabase
```

For native parameters, encode individual values rather than the whole query:

```sh
curl --get 'http://localhost:43103/' \
  --data-urlencode '-file=MyDatabase' \
  --data-urlencode '$layout_name=Customers' \
  --data-urlencode '$fmide_debugger=1'
```

### Encoding and precedence

Queries follow FMP percent-encoding conventions: **literal `+` remains `+`**;
use `%20` for a space, `%26` for an ampersand in a value, and `%25` for a literal
percent sign. Each query layer is decoded exactly once. This applies to both
`-url` and its `url` alias. Form encoders that use `+` for spaces must be adjusted:
in JavaScript use `new URLSearchParams(values).toString().replace(/\+/g, "%20")`,
or encode each key/value with `encodeURIComponent`. curl's `--data-urlencode`
already uses percent escapes for spaces.

Target precedence, highest first:

1. Saved server overrides.
2. Explicit request options (`-file`, `-fmp`, `-server`, `-port`).
3. The embedded `-url` target.
4. Ordinary defaults (`fmp`, `$`, and `script=fmIDE`).

A server configured for `fmp19` keeps that target even if a request says `-fmp=26`.
Native request parameters replace matching embedded URL query fields. Repeated
native fields/variables use the last value, case-insensitively; native `$x` and
CLI `-$=x=...` participate in the same request order. Repeated `-frontmatter`
values are combined by the CLI's existing frontmatter rules. Duplicate scalar
CLI options, including mixed aliases such as `url` and `-url`, are rejected.
Empty native values are allowed; target options and `-url` require a value.

Requests never change saved settings. A database must come from the request,
embedded URL or saved `-file`; HTTP requests do not query FileMaker for the
frontmost database. All requests use `NAME=VALUE`, with at most 256 fields and
16,384 characters in the outer request URL. Malformed percent escapes and UTF-8
are rejected.

HTTP 200 means the OS accepted the URL, **not that a FileMaker script finished**.
The JSON response does not echo sensitive URL contents. Invalid requests return
400, unknown paths 404, oversized forwarding URLs 414, failed OS dispatch 502,
and a stopping worker 503. Use normal browser links; cross-origin JavaScript
fetches and embedded image requests are rejected.

## Command grammar

```text
fmide server [ID] [VERB] [OPTIONS]
fmide server add [start|set] [OPTIONS]
fmide server list
```

ID defaults to `0`; the verb defaults to `set`. With no settings, `set` shows
status. `add` without a verb creates and saves settings without starting a worker.
`add start` also starts it. `add` accepts no identifier.

An identifier can be an index, a saved listening port, a unique tag, or `all`:

```sh
fmide server new stop
fmide server 1 start
fmide server 43104 status
fmide server all stop
```

| Verb | Behavior |
| --- | --- |
| `add [start]` | Append a configuration; optionally start it. |
| `set` | Save supplied settings; with none, show status. |
| `unset -fmp -server …` | Clear selected overrides/settings to their defaults. |
| `start` | Start in the background; already running is a successful no-op. |
| `restart` | Stop gracefully, then start with saved settings; also starts a stopped server. |
| `stop` | Gracefully stop; keep settings and logs. |
| `kill` | Force this authenticated worker to exit; keep settings and logs. |
| `remove` | Remove settings of stopped servers; refuse if any selected server is active. |
| `terminate` | Gracefully stop, then remove settings; retain settings if stopping fails. |
| `status` | Show selected servers and their details. |
| `list` | Show all configurations in one table, including stopped servers. |
| `tail` | Show the last 20 log lines per selected server, then follow new lines and rotations. |

Ctrl-C ends `tail` without stopping servers. `all` selects the currently configured
servers, so no shell quoting is needed:

```sh
fmide server all terminate
```

This stops workers and resets configurations. Historical logs remain available.
A batch `remove` checks every selected server before removing any. Other lifecycle
batches attempt each server and report failures; successful terminations stay
removed, failed servers retain settings. Force termination uses the worker's
private authenticated endpoint; it never kills an unrelated process using a stale
PID. An unresponsive/unverifiable worker is reported without deleting settings.

## Settings

| Option | Meaning |
| --- | --- |
| `-listen-port PORT` | Local HTTP port, initially `43103 + index`. |
| `-tag NAME` | Unique, case-sensitive display name and identifier. |
| `-fmp PROTOCOL` | FMP protocol override, e.g. `fmp26`, `26`, or `fmp19`. |
| `-server HOST` | FileMaker host override, including `$` or `~`. |
| `-port PORT` | Target FileMaker host port override, distinct from the HTTP port. |
| `-file NAME` | Database override. |
| `-debug on\|off` | Include full forwarded URLs in the log; default `off`. |

Both single- and double-dash forms work. Omitted settings retain saved values.
Settings accompanying any verb are validated and saved before that operation;
`list` is a read-only overview and accepts no settings. Settings changes apply to
subsequent requests; an in-flight dispatch completes using its original settings.
Changing the listening port of a running server gracefully restarts it. If binding
the new port fails, the previous settings and listener are restored when possible.

```sh
fmide server new set -fmp fmp26 -file NewDatabase
fmide server old -server fm.example.com
fmide server 1 set -listen-port 45000
fmide server 45000 tail
fmide server new unset -file -fmp
fmide server new set -debug on
```

Tags may use letters, digits, `_`, `.`, and `-`, must start with a letter/digit/`_`,
and must contain a letter or `_`. Numeric labels, command verbs (in any case),
`all`, and `*` are reserved. Tags do not rename or renumber servers.

Indices are stable. Removing server 0 leaves a hole if server 1 exists. `add`
uses the highest remaining index plus one; it does not fill interior holes.
`fmide server 0 start` can recreate server 0 with defaults, not its removed
settings. Removing trailing entries makes their indices available again; when
empty, `add` starts at 0. New indices are limited to 0–22432 so their default ports
are valid. A conflict with an existing saved port is an error, never silently
skipped; specify `-listen-port` when necessary.

Numeric lookup checks existing indices, then saved ports. Configurations cannot
share ports, even when stopped, and a port cannot equal another server's index.
After changing a port, use the new port (or unchanged index/tag) to identify it.
Unknown names/ports do not silently create a server. Explicit unused indices can
be created with `start` or `set` with options.

## Logs and storage

On macOS: `~/Library/Application Support/fmide/servers/`.
On Linux: `$XDG_STATE_HOME/fmide/servers/` or `~/.local/state/fmide/servers/`.
`FMIDE_SERVER_HOME` selects a separate directory, useful for testing.

Settings are written atomically under a process lock. Private runtime files carry
per-worker control tokens. Logs are named `INDEX.log`, rotate at 1 MiB, and retain
three backups. Startup, shutdown, forwarding acceptance, and failures are logged.
Full URLs are recorded only with `-debug on`; they may contain credentials and
script data. Turning debugging off does not erase earlier log entries.

Servers bind only to IPv4 loopback (`127.0.0.1`, also reachable as `localhost`).
They reject foreign Host/Origin values, expose no CORS permission, and authenticate
management requests. A normal browser link navigation intentionally dispatches
its FMP URL; only open forwarding links whose actions you intend to run.
Background workers survive closing the starting terminal but are not login
services and do not automatically restart after a reboot.

## Upgrading a running worker

After upgrading the CLI with Homebrew, restart existing workers to load the new
code. `restart` preserves saved settings and logs; it accepts an index, port,
tag or `all`. It requires an existing configuration and does not start a
replacement if stopping fails. Do not use `terminate`:

```sh
fmide server all restart
# Or restart only one server:
fmide server 43104 restart
```

### Action summaries

Normal logs describe each accepted forwarding request (and dispatch failures):

```text
INFO forward accepted by operating system; {"things": ["$layout_name"], "options": {"$fmide_debugger": "1"}}
INFO forward accepted by operating system; {"fmJAML": "[1].action_name"}
INFO forward accepted by operating system; {"parameter": "JSON", "action": "Go to Layout"}
```

Non-empty Name that Thing selectors are listed by name, including name, number,
ID and UUID selectors, script ranges and searches. Their values are omitted.
`$fmide_debugger` and `$fmide_debug` include literal `0`, `1`, `true` or `false`;
calculations are shown as `<expression>` and are never evaluated.

For `param`, fmJAML shows the first non-comment line up to (excluding) `=`,
skipping frontmatter. JSON shows the first `action_name`, including within
`action`, `actions` or an array, or the first command key in an action array; top-level Name that Thing selectors are also
summarized. Unknown payloads show only their type. Command labels are limited
to 120 characters and escaped onto one log line. Labels and fmJAML paths can
contain names supplied by the caller; argument values, database names, hosts,
credentials, frontmatter and unknown variables are omitted. Full URLs still
require `-debug on`. Summaries describe requests, not FileMaker completion.
