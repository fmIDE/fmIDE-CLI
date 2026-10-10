import unittest
from urllib.parse import parse_qsl, urlsplit

from fmide_cli.urls import InputError, Options, build_url, frontmatter, normalize_url


def query(url):
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))


class URLTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(build_url(Options(file="fmIDE")), "fmp://$/fmIDE?script=fmIDE")

    def test_protocol_forms(self):
        for value in ("26", "fmp26", "FMP26", "fmp26://", "fmp26:"):
            with self.subTest(value=value):
                self.assertTrue(build_url(Options(file="fmIDE", fmp=value)).startswith("fmp26://"))

    def test_invalid_protocol(self):
        for value in ("https", "fmp0", "26;open", "fmpabc", ""):
            with self.subTest(value=value), self.assertRaises(InputError):
                build_url(Options(file="fmIDE", fmp=value))

    def test_mangled_protocols(self):
        for value in ("fmp26://$/fmIDE", "fmp26:/$/fmIDE", "fmp26//$/fmIDE",
                      "https://fmp26//$/fmIDE", "http://fmp26://$/fmIDE",
                      "fmp26%3A%2F%2F$/fmIDE", "FMP26:///$/fmIDE"):
            with self.subTest(value=value):
                self.assertEqual(build_url(Options(url=value)), "fmp26://$/fmIDE?script=fmIDE")

    def test_invalid_url_wrapper_preserves_payload(self):
        suffix = '$/Rechnung?script=fmIDE&$custom_function_name=G_J_&param=a+b%26c%3Fd%2520'
        for wrapper in ('http://invalid url/', 'http://invalid%20url/',
                        'https://INVALID%20URL/'):
            for prefix, canonical in (('fmp://', 'fmp://'), ('fmp26//', 'fmp26://'),
                                      ('fmp26%3A%2F%2F', 'fmp26://')):
                with self.subTest(wrapper=wrapper, prefix=prefix):
                    value = wrapper + prefix + suffix
                    self.assertEqual(normalize_url(value), canonical + suffix)
                    self.assertEqual(build_url(Options(url=value)),
                                     build_url(Options(url=canonical + suffix)))

    def test_invalid_url_wrapper_requires_embedded_fmp_target(self):
        for value in ('http://invalid url/$/Rechnung',
                      'http://invalid%20url/https://example.com/DB',
                      'https://example.com/fmp://$/DB',
                      'http://invalid url/fmp0://$/DB',
                      'http://invalid url/fmp://$/DB#fragment'):
            with self.subTest(value=value), self.assertRaises(InputError):
                build_url(Options(url=value))

    def test_thingamajigs(self):
        for value, expected in (
            ("fmGuruDemo&$script_name=Hello%20World", "fmp://$/fmGuruDemo"),
            ("server/fmGuruDemo&$script_name=Hello%20World", "fmp://server/fmGuruDemo"),
            ("fmp19/server/fmGuruDemo&$script_name=Hello%20World", "fmp19://server/fmGuruDemo"),
            ("fmp19//fmGuruDemo&$script_name=Hello%20World", "fmp19://$/fmGuruDemo"),
        ):
            with self.subTest(value=value):
                url = build_url(Options(url=value))
                self.assertTrue(url.startswith(expected + "?"))
                self.assertEqual(query(url), {"script": "fmIDE", "$script_name": "Hello World"})

    def test_all_overrides(self):
        url = build_url(Options(url="fmp19://old:123/Old?script=fmIDE&param=old&option=3",
                                fmp="26", server="new:456", port=789, file="New File", parameter="new"))
        self.assertEqual(urlsplit(url).netloc, "new:789")
        self.assertEqual(urlsplit(url).path, "/New%20File")
        self.assertEqual(urlsplit(url).scheme, "fmp26")
        self.assertEqual(query(url), {"script": "fmIDE", "option": "3", "param": "new"})

    def test_port_override_and_credentials(self):
        url = build_url(Options(url="fmp://user:p%40ss@[::1]:123/DB", port=456))
        self.assertEqual(urlsplit(url).netloc, "user:p%40ss@[::1]:456")

    def test_server_override_does_not_copy_credentials(self):
        url = build_url(Options(url="fmp://user:secret@old/DB", server="new"))
        self.assertEqual(urlsplit(url).netloc, "new")

    def test_reject_invalid_authorities(self):
        for host in ("", "bad host", "host/path", "[broken", "host:abc", "host:70000", "::1", "host:0"):
            with self.subTest(host=host), self.assertRaises(InputError):
                build_url(Options(file="DB", server=host))
        for port in (0, -1, 65536):
            with self.subTest(port=port), self.assertRaises(InputError):
                build_url(Options(file="DB", server="host", port=port))
        with self.assertRaises(InputError):
            build_url(Options(file="DB", port=123))

    def test_variable_replacement_case_insensitive_and_last_wins(self):
        url = build_url(Options(url="fmp://$/DB?script=fmIDE&$layout_name=a&$LAYOUT_NAME=b&option=3",
                                variables=["layout_name=c", "$layout_name=d", "field_name=Table::Field"]))
        pairs = parse_qsl(urlsplit(url).query)
        self.assertEqual([v for k, v in pairs if k.casefold() == "$layout_name"], ["d"])
        self.assertEqual(query(url)["$field_name"], "Table::Field")
        self.assertEqual(query(url)["option"], "3")

    def test_empty_values_and_embedded_equals(self):
        url = build_url(Options(file="DB", parameter="", variables=["foo=", "bar=a=b=c"]))
        self.assertEqual(query(url), {"script": "fmIDE", "param": "", "$foo": "", "$bar": "a=b=c"})

    def test_variable_validation(self):
        for assignment in ("foo", "=bar", "$$foo=bar", "foo&bar=x", "foo bar=x"):
            with self.subTest(assignment=assignment), self.assertRaises(InputError):
                build_url(Options(file="DB", variables=[assignment]))

    def test_unicode_and_reserved_characters_round_trip(self):
        text = 'Malmö 🦄 + & = ? # % / " $(touch nope)'
        url = build_url(Options(file=text, parameter=text, variables=["test=" + text]))
        from urllib.parse import unquote
        self.assertEqual(unquote(urlsplit(url).path[1:]), text)
        self.assertEqual(query(url)["param"], text)
        self.assertEqual(query(url)["$test"], text)
        self.assertNotIn(" ", url)

    def test_no_double_encoding_and_plus_is_literal(self):
        url = build_url(Options(url="fmp://$/My%20File?script=fmIDE&param=a+b%26c%2520"))
        self.assertEqual(query(url)["param"], "a+b&c%20")
        self.assertEqual(urlsplit(url).path, "/My%20File")

    def test_existing_custom_script_is_preserved(self):
        self.assertEqual(query(build_url(Options(url="fmp://$/DB?script=Custom")))["script"], "Custom")

    def test_missing_file_fails(self):
        for options in (Options(), Options(file=""), Options(url="fmp26://$/")):
            with self.subTest(options=options), self.assertRaisesRegex(InputError, "-file NAME"):
                build_url(options)

    def test_reject_other_urls_and_fragments(self):
        for value in ("https://example.com/DB", "javascript:evil", "file:///tmp/DB", "fmp://$/DB#fragment"):
            with self.subTest(value=value), self.assertRaises(InputError):
                build_url(Options(url=value))

    def test_frontmatter_new_and_line_endings(self):
        self.assertEqual(frontmatter("action\r\nnext\nlast", ["$x = 1"]),
                         "---\r$x = 1\r---\raction\rnext\rlast")

    def test_frontmatter_prepend_with_separator(self):
        self.assertEqual(frontmatter("---\n$old = 2;\n---\nbody", ["$new = 1"]),
                         "---\r$new = 1\r;\r$old = 2;\r---\rbody")

    def test_frontmatter_repeated_and_comment_separator(self):
        result = frontmatter("body", ["$x = 1;", "$y = 2 // comment", "$z = 3"])
        self.assertEqual(result, "---\r$x = 1;\r$y = 2 // comment\r;\r$z = 3\r---\rbody")

    def test_frontmatter_unclosed(self):
        with self.assertRaises(InputError):
            frontmatter("---\n$x=1\nbody", ["$y=2"])

    def test_frontmatter_url_parameter(self):
        url = build_url(Options(url="fmp://$/DB?param=body", frontmatter=["$x=1"]))
        self.assertEqual(query(url)["param"], "---\r$x=1\r---\rbody")

    def test_short_uri_host_with_port(self):
        self.assertEqual(build_url(Options(url="host:5003/DB")), "fmp://host:5003/DB?script=fmIDE")

    def test_control_characters_rejected(self):
        with self.assertRaises(InputError):
            build_url(Options(url="fmp://$/DB?param=line\nbreak"))

    def test_script_precedes_variables(self):
        url = build_url(Options(url="DB&$layout_name=Example"))
        self.assertEqual(url, "fmp://$/DB?script=fmIDE&$layout_name=Example")

    def test_frontmatter_terminated_before_comment(self):
        result = frontmatter("---\n$y=2\n---\nbody", ['$x="//;"; // comment'])
        self.assertEqual(result, '---\r$x="//;"; // comment\r$y=2\r---\rbody')

    def test_frontmatter_comment_markers_inside_string(self):
        result = frontmatter("body", ['$x="//;"', '$y="/*;*/"', '$z=3'])
        self.assertEqual(result, '---\r$x="//;"\r;\r$y="/*;*/"\r;\r$z=3\r---\rbody')
