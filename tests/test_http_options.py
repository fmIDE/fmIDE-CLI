"""HTTP syntax translation and shared URL semantics, without OS dispatch."""
import copy
import unittest
from urllib.parse import quote, urlencode, urlsplit

from fmide_cli.http_options import request_options
from fmide_cli.urls import InputError, Options, build_url, parse_query


def encode(items):
    return urlencode(items, quote_via=quote)


class HTTPOptionsTests(unittest.TestCase):
    def build(self, query, overrides=None):
        return build_url(request_options(query, overrides))

    def test_native_and_cli_variables_match_terminal_command(self):
        native = '-file=MyFile&$layout_name=Home&$fmide_debugger=1'
        cli = '-file=MyFile&-$=layout_name=Home&-$=$fmide_debugger=1'
        expected = build_url(Options(file='MyFile', variables=['layout_name=Home', 'fmide_debugger=1']))
        self.assertEqual(self.build(native), expected)
        self.assertEqual(self.build(cli), expected)

    def test_unchanged_fmp_query_suffix(self):
        suffix = 'script=fmIDE&$script_name=fmIDE&$script_step_range=%221..-1%22&$fmide_debugger=0'
        expected = build_url(Options(url='fmp://$/fmIDE?' + suffix))
        self.assertEqual(self.build('-file=fmIDE&' + suffix), expected)

    def test_shared_core_overlays_script_and_param(self):
        result = build_url(Options(url='fmp://$/DB?script=Old&param=old',
                                  query_parameters=[('script', 'New'), ('param', 'a\nb')]))
        self.assertEqual(dict(parse_query(urlsplit(result).query)), {'script': 'New', 'param': 'a\rb'})

    def test_base_url_explicit_options_and_saved_overrides(self):
        query = encode([('-url', 'https://fmp19//base.example/Old?script=Old&$x=base'),
                        ('-fmp', '20'), ('-server', 'request.example'), ('-port', '5003'),
                        ('-file', 'Request'), ('script', 'New'), ('$x', 'request')])
        expected = 'fmp20://request.example:5003/Request?script=New&$x=request'
        self.assertEqual(self.build(query), expected)
        saved = {'fmp': 'fmp26', 'server': 'saved.example', 'port': 443, 'file': 'Saved'}
        original = copy.deepcopy(saved)
        self.assertEqual(self.build(query, saved), 'fmp26://saved.example:443/Saved?script=New&$x=request')
        self.assertEqual(saved, original)

    def test_mixed_variable_order_last_wins_case_insensitively(self):
        for query, value in [('-file=DB&$x=one&-$=x=two', 'two'),
                             ('-file=DB&-$=$X=one&$x=two', 'two'),
                             ('-file=DB&$x=one&--variable=x=three', 'three')]:
            items = parse_query(urlsplit(self.build(query)).query)
            self.assertEqual([(k.casefold(), v) for k, v in items if k.startswith('$')], [('$x', value)])

    def test_plus_percent_unicode_and_empty_values(self):
        result = self.build('-file=My%20DB&$x=a+b%2Bc%2526%26%3D%E2%98%83&$empty=')
        values = dict(parse_query(urlsplit(result).query))
        self.assertEqual(values['$x'], 'a+b+c%26&=☃')
        self.assertEqual(values['$empty'], '')
        self.assertIn('/My%20DB?', result)

    def test_embedded_url_decodes_each_layer_once(self):
        base = 'fmp://$/DB?param=a%26b%2526+plus'
        for alias in ('url', '-url', '--url'):
            self.assertEqual(self.build(encode([(alias, base)])), build_url(Options(url=base)))

    def test_script_parameter_and_frontmatter(self):
        query = encode([('-file', 'DB'), ('param', '[+].Exit Script = == $x'),
                        ('-frontmatter', '$x = "A+B"'), ('--frontmatter', '$y = 2')])
        expected = build_url(Options(file='DB', parameter='[+].Exit Script = == $x',
                                    frontmatter=['$x = "A+B"', '$y = 2']))
        self.assertEqual(self.build(query), expected)

    def test_saved_file_allows_short_request_without_frontmost_lookup(self):
        self.assertIn('/Saved?', self.build('$layout_name=fmIDE%20Actions', {'file': 'Saved'}))
        with self.assertRaises(InputError):
            self.build('$layout_name=Home')

    def test_empty_script_defaults_and_native_extensions_pass_through(self):
        items = dict(parse_query(urlsplit(self.build('-file=DB&script=&param=&custom=value')).query))
        self.assertEqual(items, {'script': 'fmIDE', 'param': '', 'custom': 'value'})

    def test_double_dash_target_aliases(self):
        self.assertEqual(self.build('--file=DB&--fmp=26&--server=host&--port=1234'),
                         'fmp26://host:1234/DB?script=fmIDE')

    def test_reject_unsupported_or_ambiguous_inputs(self):
        queries = ['', '-file=DB&', '-file=DB&flag', '-file=DB&=value', '-file=DB&$bad%20key=x',
                   '-file=DB&$x=%ZZ', '-file=DB&$x=%FF', 'url=a&-url=b', '-file=A&--file=B',
                   '-url=', '-file=', '-file=DB&-port=zero', '-file=DB&-port=65536',
                   '-file=DB&-$=bad', '-file=DB&--parameter-file=/etc/passwd',
                   '-file=DB&-listen-port=45000', '-file=DB&-debug=on', '-file=DB&-start=1',
                   '-file=DB&--dry-run=1', '-file=DB&%2Dunknown=value',
                   '-file=DB&' + '&'.join('$x=1' for _ in range(256))]
        for query in queries:
            with self.subTest(query=query[:80]), self.assertRaises((InputError, UnicodeError)):
                self.build(query)
