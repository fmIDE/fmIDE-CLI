"""Small, bounded operating-system integrations."""
from __future__ import annotations

import os
import subprocess
import sys

from .urls import InputError

# Resolve the application registered for the chosen URL scheme, rather than
# guessing an application name (several FileMaker versions can coexist).
FRONTMOST_JXA = r'''
ObjC.import('AppKit');
function run(argv) {
    var url = $.NSURL.URLWithString(argv[0] + '://$/');
    var appURL = $.NSWorkspace.sharedWorkspace.URLForApplicationToOpenURL(url);
    if (!appURL) throw new Error('No application registered for ' + argv[0]);
    var app = Application(ObjC.unwrap(appURL.path));
    if (!app.running()) throw new Error('FileMaker is not running');
    var windows;
    try { windows = app.windows(); } catch (e) { throw new Error('Reading FileMaker windows: ' + e.message); }
    if (!windows.length) throw new Error('No open FileMaker window');
    var title = windows[0].name();
    var matches = [];
    var documents;
    try { documents = app.documents(); } catch (e) { throw new Error('Reading FileMaker documents: ' + e.message); }
    for (var i = 0; i < documents.length; i++) {
        var names = documents[i].windows.name();
        if (names.indexOf(title) !== -1) matches.push(documents[i].name());
    }
    if (matches.length !== 1) throw new Error('Cannot identify the frontmost database unambiguously');
    return matches[0];
}
'''


def frontmost_file(scheme: str) -> str:
    if sys.platform != "darwin":
        raise InputError("frontmost-file detection requires macOS; specify -file NAME")
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", FRONTMOST_JXA, scheme],
            capture_output=True, text=True, check=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InputError(
            "cannot determine the frontmost FileMaker file; specify -file NAME "
            "or check macOS Automation access and the FileMaker fmextscriptaccess privilege. "
            + (getattr(exc, "stderr", "") or ("operation timed out" if isinstance(exc, subprocess.TimeoutExpired) else str(exc))).strip()[:300]
        ) from exc
    name = result.stdout.rstrip("\r\n")
    if not name:
        raise InputError("no frontmost FileMaker file; specify -file NAME")
    return name


def open_url(url: str) -> None:
    """Dispatch once. Success means OS acceptance, not FileMaker completion."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/open", url], check=True, capture_output=True, timeout=15)
        elif sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            raise InputError("opening FileMaker requires macOS or Windows; use --dry-run to print the URL")
    except (OSError, subprocess.SubprocessError) as exc:
        raise InputError("could not open the FMP URL; check that the selected FileMaker version is installed") from exc
