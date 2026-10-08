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

## Send a link

The request format is:

```text
http://localhost:43103/?url=ENCODED_FMP_URL
```

Encode the **entire embedded URL** once for the outer HTTP query. In particular,
its `&` must be encoded as `%26` and existing percent escapes as `%25`. `url` has
no leading dash. The server decodes the outer query once, then applies the same
FMP normalization/repair and encoding rules as `fmide -url`.

A link to `fmp://$/MyDatabase`:

```text
http://localhost:43103/?url=fmp%3A%2F%2F%24%2FMyDatabase
```

A link showing the Customers layout:

```text
http://localhost:43103/?url=fmp%3A%2F%2F%24%2FMyDatabase%3Fscript%3DfmIDE%26%24layout_name%3DCustomers
```

Have curl encode a potentially mangled link for you:

```sh
curl --get 'http://localhost:43103/' \
  --data-urlencode 'url=https://fmp26//$/MyDatabase?script=fmIDE&$layout_name=Customers'
```

Send the same link to the old FileMaker client using port 43104:

```sh
curl --get 'http://localhost:43104/' \
  --data-urlencode 'url=fmp26://$/MyDatabase?script=fmIDE&$layout_name=Customers'
```

Server 1's saved `-fmp fmp19` overrides the embedded `fmp26` scheme. Other saved
target settings likewise override the link. In JavaScript, construct the outer
query with `new URLSearchParams({url: fmpUrl})`. Use a normal clickable link;
cross-origin JavaScript fetches and embedded image requests are rejected.

HTTP 200 means the OS accepted the URL, **not that a FileMaker script finished**.
The JSON response does not echo sensitive URL contents. Invalid links return 400,
unknown paths 404, oversized forwarding URLs 414, failed OS dispatch 502, and a
stopping worker 503. A link must contain a database unless `-file` is saved;
HTTP requests do not query FileMaker for the frontmost database. The outer request
URL is limited to 16,384 characters.

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
