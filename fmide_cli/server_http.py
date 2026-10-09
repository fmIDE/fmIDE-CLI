"""Loopback HTTP worker and authenticated lifecycle control."""
from __future__ import annotations

from html import escape
import hmac
from http.client import HTTPConnection, HTTPSConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import ssl
import socketserver
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote, urlsplit

from .http_options import request_options
from .log_summary import action_summary
from .server_store import Store, atomic_json, read_json
from .system import open_url
from .urls import InputError, build_url

MAX_URL = 16384
RECEIPT_TTL_SECONDS = 10 * 60
MAX_RECEIPTS = 128


def control(runtime: dict, action: str = 'status', timeout: float = 1) -> dict:
    if (not isinstance(runtime, dict) or type(runtime.get('port')) is not int
            or not 1 <= runtime['port'] <= 65535 or not isinstance(runtime.get('token'), str)
            or not runtime['token'] or any(c in runtime['token'] for c in '\r\n')):
        raise InputError('invalid server runtime metadata')
    scheme = runtime.get('scheme', 'http')
    if scheme not in ('http', 'https'):
        raise InputError('invalid server runtime metadata')
    fingerprint = runtime.get('cert_sha256') if scheme == 'https' else None
    if scheme == 'https' and (not isinstance(fingerprint, str) or len(fingerprint) != 64):
        raise InputError('invalid server runtime metadata')
    if scheme == 'https':
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = HTTPSConnection('127.0.0.1', runtime['port'], timeout=timeout, context=context)
    else:
        connection = HTTPConnection('127.0.0.1', runtime['port'], timeout=timeout)
    try:
        if fingerprint:
            import hashlib
            connection.connect()
            peer = connection.sock.getpeercert(binary_form=True)
            if not hmac.compare_digest(hashlib.sha256(peer).hexdigest(), fingerprint):
                raise InputError('server certificate changed')
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


def server_ssl_context(cert_file: str, key_file: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=os.path.expanduser(cert_file), keyfile=os.path.expanduser(key_file))
    return context


def certificate_fingerprint(cert_file: str) -> str:
    import hashlib
    with open(os.path.expanduser(cert_file), encoding='ascii') as stream:
        der = ssl.PEM_cert_to_DER_cert(stream.read())
    return hashlib.sha256(der).hexdigest()


