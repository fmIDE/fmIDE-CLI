"""Bounded action descriptions for normal logs; never include argument values."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from .urls import parse_query

THINGS = set('account base_table custom_function custom_menu_item custom_menu custom_menu_set '
             'extended_privilege external_data_source field layout_field layout layout_part '
             'object privilege_set script script_step t_o table theme value_list window'.split())
THING_KEYS = {thing + '_' + suffix for thing in THINGS for suffix in ('name', 'number', 'id', 'uuid')}
THING_KEYS.update(('script_name_stub', 'script_step_number_to', 'script_step_range',
                   'script_step_search', 'script_step_search_value'))
SAFE_FLAGS = {'fmide_debug', 'fmide_debugger'}


def first_json_action(value, depth=0):
    """Recognize action_name and the documented action/actions/[…] wrappers."""
    if depth > 8:
        return None
    if isinstance(value, list):
        return first_json_action(value[0], depth + 1) if value else None
    if isinstance(value, dict):
        name = value.get('action_name')
        if isinstance(name, str) and name.strip():
            return name
        for key in ('action', 'actions', '[…]', '[...]'):
            if key in value:
                return first_json_action(value[key], depth + 1)
        # Action-array shorthand: [{"Go to Layout": {...}}, {"Loop": null}].
        if len(value) == 1:
            key, arguments = next(iter(value.items()))
            if key not in THING_KEYS | SAFE_FLAGS and (isinstance(arguments, dict) or arguments is None):
                return key
    return None


def action_summary(url: str) -> str:
    """Summarize the final URL without evaluating FileMaker expressions."""
    result = {}
    names = set()
    flags = {}

    def collect(items):
        for key, value in items:
            key = key.lower().removeprefix('$')
            if value is None or value == '' or (isinstance(value, str) and not value.strip()):
                continue
            if key in THING_KEYS:
                names.add('$' + key)
            if key in SAFE_FLAGS:
                text = str(value).strip().lower()
                flags['$' + key] = text if text in ('0', '1', 'true', 'false') else '<expression>'

    query = parse_query(urlsplit(url).query)
    collect(query)
    parameter = next((v for k, v in query if k.lower() == 'param'), '').strip()
    if parameter:
        lines = parameter.splitlines()
        if lines and lines[0].strip() == '---':
            end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
            parameter = '\n'.join(lines[end + 1:]).strip() if end is not None else ''
        try:
            payload = json.loads(parameter)
        except (ValueError, RecursionError):
            # fmJAML paths can themselves contain names: log only the first path,
            # never its value, and JSON-escape it below to prevent log injection.
            line = next((s.strip() for s in parameter.splitlines()
                         if s.strip() and not s.lstrip().startswith(('#', '//'))), '')
            if '=' in line or re.match(r'^\[(?:\d+|\+|:)\]\.', line):
                result['fmJAML'] = line.split('=', 1)[0].strip()[:120]
            elif parameter:
                result['parameter'] = 'unrecognized'
        else:
            result['parameter'] = 'JSON'
            if isinstance(payload, dict):
                collect(payload.items())
            name = first_json_action(payload)
            if name:
                result['action'] = name[:120]
    if names:
        result['things'] = sorted(names)
    if flags:
        result['options'] = flags
    return json.dumps(result, ensure_ascii=True, separators=(', ', ': '))
