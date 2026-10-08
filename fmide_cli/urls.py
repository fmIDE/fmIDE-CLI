"""Pure URL construction; no FileMaker or shell calls."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote, unquote, urlencode, urlsplit


class InputError(ValueError):
    """Invalid CLI input or an unresolved target."""


def line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r")


def protocol(value: str) -> str:
    value = value.strip().lower().removesuffix("://").removesuffix(":")
    if value.isascii() and value.isdecimal():
        value = "fmp" + value
    if not re.fullmatch(r"fmp(?:[1-9][0-9]*)?", value):
        raise InputError("protocol must be fmp or fmp followed by a version, e.g. fmp26")
    return value


def normalize_url(value: str) -> str:
    """Repair known FMP manglings and expand documented thingamajig URIs."""
    value = value.strip()
    if re.search(r"[\x00-\x1f]", value):
        raise InputError("URL contains control characters; percent-encode parameter values")
    # Repair only the prefix: decoding the entire URL would destroy encoded &/?.
    value = re.sub(r"^(fmp[0-9]*)%3[aA](?:%2[fF]){2}", r"\1://", value, flags=re.I)
    value = re.sub(r"^https?://(?=fmp[0-9]*(?::|/))", "", value, flags=re.I)
    match = re.match(r"^(fmp[0-9]*)(?::/*|/+)", value, re.I)
    if match:
        value = protocol(match[1]) + "://" + value[match.end():]
        # fmp26//File is a thingamajig with an omitted host.
        if match[0].endswith("//") and ":" not in match[0]:
            remainder = value.split("://", 1)[1]
            if "/" not in re.split(r"[?&]", remainder, maxsplit=1)[0]:
                value = protocol(match[1]) + "://$/" + remainder
    elif "://" in value or (re.match(r"^[a-z][a-z0-9+.-]*:", value, re.I)
                            and not re.match(r"^[^/?#]+:[0-9]+/", value)):
        raise InputError("-url accepts only FMP URLs or thingamajig URIs")
    else:
        target = re.split(r"[?&]", value, maxsplit=1)[0]
        value = "fmp://" + ("$/" if "/" not in target else "") + value
    # Short URIs use & instead of ?script=fmIDE&.
    if "&" in value.split("?", 1)[0]:
        value = value.replace("&", "?", 1)
    return value


def parse_query(query: str) -> list[tuple[str, str]]:
    # FMP uses percent encoding, not HTML form encoding: '+' is literal.
    result = []
    for item in query.split("&"):
        if item:
            key, _, value = item.partition("=")
            result.append((unquote(key, errors="strict"), unquote(value, errors="strict")))
    return result


def replace_query(items: list[tuple[str, str]], key: str, value: str) -> None:
    items[:] = [(k, v) for k, v in items if k.casefold() != key.casefold()]
    items.append((key, value))


def variable(assignment: str) -> tuple[str, str]:
    name, separator, value = assignment.partition("=")
    name = name.removeprefix("$")
    if not separator or not name or re.search(r"[\s$&=?#\x00-\x1f]", name):
        raise InputError("each -$ needs NAME=VALUE (for example layout_name=Customers)")
    return "$" + name, value


def frontmatter(parameter: str, assignments: list[str]) -> str:
    parameter = line_endings(parameter)
    if not assignments:
        return parameter
    parts = [line_endings(item).strip() for item in assignments if item.strip()]
    if not parts:
        return parameter
    def separator(text: str) -> str:
        # Ignore comments only when inspecting the final token; keep the user's
        # calculation unchanged. Quoted comment markers remain string data.
        tokens = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r]*|/\*.*?\*/',
                        lambda m: m[0] if m[0].startswith('"') else "", text, flags=re.S)
        return "\r" if tokens.rstrip().endswith(";") else "\r;\r"

    additions = parts[0]
    for part in parts[1:]:
        additions += separator(additions) + part
    if parameter.startswith("---\r"):
        if not re.search(r"\r---(?:\r|$)", parameter[3:]):
            raise InputError("existing frontmatter has no closing --- delimiter")
        existing = parameter[4:]
        return "---\r" + additions + separator(additions) + existing
    return "---\r" + additions + "\r---\r" + parameter


def authority(value: str, override_port: int | None) -> str:
    if not value or re.search(r"[\s/?#\\\x00-\x1f]", value):
        raise InputError("server must be a hostname, IP address, $ or ~, optionally with a port")
    try:
        parsed = urlsplit("fmp://" + value)
        if not parsed.hostname:
            raise ValueError("missing hostname")
        old_port = parsed.port
    except ValueError as exc:
        raise InputError("invalid server or port (use brackets around IPv6 addresses)") from exc
    if old_port is not None and not 1 <= old_port <= 65535:
        raise InputError("port must be between 1 and 65535")
    if parsed.hostname in ("$", "~") and old_port is not None:
        raise InputError("a port requires a server hostname or IP address")
    if override_port is None:
        return value
    if not 1 <= override_port <= 65535:
        raise InputError("port must be between 1 and 65535")
    if parsed.hostname in ("$", "~"):
        raise InputError("a port requires a server hostname or IP address")
    userinfo, sep, host = value.rpartition("@")
    host = host if sep else value
    host = host[:host.index("]") + 1] if host.startswith("[") else host.split(":", 1)[0]
    return (userinfo + "@" if sep else "") + host + ":" + str(override_port)


@dataclass
class Options:
    url: str | None = None
    fmp: str | None = None
    server: str | None = None
    port: int | None = None
    file: str | None = None
    variables: list[str] = field(default_factory=list)
    frontmatter: list[str] = field(default_factory=list)
    parameter: str | None = None
    query_parameters: list[tuple[str, str]] = field(default_factory=list)


def build_url(options: Options, resolve_file: Callable[[str], str] | None = None) -> str:
    base = urlsplit(normalize_url(options.url)) if options.url is not None else urlsplit("fmp://$/")
    if base.fragment:
        raise InputError("URL fragments are not supported; encode literal # as %23")
    scheme = protocol(options.fmp if options.fmp is not None else base.scheme)
    host = authority(options.server if options.server is not None else base.netloc or "$", options.port)
    file = options.file if options.file is not None else unquote(base.path.lstrip("/"), errors="strict")
    if file in ("", "«file»"):
        if resolve_file is None:
            raise InputError("cannot determine the frontmost file; specify -file NAME")
        file = resolve_file(scheme)
    if not file or any(c in file for c in "\r\n\x00"):
        raise InputError("a nonempty file name is required; specify -file NAME")
    items = parse_query(base.query)
    # Explicit native FMP query fields override the base URL in request order.
    for key, value in options.query_parameters:
        if not key or re.search(r"[\s&=?#\x00-\x1f\x7f]", key) or key.startswith('-'):
            raise InputError("invalid FMP query parameter name")
        if key.startswith('$'):
            key, value = variable(key + '=' + value)
        replace_query(items, key, value)
    if not any(k.casefold() == "script" and v for k, v in items):
        replace_query(items, "script", "fmIDE")
    if options.parameter is not None:
        replace_query(items, "param", options.parameter)
    if options.frontmatter or any(k.casefold() == "param" for k, _ in items):
        parameter = next((v for k, v in reversed(items) if k.casefold() == "param"), "")
        replace_query(items, "param", frontmatter(parameter, options.frontmatter))
    for assignment in options.variables:
        key, value = variable(assignment)
        replace_query(items, key, value)
    items.sort(key=lambda item: 0 if item[0].casefold() == "script" else 1)
    query = urlencode(items, quote_via=quote, safe="$")
    return f"{scheme}://{host}/{quote(file, safe='')}?{query}"