def default_certificate(store: Store, index: str) -> tuple[str, str]:
    """Create a private, self-signed localhost certificate for a new HTTPS listener."""
    cert = store.root / f'{index}.localhost.pem'
    key = store.root / f'{index}.localhost-key.pem'
    if cert.is_file() and key.is_file():
        return str(cert), str(key)
    executable = shutil.which('openssl') or ('/usr/bin/openssl' if os.path.isfile('/usr/bin/openssl') else None)
    if not executable:
        raise InputError('HTTPS needs OpenSSL to create a local certificate; install OpenSSL or configure -tls-cert and -tls-key')
    with tempfile.TemporaryDirectory(dir=store.root) as temporary:
        temporary = Path(temporary)
        temp_cert, temp_key, config = (temporary / name for name in ('cert.pem', 'key.pem', 'openssl.cnf'))
        config.write_text(
            '[req]\nprompt = no\ndistinguished_name = dn\nx509_extensions = v3_ext\n'
            '[dn]\nCN = localhost\n'
            '[v3_ext]\nsubjectAltName = DNS:localhost,IP:127.0.0.1\n',
            encoding='ascii')
        try:
            subprocess.run([executable, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-days', '825', '-keyout', str(temp_key), '-out', str(temp_cert),
                            '-config', str(config)], check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise InputError('could not create the default HTTPS certificate; configure -tls-cert and -tls-key') from exc
        os.chmod(temp_key, 0o600)
        os.chmod(temp_cert, 0o600)
        os.replace(temp_key, key)
        os.replace(temp_cert, cert)
    return str(cert), str(key)


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
        except (InputError, OSError, ValueError, HTTPException):
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
    receipts = {}
    receipts_lock = threading.Lock()

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
            self.reply_body(code, body, 'application/json; charset=utf-8')

        def reply_body(self, code: int, body: bytes, content_type: str):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Vary', 'Accept')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def redirect(self, location: str):
            self.send_response(303)
            self.send_header('Location', location)
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()

        def is_browser_navigation(self) -> bool:
            return (self.headers.get('Sec-Fetch-Mode') == 'navigate'
                    and 'text/html' in self.headers.get('Accept', '').lower())

        def save_receipt(self, data: dict) -> str:
            now = time.monotonic()
            receipt_id = secrets.token_urlsafe(24)
            with receipts_lock:
                for key, (created, _) in list(receipts.items()):
                    if now - created > RECEIPT_TTL_SECONDS:
                        del receipts[key]
                while len(receipts) >= MAX_RECEIPTS:
                    del receipts[next(iter(receipts))]
                receipts[receipt_id] = (now, data)
            return receipt_id

        def show_receipt(self, receipt_id: str):
            now = time.monotonic()
            with receipts_lock:
                item = receipts.get(receipt_id)
                if item and now - item[0] > RECEIPT_TTL_SECONDS:
                    del receipts[receipt_id]
                    item = None
            if item is None:
                self.reply(404, {'error': 'receipt expired or not found'})
                return
            body = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1">'
                    '<title>fmIDE Gateway result</title><style>'
                    'body{max-width:760px;margin:3rem auto;padding:0 1.5rem;'
                    'font:16px/1.6 system-ui,sans-serif;color:#172b3a;background:#f8fafc}'
                    'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#e8eef3;'
                    'padding:1rem;border-radius:6px}</style></head><body>'
                    '<h1>fmIDE Gateway result</h1><p>The operating system accepted the FileMaker URL. '
                    'FileMaker execution is asynchronous.</p><pre>'
                    + escape(json.dumps(item[1], indent=2))
                    + '</pre><p><a href="/">Gateway home</a></p></body></html>')
            self.reply_body(200, body.encode('utf-8'), 'text/html; charset=utf-8')

        def welcome(self):
            address = f'{runtime.get("scheme", "http")}://localhost:{runtime["port"]}'
            transport = 'HTTPS' if runtime.get('scheme') == 'https' else 'HTTP'
            config = store.read().get(str(index), {})
            page_tag = config.get('tag') or ('default' if str(index) == '0' else 'untagged')
            page_title = f"fmIDE Gateway #{index} '{page_tag}', port {runtime['port']}"
            host = config.get('server')
            host = host.rsplit('@', 1)[-1] if host else '($)'
            headers = ['fmIDE Port', 'Server #', 'Tag', 'fmp', 'server']
            values = [str(runtime['port']), str(index),
                      config.get('tag') or ('(default)' if str(index) == '0' else '(none)'),
                      config.get('fmp') or '(fmp)', host]
            if config.get('file'):
                headers.append('file')
                values.append(config['file'])
            if config.get('port'):
                headers.append('FMP port')
                values.append(str(config['port']))
            # Keep terminal table cells on one line; HTML is escaped separately.
            cells = [' '.join(value.split()).replace('|', '\u00a6') for value in values]
            details = ('| ' + ' | '.join(headers) + ' |\n| '
                       + ' | '.join(['---'] * len(headers)) + ' |\n| '
                       + ' | '.join(cells) + ' |')
            table_html = ('<table><thead><tr>'
                          + ''.join('<th scope="col">' + escape(h) + '</th>' for h in headers)
                          + '</tr></thead><tbody><tr>'
                          + ''.join('<td>' + escape(v) + '</td>' for v in values)
                          + '</tr></tbody></table>')
            action = '[+].Show Custom Dialog.message = == $fmide_version\n[+].Exit Script = == $fmide_version'
            output = '$fmide_on_exit_script_write_data_to_folder_path = Get ( DesktopPath ) & "fmide_api_output_temp/"'
            action_url = address + '/?-file=MyDatabase&param=' + quote(action, safe='')
            output_url = action_url + '&-frontmatter=' + quote(output, safe='')
            text = f"""Hello from fmIDE!

Welcome to the local fmIDE {transport} Gateway: {address}/

{details}

This server provides direct access to fmIDE in FileMaker Pro. It accepts fmIDE API parameters and fmIDE FMP URLs, which it unmangles and opens. fmIDE-CLI forwarding parameters let you override the destination, for example by specifying a server address.

Usage

fmIDE 'Name that Thing' API

`{address}/?-file=MyDatabase&$layout_name=Home`

Specify the target database with `-file` and the layout to show with `$layout_name`.
Replace `MyDatabase` and `Home` with your database and layout names.

fmIDE Action Script API (fmIDEAS)

`{action_url}`

Replace `MyDatabase` with your database name. This example shows the fmIDE version in a dialog, then returns it as the script result. Pass this two-line fmJAML action script as `param`:
`{action}`

To also save the result on your Desktop, add this `-frontmatter` assignment:
`{output}`

The complete URL with Desktop output is:
`{output_url}`

Read `script_result.txt` in `Desktop/fmide_api_output_temp/` after the action completes.

fmIDE FMP URL forwarding

`{address}/?-url=fmp26%3A%2F%2F%24%2FMyDatabase%3Fscript%3DfmIDE%26%24script_name%3DfmIDE%26%24script_step_number%3D2`

Original FMP URL passed as `-url`:
`fmp26://$/MyDatabase?script=fmIDE&$script_name=fmIDE&$script_step_number=2`

Forward an existing FMP URL by passing it as `-url`. Percent-encode the URL as the parameter value.

Parameters

Target File
  `-file`: target database name (unless configured on the server)

fmIDE 'Name that Thing' Parameters
  `$layout_name`: layout to show
  `$script_name`: script to show
  `$script_step_number`: script step to show
  All Name that Thing parameters: https://github.com/fmIDE/fmIDE/wiki/fmIDE-%27Name-that-Thing%27-API-Parameters

fmIDE option variables
  `$fmide_debugger=1` /* Enable the fmIDE debugger. */
  `$fmide_pause_on_error=1` /* Pause when an error occurs. */
  `$fmide_pause_on_condition=1` /* Pause when the condition calculation is true. */
  `$fmide_pause_on_condition_calculation = "$fmide__action_number=4"` /* Pause at action number 4 when conditional pausing is enabled. */

  `$fmide_debug=3` /* 0=none, 3=errors, 5=info, 7=debug */

fmIDE script parameter
  `param=«fmJAML/fmIDEAS»`
  `param=«JSON/fmIDEAS»`

fmIDE CLI forwarding parameters
  `-url`: an FMP URL to (unmangle and) forward
  `-fmp`: FileMaker protocol, for example `fmp26`
  `-server`: FileMaker host
  `-port`: FileMaker host port
  `-file`: target database name (unless configured on the server)
  `-frontmatter`: a separate space to add frontmatter to the fmIDE script parameter.
    Define variables here as FileMaker Let variable definitions,
    or pass them as `$var` parameters.

Notes

Saved server settings override targets supplied in the request.
Use `%20` for spaces and `%26` for ampersands in URL values; literal `+` stays `+`.
FileMaker needs the fmIDE script and the `fmurlscript` extended privilege.
A successful forwarding response means the OS accepted the URL;
it does not confirm that FileMaker finished the action.

Full documentation: https://github.com/fmIDE/fmIDE-CLI/blob/main/docs/servers.md
"""
            # Browsers normally request HTML; curl's */* gets readable text.
            wants_html = False
            for item in self.headers.get('Accept', '').split(','):
                media, *parameters = item.strip().lower().split(';')
                quality = 1.0
                for parameter in parameters:
                    key, separator, value = parameter.strip().partition('=')
                    if key == 'q' and separator:
                        try:
                            quality = float(value)
                        except ValueError:
                            quality = 0.0
                if media == 'text/html' and 0 < quality <= 1:
                    wants_html = True
            if wants_html:
                title, content = text.split('\n', 1)
                content_html = escape(content.strip()).replace(escape(details), '</pre>' + table_html + '<pre>', 1)
                content_html = content_html.replace(escape(address + '/'), '<a href="' + escape(address + '/') + '">' + escape(address + '/') + '</a>', 1)
                wiki_url = 'https://github.com/fmIDE/fmIDE/wiki/fmIDE-%27Name-that-Thing%27-API-Parameters'
                content_html = content_html.replace(wiki_url, '<a href="' + wiki_url + '">fmIDE Wiki — Name that Thing parameters</a>')
                content_html = re.sub(r'`([^`]+)`', r'<code>\1</code>', content_html)
                headings = {
                    2: ('Usage', 'Parameters', 'Notes'),
                    3: ("fmIDE 'Name that Thing' API", 'fmIDE Action Script API (fmIDEAS)',
                        'fmIDE FMP URL forwarding', 'Target File', "fmIDE 'Name that Thing' Parameters",
                        'fmIDE option variables', 'fmIDE script parameter', 'fmIDE CLI forwarding parameters'),
                }
                for level, labels in headings.items():
                    for label in labels:
                        content_html = content_html.replace('\n' + escape(label) + '\n',
                            f'</pre><h{level}>' + escape(label) + f'</h{level}><pre>')
                body = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width, initial-scale=1">'
                        f'<title>{escape(page_title)}</title><style>'
                        'body{max-width:900px;margin:3rem auto;padding:0 1.5rem;'
                        'font-family:system-ui,sans-serif;line-height:1.6;color:#172b3a;background:#f8fafc}'
                        'code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.9em;background:#e8eef3;border-radius:4px;padding:.12em .3em}'
                        'h2{font-size:1.5rem;margin:2rem 0 .75rem}h3{font-size:1.1rem;margin:1.4rem 0 .5rem}'
                        'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}'
                        'table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{text-align:left;padding:.5rem .75rem;border:1px solid #cbd5e1;overflow-wrap:anywhere}'
                        '.welcome-logo{display:block;width:300px;max-width:100%;height:auto}'
                        '</style></head><body>'
                        '<img class="welcome-logo" '
                        'src="https://raw.githubusercontent.com/fmIDE/fmIDE-CLI/main/docs/fmIDE-43103.svg" '
                        'width="600" height="225" alt="fmIDE morphing into port number 43103">'
                        '<h1>' + escape(title) + '</h1><pre>'
                        + content_html + '</pre><p><a href="https://github.com/fmIDE/'
                        'fmIDE-CLI/blob/main/docs/servers.md">Read the full server documentation</a>'
                        '</p></body></html>')
                self.reply_body(200, body.encode('utf-8'), 'text/html; charset=utf-8')
            else:
                self.reply_body(200, text.replace('`', '').encode('utf-8'), 'text/plain; charset=utf-8')

        def allowed_browser_request(self) -> bool:
            allowed = {f'127.0.0.1:{runtime["port"]}', f'localhost:{runtime["port"]}'}
            if self.headers.get('Host', '') not in allowed:
                return False
            origin = self.headers.get('Origin')
            scheme = runtime.get('scheme', 'http')
            if origin and origin not in {scheme + '://' + host for host in allowed}:
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
            if path.path.startswith('/_fmide/receipt/'):
                if method != 'GET' or path.query:
                    self.reply(404, {'error': 'receipt not found'})
                    return
                receipt_id = path.path.removeprefix('/_fmide/receipt/')
                if not re.fullmatch(r'[A-Za-z0-9_-]{32}', receipt_id):
                    self.reply(404, {'error': 'receipt not found'})
                    return
                self.show_receipt(receipt_id)
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
                self.reply(405, {'error': 'forwarding uses GET /?-file=NAME&$layout_name=Home or /?-url=ENCODED_FMP_URL'})
                return
            if stopped.is_set():
                self.reply(503, {'error': 'server is stopping'})
                return
            if len(self.path) > MAX_URL:
                self.reply(414, {'error': 'forwarding URL is too long'})
                return
            if path.path != '/':
                self.reply(404, {'error': 'use /?-file=NAME&$layout_name=Home or /?-url=ENCODED_FMP_URL'})
                return
            if not path.query:
                self.welcome()
                return
            try:
                config = store.read().get(index)
                if config is None:
                    raise InputError('server configuration was removed')
                url = build_url(request_options(path.query, config))
            except (ValueError, OSError, UnicodeError):
                logger.warning('forward rejected: invalid URL or configuration')
                self.reply(400, {'error': 'invalid FMP URL or server settings; include a database name'})
                return
            if config.get('debug'):
                # JSON escaping prevents injected newlines/control characters in logs.
                logger.debug('forward URL %s', json.dumps(url, ensure_ascii=True))
            summary = action_summary(url)
            try:
                dispatch(url)
            except (InputError, OSError):
                logger.error('dispatch failed: check FileMaker URL handler; %s', summary)
                self.reply(502, {'error': 'could not dispatch to FileMaker; check the selected URL handler'})
                return
            logger.info('forward accepted by operating system; %s', summary)
            result = {'accepted': True, 'message': 'OS accepted the URL; FileMaker execution is asynchronous'}
            if self.is_browser_navigation():
                receipt_id = self.save_receipt(result)
                self.redirect('/_fmide/receipt/' + receipt_id)
            else:
                self.reply(200, result)
    return Handler


class ForwardingHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    request_queue_size = 16

    def __init__(self, address, handler, ssl_context=None):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)
        if ssl_context is not None:
            self.socket = ssl_context.wrap_socket(self.socket, server_side=True)

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
            scheme = 'https' if config.get('https', False) else 'http'
            runtime = {'pid': os.getpid(), 'port': config['listen_port'],
                       'token': secrets.token_hex(32), 'scheme': scheme}
            context = None
            if scheme == 'https':
                cert_file, key_file = ((config['tls_cert'], config['tls_key'])
                                       if config.get('tls_cert') else default_certificate(store, index))
                context = server_ssl_context(cert_file, key_file)
                runtime['cert_sha256'] = certificate_fingerprint(cert_file)
            stopped = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stopped.set())
            signal.signal(signal.SIGINT, lambda *_: stopped.set())
            with ForwardingHTTPServer(('127.0.0.1', runtime['port']),
                                      handler_class(store, index, runtime, stopped, logger),
                                      ssl_context=context) as server:
                server.timeout = 0.2
                atomic_json(store.runtime(index), runtime)
                logger.info('server %s listening on %s://127.0.0.1:%s', index, scheme, runtime['port'])
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
