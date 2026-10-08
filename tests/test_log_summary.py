import json
import unittest
from urllib.parse import quote, urlencode

from fmide_cli.log_summary import action_summary


class LogSummaryTests(unittest.TestCase):
    def summary(self, **params):
        return action_summary('fmp26://user:password@private/PrivateDB?' + urlencode(params, quote_via=quote))

    def test_names_and_safe_flags_only(self):
        text = self.summary(**{'$layout_name': 'Secret Layout', '$script_step_range': '1..-1',
                               '$field_name': '', '$table_name': '  ', '$fmide_debugger': '1',
                               '$fmide_debug': 'Get ( Secret )', '$unknown': 'private'})
        self.assertEqual(json.loads(text), {
            'things': ['$layout_name', '$script_step_range'],
            'options': {'$fmide_debugger': '1', '$fmide_debug': '<expression>'}})
        for secret in ('Secret', 'private', 'password', 'PrivateDB', '1..-1'):
            self.assertNotIn(secret, text)

    def test_fmjaml_first_command_excludes_values_and_frontmatter(self):
        text = self.summary(param='---\r$secret = "private";\r---\r// comment\r[1].action_name = "Go to Layout"\r[2].secret=hidden')
        self.assertEqual(json.loads(text), {'fmJAML': '[1].action_name'})

    def test_json_first_action_and_name_that_thing(self):
        for payload in ([{'action_name': 'Go to Layout', 'layout_name': 'Private'}],
                        {'action': {'action_name': 'Go to Layout'}},
                        [{'Go to Layout': {'layout_name': 'Private'}}],
                        {'actions': [{'action_name': 'Go to Layout'}, {'action_name': 'Secret'}]}):
            text = self.summary(param=json.dumps(payload))
            self.assertEqual(json.loads(text)['action'], 'Go to Layout')
            self.assertNotIn('Private', text)
            self.assertNotIn('Secret', text)
        text = self.summary(param='{"layout_name":"Private","fmide_debugger":true}')
        self.assertEqual(json.loads(text)['things'], ['$layout_name'])
        self.assertEqual(json.loads(text)['options'], {'$fmide_debugger': 'true'})

    def test_unrecognized_and_empty_payload(self):
        self.assertEqual(json.loads(self.summary(param='private text')), {'parameter': 'unrecognized'})
        self.assertEqual(json.loads(self.summary(param='')), {})
        self.assertEqual(json.loads(self.summary(param='---\rsecret=private')), {})

    def test_escaped_bounded_and_deep_payloads(self):
        text = self.summary(param=json.dumps({'action_name': 'Go\nInjected\x00' + 'x' * 300}))
        self.assertNotIn('\n', text)
        self.assertNotIn('\x00', text)
        self.assertEqual(len(json.loads(text)['action']), 120)
        text = self.summary(param='[' * 1100 + '0' + ']' * 1100)
        self.assertIn(json.loads(text)['parameter'], ('JSON', 'unrecognized'))
