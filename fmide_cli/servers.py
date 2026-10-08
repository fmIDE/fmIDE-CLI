"""CLI for independently configured localhost forwarding workers."""
from __future__ import annotations

import argparse
from collections import deque
from http.client import HTTPException
import copy
import os
from pathlib import Path
import subprocess
import sys
import time

from .server_http import control, process_locked, state, worker
from .server_store import FIELDS, VERBS, Store, default_config, resolve, validate
from .urls import InputError, protocol

_CHILDREN: list[subprocess.Popen] = []


def start(store: Store, index: str) -> None:
    current, _ = state(store, index)
    if current == 'running':
        return
    if current != 'stopped':
        raise InputError(f'server {index} is {current}; inspect its log before restarting')
    store.runtime(index).unlink(missing_ok=True)
    env = dict(os.environ, FMIDE_SERVER_HOME=str(store.root))
    # Works from a checkout, a wheel, and Homebrew libexec without relying on PATH.
    package_root = str(Path(__file__).resolve().parent.parent)
    env['PYTHONPATH'] = package_root
    child = subprocess.Popen([sys.executable, '-m', 'fmide_cli.servers', '--worker', index],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True,
                             cwd=package_root, env=env)
    _CHILDREN.append(child)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise InputError(f'server {index} failed to start; inspect {store.log(index)}')
        if state(store, index)[0] == 'running':
            return
        time.sleep(0.05)
    child.terminate()
    try:
        child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
    raise InputError(f'server {index} startup timed out; inspect {store.log(index)}')


def stop(store: Store, index: str, force: bool = False) -> None:
    current, runtime = state(store, index)
    if current == 'stopped':
        store.runtime(index).unlink(missing_ok=True)
        return
    if current == 'unreachable' or not runtime:
        raise InputError(f'server {index} cannot be authenticated; settings retained; inspect {store.log(index)}')
    control(runtime, 'kill' if force else 'stop', timeout=3)
    deadline = time.monotonic() + (5 if force else 25)
    while time.monotonic() < deadline:
        for child in _CHILDREN[:]:
            if child.poll() is not None:
                _CHILDREN.remove(child)
        if not process_locked(store, index):
            store.runtime(index).unlink(missing_ok=True)
            return
        time.sleep(0.05)
    raise InputError(f'server {index} did not stop; settings retained; use kill to force termination')


def table(store: Store, configs: dict, indices: list[str], details: bool = False) -> None:
    rows = [['INDEX', 'TAG', 'PORT', 'STATE', 'FMP', 'HOST', 'FILE']]
    for index in indices:
        cfg = configs[index]
        # Do not expose credentials embedded in a saved FMP authority.
        host = cfg.get('server')
        host = host.rsplit('@', 1)[-1] if host else '—'
        rows.append([index, cfg.get('tag') or '—', str(cfg['listen_port']), state(store, index)[0],
                     cfg.get('fmp') or '—', host, cfg.get('file') or '—'])
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print('  '.join(value.ljust(width) for value, width in zip(row, widths)).rstrip())
    if not indices:
        print('No forwarding servers configured.')
    if details:
        for index in indices:
            cfg = configs[index]
            print(f'Server {index}: http://127.0.0.1:{cfg["listen_port"]}/')
            print(f'  Target port: {cfg.get("port") or "preserve"}; debug: {"on" if cfg.get("debug") else "off"}')
            print(f'  Log: {store.log(index)}')
        print(f'Settings: {store.path}')


def tail(store: Store, indices: list[str]) -> None:
    if not indices:
        print('No forwarding servers configured.')
        return
    positions = {}
    for index in indices:
        path = store.log(index)
        try:
            with path.open(encoding='utf-8', errors='replace') as stream:
                for line in deque(stream, maxlen=20):
                    print(f'[{index}] {line}', end='', flush=True)
                positions[index] = (os.fstat(stream.fileno()).st_ino, stream.tell())
        except FileNotFoundError:
            positions[index] = (None, 0)
    while True:
        for index in indices:
            try:
                with store.log(index).open(encoding='utf-8', errors='replace') as stream:
                    stat = os.fstat(stream.fileno())
                    inode, offset = positions[index]
                    stream.seek(offset if inode == stat.st_ino and offset <= stat.st_size else 0)
                    for line in stream:
                        print(f'[{index}] {line}', end='', flush=True)
                    positions[index] = (stat.st_ino, stream.tell())
            except FileNotFoundError:
                pass
        time.sleep(0.2)


