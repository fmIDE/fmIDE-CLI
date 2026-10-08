"""Loopback HTTP worker and authenticated lifecycle control."""
from __future__ import annotations

import hmac
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import signal
import socketserver
import threading
from urllib.parse import parse_qs, urlsplit

from .server_store import Store, atomic_json, read_json, target_options
from .system import open_url
from .urls import InputError, Options, build_url

MAX_URL = 16384


def control(runtime: dict, action: str = 'status', timeout: float = 1) -> dict:
    if (not isinstance(runtime, dict) or type(runtime.get('port')) is not int
            or not 1 <= runtime['port'] <= 65535 or not isinstance(runtime.get('token'), str)
            or not runtime['token'] or any(c in runtime['token'] for c in '\r\n')):
        raise InputError('invalid server runtime metadata')
    connection = HTTPConnection('127.0.0.1', runtime['port'], timeout=timeout)
    try:
        connection.request('GET' if action == 'status' else 'POST', '/_fmide/' + action,
                           headers={'Authorization': 'Bearer ' + runtime['token']})
        response = connection.getresponse()
        data = response.read(4096)
        if response.status != 200:
            raise InputError('server control endpoint did not authenticate')
        result = json.loads(data)
        if not isinstance(result, dict) or result.get('token') != runtime['token']:
            raise InputError('server identity changed')
        return result
    finally:
        connection.close()


def process_locked(store: Store, index: str) -> bool:
    import fcntl
    with (store.root / f'{index}.process.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def state(store: Store, index: str) -> tuple[str, dict | None]:
    runtime = read_json(store.runtime(index))
    if runtime:
        try:
            result = control(runtime)
            return ('stopping' if result.get('stopping') else 'running'), runtime
        except (OSError, ValueError, HTTPException):
            pass
    return ('unreachable' if process_locked(store, index) else 'stopped'), runtime


def logger_for(store: Store, index: str) -> logging.Logger:
    logger = logging.getLogger('fmide.server.' + index)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = RotatingFileHandler(store.log(index), maxBytes=1024 * 1024, backupCount=3, encoding='utf-8')
    os.chmod(store.log(index), 0o600)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    return logger


def handler_class(store: Store, index: str, runtime: dict, stopped: threading.Event,
                  logger: logging.Logger, dispatch=open_url):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'fmIDE'
        sys_version = ''

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def log_message(self, format, *args):
            # BaseHTTPRequestHandler logs raw request URLs, which may be sensitive.
            pass

        def reply(self, code: int, data: dict):
            body = json.dumps(data).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def allowed_browser_request(self) -> bool:
            allowed = {f'127.0.0.1:{runtime["port"]}', f'localhost:{runtime["port"]}'}
            if self.headers.get('Host', '') not in allowed:
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + host for host in allowed}:
                return False
            # Permit intentional browser link navigation, not cross-site images/fetches.
            site = self.headers.get('Sec-Fetch-Site')
            return site not in ('cross-site', 'same-site') or self.headers.get('Sec-Fetch-Mode') == 'navigate'

        def do_GET(self):
            self.handle_request('GET')

        def do_POST(self):
            self.handle_request('POST')

        def handle_request(self, method):
            if not self.allowed_browser_request():
                self.reply(403, {'error': 'request must target this localhost server'})
                return
            try:
                path = urlsplit(self.path)
            except ValueError:
                self.reply(400, {'error': 'invalid request URL'})
                return
            if path.path.startswith('/_fmide/'):
                expected = 'Bearer ' + runtime['token']
                if not hmac.compare_digest(self.headers.get('Authorization', '').encode('utf-8'), expected.encode('utf-8')):
                    self.reply(403, {'error': 'authentication required'})
                    return
                action = path.path.removeprefix('/_fmide/')
                if (method, action) not in {('GET', 'status'), ('POST', 'stop'), ('POST', 'kill')}:
                    self.reply(405, {'error': 'unsupported control operation'})
                    return
                if action != 'status':
                    logger.info('%s requested', action)
                    stopped.set()
                self.reply(200, {'token': runtime['token'], 'stopping': stopped.is_set()})
                if action == 'kill':
                    os._exit(0)  # This authenticated worker only; never signal a stored PID.
                return
            if method != 'GET':
                self.reply(405, {'error': 'forwarding uses GET /?url=ENCODED_FMP_URL'})
                return
            if stopped.is_set():
                self.reply(503, {'error': 'server is stopping'})
                return
            if len(self.path) > MAX_URL:
                self.reply(414, {'error': 'forwarding URL is too long'})
                return
            if path.path != '/':
                self.reply(404, {'error': 'use /?url=ENCODED_FMP_URL'})
                return
            try:
                query = parse_qs(path.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2, errors='strict')
                if set(query) != {'url'} or len(query['url']) != 1 or not query['url'][0]:
                    raise InputError('supply exactly one nonempty url query parameter')
                config = store.read().get(index)
                if config is None:
                    raise InputError('server configuration was removed')
                url = build_url(Options(url=query['url'][0], **target_options(config)))
            except (ValueError, OSError, UnicodeError):
                logger.warning('forward rejected: invalid URL or configuration')
                self.reply(400, {'error': 'invalid FMP URL or server settings; include a database name'})
                return
            if config.get('debug'):
                # JSON escaping prevents injected newlines/control characters in logs.
                logger.debug('forward URL %s', json.dumps(url, ensure_ascii=True))
            try:
                dispatch(url)
            except (InputError, OSError):
                logger.error('dispatch failed: check FileMaker URL handler')
                self.reply(502, {'error': 'could not dispatch to FileMaker; check the selected URL handler'})
                return
            logger.info('forward accepted by operating system')
            self.reply(200, {'accepted': True, 'message': 'OS accepted the URL; FileMaker execution is asynchronous'})
    return Handler


class ForwardingHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 16

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)

    def server_bind(self):
        # HTTPServer.server_bind calls getfqdn(), which can block on reverse DNS
        # even for 127.0.0.1 (notably on hosted macOS). This listener is always
        # local, so its name is known and readiness must not depend on DNS.
        socketserver.TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def worker(index: str) -> int:
    import fcntl
    os.umask(0o077)
    store = Store()
    with (store.root / f'{index}.process.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 1
        logger = logger_for(store, index)
        runtime = None
        try:
            config = store.read()[index]
            runtime = {'pid': os.getpid(), 'port': config['listen_port'], 'token': secrets.token_hex(32)}
            stopped = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stopped.set())
            signal.signal(signal.SIGINT, lambda *_: stopped.set())
            with ForwardingHTTPServer(('127.0.0.1', runtime['port']),
                                      handler_class(store, index, runtime, stopped, logger)) as server:
                server.timeout = 0.2
                atomic_json(store.runtime(index), runtime)
                logger.info('server %s listening on 127.0.0.1:%s', index, runtime['port'])
                while not stopped.is_set():
                    server.handle_request()
            logger.info('server %s stopped', index)
            return 0
        except (OSError, ValueError, KeyError) as exc:
            logger.error('worker failed to start or read settings (%s, errno=%s); check port availability and settings.json',
                         type(exc).__name__, getattr(exc, 'errno', None))
            return 1
        finally:
            if runtime and read_json(store.runtime(index)) == runtime:
                store.runtime(index).unlink(missing_ok=True)
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
