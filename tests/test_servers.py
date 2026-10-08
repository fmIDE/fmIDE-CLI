"""Isolated server tests; never dispatch to a real FileMaker installation."""
from contextlib import redirect_stderr, redirect_stdout
from http.client import HTTPConnection, HTTPSConnection
import io
import json
import os
from pathlib import Path
import signal
import shutil
import ssl
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from fmide_cli.cli import main
from fmide_cli.server_http import (ForwardingHTTPServer, certificate_fingerprint, control,
                                   handler_class, logger_for, server_ssl_context)
from fmide_cli.server_store import Store, default_config, resolve, validate
from fmide_cli.urls import InputError


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@unittest.skipUnless(os.name == 'posix', 'background server management requires POSIX')
class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, FMIDE_SERVER_HOME=self.temp.name)
        env.start()
        self.addCleanup(env.stop)
        self.store = Store()

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = main(['server', *args])
        return result, out.getvalue(), err.getvalue()

    def test_add_holes_and_reset(self):
        self.assertEqual(self.cli('add', '-tag', 'new')[0], 0)
        self.assertEqual(self.cli('add', '-tag', 'old', '-fmp', '19')[0], 0)
        cfg = self.store.read()
        self.assertEqual(cfg['0']['listen_port'], 43103)
        self.assertTrue(cfg['0']['https'])
        self.assertEqual(cfg['1']['listen_port'], 43104)
        self.assertEqual(cfg['1']['fmp'], 'fmp19')
        self.assertEqual(self.cli('new', 'remove')[0], 0)
        self.assertEqual(self.cli('add', '-tag', 'third')[0], 0)
        self.assertEqual(set(self.store.read()), {'1', '2'})
        self.assertEqual(self.cli('2', 'remove')[0], 0)
        self.assertEqual(self.cli('old', 'remove')[0], 0)
        self.assertEqual(self.cli('add')[0], 0)
        self.assertEqual(set(self.store.read()), {'0'})

    def test_explicit_recreate_hole(self):
        self.cli('add')
        self.cli('add')
        self.cli('0', 'remove')
        self.assertEqual(self.cli('0', 'set', '-tag', 'back')[0], 0)
        self.assertEqual(set(self.store.read()), {'0', '1'})

    def test_resolve_tag_index_and_current_port(self):
        self.cli('add', '-tag', 'old')
        self.assertEqual(self.cli('old', '-listen-port', '45000')[0], 0)
        for identifier in ('old', '0', '45000'):
            self.assertEqual(resolve(self.store.read(), identifier), '0')
        self.assertEqual(self.cli('43103', 'stop')[0], 1)

    def test_tags_ports_and_unknown_commands_are_rejected_without_mutation(self):
        self.cli('add', '-tag', 'new')
        before = self.store.path.read_bytes()
        for tag in ('123', '1.2', '*', 'all', 'start', 'STOP', 'a b', 'new'):
            with self.subTest(tag=tag):
                self.assertEqual(self.cli('add', '-tag', tag)[0], 1)
                self.assertEqual(self.store.path.read_bytes(), before)
        for args in [('add', '-listen-port', '43103'), ('add', '-listen-port', '65536'),
                     ('missing', 'stop'), ('0', 'set', '-fmp', 'https'),
                     ('0', 'set', '-server', '$', '-port', '443'),
                     ('0', 'set', '-tls-cert', 'cert.pem')]:
            self.assertEqual(self.cli(*args)[0], 1)
            self.assertEqual(self.store.path.read_bytes(), before)
        with self.assertRaises(SystemExit):
            self.cli('add', '1', 'start')

    def test_ambiguous_index_port_rejected(self):
        cfg = {'0': default_config(0), '1': default_config(1)}
        cfg['0']['listen_port'] = 1
        with self.assertRaises(InputError):
            validate(cfg)

    def test_set_unset_preserve_and_overview(self):
        self.cli('add', '-tag', 'new', '-fmp', '26', '-file', 'New DB')
        self.cli('add', '-tag', 'old')
        self.assertEqual(self.cli('new', 'set', '-https', 'off')[0], 0)
        self.assertFalse(self.store.read()['0']['https'])
        self.assertEqual(self.cli('new', 'unset', '-https')[0], 0)
        self.assertTrue(self.store.read()['0']['https'])
        self.assertEqual(self.cli('all', 'set', '-debug', 'on')[0], 0)
        self.assertEqual(self.cli('new', 'unset', '-fmp', '-file')[0], 0)
        cfg = self.store.read()['0']
        self.assertIsNone(cfg['fmp'])
        self.assertIsNone(cfg['file'])
        self.assertEqual(cfg['tag'], 'new')
        self.assertTrue(cfg['debug'])
        code, out, err = self.cli('list')
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[0].split()[:3], ['INDEX', 'TAG', 'PORT'])
        self.assertIn('new', out)
        self.assertIn('old', out)
        self.assertEqual(self.cli('all', 'remove')[0], 0)
        self.assertEqual(self.store.read(), {})

    def test_pre_https_settings_keep_the_http_transport(self):
        self.cli('add', '-tag', 'legacy')
        config = self.store.read()
        config['0'].pop('https')
        self.store.save(config)
        code, out, err = self.cli('legacy', 'status')
        self.assertEqual(code, 0, err)
        self.assertIn('Server 0: http://127.0.0.1:43103/', out)

    def test_empty_overview_and_bare_server(self):
        self.assertEqual(self.cli('list')[0], 0)
        self.assertEqual(self.cli()[0], 0)
        self.assertEqual(self.store.read(), {})

    def test_corrupt_settings_are_not_overwritten(self):
        self.store.path.write_text('{broken')
        self.assertEqual(self.cli('add')[0], 1)
        self.assertEqual(self.store.path.read_text(), '{broken')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.cfg = default_config(0)
        self.cfg.update(fmp='fmp19', file='Old DB', server='fm.example.com', port=5003)
        self.store.save({'0': self.cfg})
        self.logger = logger_for(self.store, '0')
        self.urls = []
        self.stop_event = threading.Event()
        self.runtime = {'port': 0, 'token': 'test-secret'}
        self.server = ForwardingHTTPServer(('127.0.0.1', 0), handler_class(
            self.store, '0', self.runtime, self.stop_event, self.logger, self.urls.append))
        self.runtime['port'] = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
        self.temp.cleanup()

    def request(self, path, method='GET', headers=None):
        connection = HTTPConnection('127.0.0.1', self.runtime['port'], timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def forward(self, url, headers=None):
        return self.request('/?' + urlencode({'url': url}), headers=headers)

    def test_welcome_for_browser_and_curl_never_dispatches(self):
        for file in ('Old DB', None):
            self.cfg['file'] = file
            self.store.save({'0': self.cfg})
            for path, accept, content_type in (
                    ('/', 'text/html,application/xhtml+xml,*/*;q=0.8', 'text/html'),
                    ('/?', '*/*', 'text/plain'),
                    ('/', '', 'text/plain'),
                    ('/', 'text/html;q=0', 'text/plain')):
                with self.subTest(file=file, path=path, accept=accept):
                    connection = HTTPConnection('127.0.0.1', self.runtime['port'], timeout=3)
                    try:
                        connection.request('GET', path, headers={'Accept': accept})
                        response = connection.getresponse()
                        body = response.read()
                        self.assertEqual(response.status, 200)
                        self.assertIn(content_type, response.getheader('Content-Type'))
                        self.assertEqual(int(response.getheader('Content-Length')), len(body))
                        self.assertEqual(response.getheader('Vary'), 'Accept')
                        self.assertIn(b'Hello from fmIDE!', body)
                        self.assertIn(str(self.runtime['port']).encode(), body)
                        self.assertIn(b'fmIDE CLI forwarding parameters', body)
                        self.assertIn(b'-file=MyDatabase', body)
                        self.assertNotIn(b'test-secret', body)
                        self.assertNotIn(b'Old DB', body)
                    finally:
                        connection.close()
        self.assertEqual(self.urls, [])
        self.assertNotIn('forward rejected', self.store.log('0').read_text())
        self.assertEqual(self.request('/', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('/', method='POST')[0], 405)
        self.stop_event.set()
        self.assertEqual(self.request('/')[0], 503)

    def test_normal_log_describes_forwarded_action_without_values(self):
        code, _ = self.request('/?' + urlencode({'$layout_name': 'Private Layout', '$fmide_debugger': '1'}))
        self.assertEqual(code, 200)
        log = self.store.log('0').read_text()
        self.assertIn('"things": ["$layout_name"]', log)
        self.assertIn('"$fmide_debugger": "1"', log)
        self.assertNotIn('Private Layout', log)
        self.assertNotIn('Old DB', log)

    def test_listener_startup_does_not_depend_on_reverse_dns(self):
        with patch('socket.getfqdn', side_effect=AssertionError('reverse DNS must not run')):
            with ForwardingHTTPServer(('127.0.0.1', 0), self.server.RequestHandlerClass) as server:
                self.assertEqual(server.server_name, 'localhost')
                self.assertGreater(server.server_port, 0)

    def test_shared_url_builder_preserves_parameters(self):
        status, data = self.forward('https://fmp26//$/New?script=fmIDE&param=a%26b%2B%25&$x=one%20two')
        self.assertEqual(status, 200)
        self.assertTrue(data['accepted'])
        self.assertEqual(self.urls, ['fmp19://fm.example.com:5003/Old%20DB?script=fmIDE&$x=one%20two&param=a%26b%2B%25'])
        self.assertNotIn('param=', self.store.log('0').read_text())

    def test_native_http_parameters_and_settings_unchanged(self):
        before = self.store.path.read_bytes()
        status, data = self.request('/?-file=New&-fmp=26&$layout_name=Home&$fmide_debugger=1')
        self.assertEqual(status, 200)
        self.assertTrue(data['accepted'])
        self.assertEqual(self.urls[-1], 'fmp19://fm.example.com:5003/Old%20DB?script=fmIDE&$layout_name=Home&$fmide_debugger=1')
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.request('/?-$=layout_name=Home&-$=$fmide_debugger=1')[0], 200)
        self.assertEqual(self.urls[-1], self.urls[-2])

    def test_live_settings_and_explicit_debug(self):
        self.cfg.update(fmp='fmp26', server=None, file=None, port=None, debug=True)
        self.store.save({'0': self.cfg})
        self.forward('fmp19://$/New?param=private')
        self.assertEqual(self.urls[-1], 'fmp26://$/New?script=fmIDE&param=private')
        self.assertIn('param=private', self.store.log('0').read_text())

    def test_invalid_requests_never_dispatch(self):
        for url in ('https://evil.example/', 'file:///tmp/file', 'javascript:alert(1)', 'fmp://[broken/DB'):
            self.assertEqual(self.forward(url)[0], 400)
        self.cfg['file'] = None
        self.store.save({'0': self.cfg})
        self.assertEqual(self.forward('fmp://$/')[0], 400)
        for path in ('/?url=', '/?url=a&url=b', '/?url=a&-unsupported=b'):
            self.assertEqual(self.request(path)[0], 400)
        self.assertEqual(self.request('/favicon.ico')[0], 404)
        self.assertEqual(self.request('/?url=' + 'x' * 17000)[0], 414)
        self.assertEqual(self.request('/?url=DB', method='POST')[0], 405)
        self.assertEqual(self.urls, [])

    def test_control_auth_and_browser_isolation(self):
        self.assertEqual(self.request('/_fmide/stop', 'POST')[0], 403)
        self.assertEqual(self.forward('DB', {'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.forward('DB', {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.forward('DB', {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors'})[0], 403)
        self.assertEqual(self.urls, [])
        self.assertEqual(self.forward('DB', {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate'})[0], 200)
        self.assertEqual(control(self.runtime)['token'], self.runtime['token'])
        self.assertTrue(control(self.runtime, 'stop')['stopping'])
        self.assertEqual(self.forward('DB')[0], 503)

    def test_dispatch_error_is_reported(self):
        # Replace the handler factory to inject the normal dispatch failure type.
        def fail(url):
            raise InputError('failure containing secret')
        self.server.RequestHandlerClass = handler_class(self.store, '0', self.runtime, self.stop_event, self.logger, fail)
        code, data = self.forward('DB')
        self.assertEqual(code, 502)
        self.assertNotIn('secret', str(data))
        self.assertNotIn('secret', self.store.log('0').read_text())


@unittest.skipUnless(os.name == 'posix' and shutil.which('openssl'), 'HTTPS certificate test needs POSIX and OpenSSL')
class HTTPSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cert = self.root / 'localhost.pem'
        self.key = self.root / 'localhost-key.pem'
        subprocess.run([
            shutil.which('openssl'), 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(self.key), '-out', str(self.cert), '-days', '1', '-subj', '/CN=localhost',
            '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.store = Store(self.root / 'state')
        self.cfg = default_config(0)
        self.cfg.update(file='Test DB', tls_cert=str(self.cert), tls_key=str(self.key))
        self.store.save({'0': self.cfg})
        self.logger = logger_for(self.store, '0')
        self.urls = []
        self.stop_event = threading.Event()
        self.runtime = {'port': 0, 'token': 'https-test-secret', 'scheme': 'https',
                        'cert_sha256': certificate_fingerprint(str(self.cert))}
        self.server = ForwardingHTTPServer(
            ('127.0.0.1', 0), handler_class(self.store, '0', self.runtime,
                                            self.stop_event, self.logger, self.urls.append),
            ssl_context=server_ssl_context(str(self.cert), str(self.key)))
        self.runtime['port'] = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

    def request(self, path, headers=None):
        connection = HTTPSConnection('127.0.0.1', self.runtime['port'], timeout=3,
                                      context=ssl._create_unverified_context())
        try:
            connection.request('GET', path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_https_forwarding_welcome_origin_and_pinned_control(self):
        status, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'https://localhost:', body)
        self.assertEqual(control(self.runtime)['token'], self.runtime['token'])
        self.assertEqual(self.request('/?-$=layout_name=Home', {
            'Origin': f'https://127.0.0.1:{self.runtime["port"]}'} )[0], 200)
        self.assertEqual(self.urls, ['fmp://$/Test%20DB?script=fmIDE&$layout_name=Home'])
        self.assertEqual(self.request('/', {'Origin': f'http://127.0.0.1:{self.runtime["port"]}'})[0], 403)

    def test_control_rejects_a_changed_certificate_before_sending_token(self):
        with patch('fmide_cli.server_http.HTTPSConnection') as make_connection:
            connection = make_connection.return_value
            connection.sock.getpeercert.return_value = b'changed certificate'
            runtime = dict(self.runtime, cert_sha256='0' * 64)
            with self.assertRaises(InputError):
                control(runtime)
            connection.request.assert_not_called()
            connection.close.assert_called_once()


@unittest.skipUnless(os.name == 'posix', 'background server management requires POSIX')
class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, FMIDE_SERVER_HOME=self.temp.name)
        self.root = Path(__file__).resolve().parents[1]
        self.store = Store(Path(self.temp.name))

    def tearDown(self):
        try:
            self.run_cli('all', 'kill')
            self.run_cli('all', 'remove')
        finally:
            self.temp.cleanup()

    def run_cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, '-m', 'fmide_cli', 'server', *args],
                                env=self.env, cwd=self.root, text=True, capture_output=True, timeout=40)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_multi_server_full_lifecycle_and_tail(self):
        first, second = free_port(), free_port()
        while second == first:
            second = free_port()
        self.run_cli('add', 'start', '-tag', 'new', '-listen-port', str(first))
        self.run_cli('add', 'start', '-tag', 'old', '-listen-port', str(second), '-fmp', '19')
        self.assertEqual(set(self.store.read()), {'0', '1'})
        overview = self.run_cli('list').stdout
        self.assertEqual(overview.count('running'), 2)
        details = self.run_cli('new', 'status').stdout
        self.assertIn('Server 0: https://127.0.0.1:', details)
        self.assertTrue((self.store.root / '0.localhost.pem').is_file())
        self.assertTrue((self.store.root / '0.localhost-key.pem').is_file())
        self.run_cli('all', 'remove', expected=1)
        self.assertEqual(set(self.store.read()), {'0', '1'})
        tail = subprocess.Popen([sys.executable, '-m', 'fmide_cli', 'server', 'new', 'tail'],
                                env=self.env, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(0.3)
            self.run_cli('new', 'stop')  # Tail must not hold the manager lock.
            tail.send_signal(signal.SIGINT)
            out, _ = tail.communicate(timeout=5)
            self.assertIn('listening', out)
        finally:
            if tail.poll() is None:
                tail.kill()
                tail.communicate()
        self.run_cli('new', 'remove')
        self.assertEqual(set(self.store.read()), {'1'})
        self.run_cli(str(second), 'kill')
        self.assertIn('stopped', self.run_cli('old', 'status').stdout)
        self.assertIn('1', self.store.read())
        self.run_cli('old', 'start')
        self.run_cli('all', 'terminate')
        self.assertEqual(self.store.read(), {})
        self.assertTrue(self.store.log('0').exists())
        self.run_cli('add')
        self.assertEqual(set(self.store.read()), {'0'})

    def test_port_change_and_failed_rebind_roll_back(self):
        initial, replacement = free_port(), free_port()
        while replacement == initial:
            replacement = free_port()
        self.run_cli('add', 'start', '-listen-port', str(initial))
        self.run_cli('set', '-listen-port', str(replacement))
        self.assertEqual(self.store.read()['0']['listen_port'], replacement)
        self.assertIn('running', self.run_cli(str(replacement), 'status').stdout)
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            busy = occupied.getsockname()[1]
            self.run_cli('set', '-listen-port', str(busy), expected=1)
            self.assertEqual(self.store.read()['0']['listen_port'], replacement)
            self.assertIn('running', self.run_cli('status').stdout)

    def test_missing_runtime_fields_are_treated_as_stale(self):
        self.run_cli('add')
        self.store.runtime('0').write_text(json.dumps({'pid': os.getpid()}))
        self.assertIn('stopped', self.run_cli('status').stdout)
        self.run_cli('kill')
        self.assertFalse(self.store.runtime('0').exists())

    def test_busy_port_failure_retains_configuration(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            self.run_cli('add', 'start', '-listen-port', str(occupied.getsockname()[1]), expected=1)
        self.assertIn('0', self.store.read())
        self.assertIn('stopped', self.run_cli('status').stdout)
        self.run_cli('start')
        self.assertIn('running', self.run_cli('status').stdout)

    def test_concurrent_adds_are_serialized(self):
        commands = [subprocess.Popen([sys.executable, '-m', 'fmide_cli', 'server', 'add'],
                                    env=self.env, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for _ in range(4)]
        for command in commands:
            out, err = command.communicate(timeout=10)
            self.assertEqual(command.returncode, 0, (out, err))
        self.assertEqual(set(self.store.read()), {'0', '1', '2', '3'})

    def test_stale_runtime_does_not_signal_unrelated_process(self):
        self.run_cli('add')
        self.store.runtime('0').write_text(json.dumps({'pid': os.getpid(), 'port': free_port(), 'token': 'stale'}))
        self.run_cli('kill')
        self.assertFalse(self.store.runtime('0').exists())
        self.assertIn('0', self.store.read())
