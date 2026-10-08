"""Private, atomically persisted forwarding-server configurations (POSIX)."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .urls import InputError, Options, authority, build_url, protocol

BASE_PORT = 43103
VERBS = {'add', 'set', 'unset', 'start', 'restart', 'stop', 'remove', 'terminate', 'kill', 'status', 'list', 'tail'}
FIELDS = ('fmp', 'server', 'file', 'port', 'listen_port', 'tag', 'debug')


def home() -> Path:
    if os.environ.get('FMIDE_SERVER_HOME'):
        return Path(os.environ['FMIDE_SERVER_HOME']).expanduser().resolve()
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'fmide' / 'servers'
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state'))) / 'fmide' / 'servers'


def atomic_json(path: Path, value: object) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default
    except (ValueError, UnicodeError) as exc:
        raise InputError(f'cannot read {path}; repair the file before continuing') from exc


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else home()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.root / 'settings.json'

    @contextmanager
    def locked(self):
        import fcntl
        with (self.root / 'settings.lock').open('a') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self) -> dict:
        value = read_json(self.path, {'version': 1, 'servers': {}})
        if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('servers'), dict):
            raise InputError(f'unsupported settings in {self.path}')
        configs = value['servers']
        try:
            for key, config in configs.items():
                if str(int(key)) != key or int(key) < 0 or not isinstance(config, dict):
                    raise ValueError('invalid server index or settings')
            validate(configs)
        except (TypeError, KeyError, ValueError) as exc:
            raise InputError(f'invalid settings in {self.path}: {exc}') from exc
        return configs

    def save(self, configs: dict) -> None:
        validate(configs)
        atomic_json(self.path, {'version': 1, 'servers': configs})

    def runtime(self, index: str) -> Path:
        return self.root / f'{index}.runtime.json'

    def log(self, index: str) -> Path:
        return self.root / f'{index}.log'


def default_config(index: int) -> dict:
    if not 0 <= index <= 65535 - BASE_PORT:
        raise InputError(f'new index must be between 0 and {65535 - BASE_PORT}')
    return {'listen_port': BASE_PORT + index, 'tag': None, 'debug': False,
            'fmp': None, 'server': None, 'port': None, 'file': None}


def resolve(configs: dict, identifier: str, create: bool = False) -> str:
    if identifier.isascii() and identifier.isdecimal():
        index = str(int(identifier))
        if index in configs:
            return index
        for key, config in configs.items():
            if config['listen_port'] == int(identifier):
                return key
        if create:
            default_config(int(index))
            return index
    else:
        for key, config in configs.items():
            if config.get('tag') == identifier:
                return key
    raise InputError(f'server {identifier!r} not found; use server add -tag NAME to create a named server')


def validate(configs: dict) -> None:
    ports, tags = set(), set()
    for key, config in configs.items():
        listen_port = config.get('listen_port')
        if type(listen_port) is not int or not 1 <= listen_port <= 65535:
            raise InputError('listening port must be between 1 and 65535')
        if listen_port in ports:
            raise InputError(f'listening port {listen_port} is already assigned')
        ports.add(listen_port)
        if str(listen_port) in configs and str(listen_port) != key:
            raise InputError('a listening port cannot equal another server index')
        tag = config.get('tag')
        if tag is not None:
            if (not isinstance(tag, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', tag)
                    or not re.search(r'[A-Za-z_]', tag) or tag.casefold() in VERBS | {'all'}):
                raise InputError('tag must be a nonnumeric name using letters, digits, _, . or -; verbs and all are reserved')
            if tag in tags:
                raise InputError(f'tag {tag!r} is already assigned')
            tags.add(tag)
        for name in ('fmp', 'server', 'file'):
            if config.get(name) is not None and not isinstance(config[name], str):
                raise InputError(f'{name} must be text')
        if config.get('fmp') is not None:
            protocol(config['fmp'])
        if config.get('server') is not None:
            authority(config['server'], config.get('port'))
        port = config.get('port')
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise InputError('target port must be between 1 and 65535')
        if type(config.get('debug', False)) is not bool:
            raise InputError('debug must be true or false')
        # A saved port can override an incoming URL's host without a saved host.
        build_url(Options(url='fmp://example.com/Validation', **target_options(config)))


def target_options(config: dict) -> dict:
    return {name: config.get(name) for name in ('fmp', 'server', 'file', 'port')}