def parse(argv: list[str]):
    # Select the grammar before argparse reads option values (a tag may be 'unsettable').
    leading = []
    for word in argv:
        if word.startswith('-'):
            break
        leading.append(word)
    unset = 'unset' in leading
    parser = argparse.ArgumentParser(
        prog='fmide server', allow_abbrev=False,
        description='Manage localhost FMP forwarding servers. ID is an index, saved port, tag, or all.',
        epilog='Default ID: 0. Default verb: set (no settings shows status). '
               'Use add [start] to append. Default port: 43103 + index. '
               'Verbs: add, set, unset, start, stop, remove, terminate, kill, status, list, tail. '
               'stop keeps settings; remove requires stopped; terminate stops and removes; kill forces stop.',
    )
    parser.add_argument('words', nargs='*', metavar='[ID] [VERB]')
    help_text = {
        'fmp': 'saved FMP protocol/version override',
        'server': 'saved FileMaker host override (not the HTTP listener)',
        'file': 'saved database override',
        'port': 'saved FileMaker host port override',
        'listen_port': 'local HTTP port (default: 43103 + index)',
        'tag': 'unique nonnumeric name usable as an identifier',
        'debug': 'log full forwarded URLs, potentially including secrets (default: off)',
    }
    for field in FIELDS:
        name = field.replace('_', '-')
        kwargs = {'dest': field, 'default': None, 'help': help_text[field]}
        if unset:
            kwargs['action'] = 'store_true'
        elif field == 'debug':
            kwargs['choices'] = ('on', 'off')
        elif field in ('port', 'listen_port'):
            kwargs['type'] = int
        parser.add_argument('-' + name, '--' + name, **kwargs)
    args = parser.parse_intermixed_args(argv)
    words = args.words
    adding = bool(words and words[0] == 'add')
    if adding:
        if len(words) > 2 or (len(words) == 2 and words[1] not in ('start', 'set')):
            parser.error('use add [start|set] [OPTIONS]; add has no identifier')
        identifier, verb = None, words[1] if len(words) == 2 else 'set'
    else:
        identifier = '0'
        if words and words[0] not in VERBS:
            identifier, words = words[0], words[1:]
        if len(words) > 1 or (words and words[0] not in VERBS - {'add'}):
            parser.error('expected [ID] start|stop|set|unset|tail|status|list|remove|terminate|kill')
        verb = words[0] if words else 'set'
    if verb == 'list' and identifier != '0':
        parser.error('list takes no identifier; use status for selected servers')
    changes = {field: getattr(args, field) for field in FIELDS if getattr(args, field) is not None}
    if not unset:
        if 'debug' in changes:
            changes['debug'] = changes['debug'] == 'on'
        if 'fmp' in changes:
            changes['fmp'] = protocol(changes['fmp'])
    if verb == 'list' and changes:
        parser.error('list takes no settings')
    if verb == 'unset' and not changes:
        parser.error('unset requires settings to clear, e.g. unset -fmp -server')
    return identifier, verb, adding, changes


def execute(argv: list[str]) -> int:
    identifier, verb, adding, changes = parse(argv)
    if os.name != 'posix':
        raise InputError('forwarding servers currently require macOS or Linux; immediate CLI commands are unchanged')
    store = Store()
    with store.locked():
        original = store.read()
        configs = copy.deepcopy(original)
        if adding:
            index = str(max(map(int, configs), default=-1) + 1)
            configs[index] = default_config(int(index))
            indices = [index]
        elif identifier == 'all' or verb == 'list' or (not configs and identifier == '0' and verb == 'set' and not changes):
            indices = sorted(configs, key=int)
        else:
            # Bare server/status never creates a configuration as a side effect.
            create = verb == 'start' or (verb == 'set' and bool(changes))
            index = resolve(configs, identifier, create=create)
            if index not in configs:
                configs[index] = default_config(int(index))
            indices = [index]
        if not indices and changes:
            raise InputError('no servers to configure; use server add')
        for index in indices:
            if verb == 'unset':
                defaults = default_config(int(index))
                for field in changes:
                    configs[index][field] = defaults[field]
            else:
                configs[index].update(changes)
        validate(configs)  # Validate the entire batch before mutating settings or processes.
        if verb == 'remove':
            busy = [index for index in indices if state(store, index)[0] != 'stopped']
            if busy:
                raise InputError('stop servers ' + ', '.join(busy) + ' first, or use terminate')
        changed = configs != original
        restarting = []
        if changed:
            for index in indices:
                if index in original and configs[index]['listen_port'] != original[index]['listen_port']:
                    current = state(store, index)[0]
                    if current != 'stopped':
                        if current != 'running':
                            raise InputError(f'server {index} is {current}; stop it before changing ports')
                        restarting.append(index)
            # Stop before changing the advertised port. Restore previous settings on bind failure.
            for index in restarting:
                stop(store, index)
            store.save(configs)
            try:
                if verb not in ('stop', 'kill', 'terminate', 'remove'):
                    for index in restarting:
                        start(store, index)
            except (InputError, OSError):
                for index in restarting:
                    stop(store, index)
                store.save(original)
                for index in restarting:
                    start(store, index)
                raise
        errors = []
        for index in indices:
            try:
                if verb == 'start':
                    start(store, index)
                elif verb in ('stop', 'kill', 'terminate'):
                    stop(store, index, force=verb == 'kill')
                if verb in ('remove', 'terminate'):
                    configs.pop(index)
                    store.runtime(index).unlink(missing_ok=True)
                    store.save(configs)
                    print(f'Removed server {index}; debug logs retained.')
            except (InputError, OSError, HTTPException) as exc:
                errors.append(str(exc))
        if verb not in ('tail', 'remove', 'terminate'):
            table(store, configs, indices, details=verb != 'list')
        if errors:
            raise InputError('; '.join(errors))
    # Following logs must never keep the settings lock held.
    if verb == 'tail':
        tail(store, indices)
    return 0


def main(argv: list[str]) -> int:
    try:
        return execute(argv)
    except (InputError, OSError, ValueError, HTTPException) as exc:
        print(f'fmide server: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        raise SystemExit(worker(sys.argv[2]))
    raise SystemExit(main(sys.argv[1:]))
