"""Translate HTTP query syntax into the same options used by the terminal CLI."""
from __future__ import annotations

import re

from .urls import InputError, Options, parse_query, variable

SCALARS = {
    '-url': 'url', '--url': 'url', 'url': 'url',
    '-file': 'file', '--file': 'file',
    '-fmp': 'fmp', '--fmp': 'fmp',
    '-server': 'server', '--server': 'server',
    '-port': 'port', '--port': 'port',
}
MAX_FIELDS = 256


def request_options(query: str, overrides: dict | None = None) -> Options:
    """Parse once, preserving literal + and the order of native/CLI variables.

    Only forwarding options are exposed, never shell execution, local file
    reading, or persistent server management. Saved target overrides take priority.
    """
    if not query or len(query.split('&')) > MAX_FIELDS:
        raise InputError('supply between 1 and 256 query parameters')
    if re.search(r'%(?![0-9a-fA-F]{2})', query):
        raise InputError('invalid percent escape in query')
    if any(not item or '=' not in item for item in query.split('&')):
        raise InputError('each query parameter must use NAME=VALUE')
    options = Options()
    seen = set()
    for name, value in parse_query(query):
        if name in SCALARS:
            field = SCALARS[name]
            if field in seen:
                raise InputError('duplicate CLI option: ' + field)
            seen.add(field)
            if not value:
                raise InputError('CLI options require a nonempty value')
            if field == 'port':
                if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
                    raise InputError('target port must be between 1 and 65535')
                value = int(value)
            setattr(options, field, value)
        elif name in ('-$', '--variable'):
            options.query_parameters.append(variable(value))
        elif name in ('-frontmatter', '--frontmatter'):
            options.frontmatter.append(value)
        elif name.startswith('-'):
            raise InputError('unsupported HTTP CLI option: ' + name)
        else:
            options.query_parameters.append((name, value))
    for field in ('fmp', 'server', 'file', 'port'):
        value = (overrides or {}).get(field)
        if value is not None:
            setattr(options, field, value)
    return options
