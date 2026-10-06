"""Opt-in integration tests. Read database identity and write only scratch files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import quote

LIVE_FILE = os.environ.get("FMIDE_LIVE_FILE")


def fm_string(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


@unittest.skipUnless(LIVE_FILE, "set FMIDE_LIVE_FILE=fmIDE to test an open FileMaker database")
class LiveFileMakerTests(unittest.TestCase):
    def test_frontmatter_variables_and_action_script(self):
        with tempfile.TemporaryDirectory(prefix="fmide-cli-test-") as directory:
            output = Path(directory) / "result.json"
            # No records, layouts or schema are changed. ConvertToFileMakerPath
            # makes the scratch path independent of the startup volume's name.
            assignments = '$cli_prefix = "Malmö 🦄 + & = %"'
            parameter = '\n'.join([
                '---', '$cli_suffix = " / done";', '---',
                '[+].Set Variable.$cli_path = == ConvertToFileMakerPath ( ' + fm_string(str(output)) + ' ; PosixPath )',
                '[+].Create Data File = == $cli_path',
                '[+].Open Data File =',
                '[:]..target = "$cli_handle"',
                '[:]..source_file = == $cli_path',
                '[+].Write to Data File =',
                '[:]..file_id = == $cli_handle',
                '[:]..data_source = == JSONSetElement ( "{}" ; [ "file" ; Get ( FileName ) ; JSONString ] ; [ "version" ; $fmide_version ; JSONString ] ; [ "text" ; $cli_prefix & $cli_suffix ; JSONString ] ; [ "variable" ; $cli_probe ; JSONString ] )',
                '[:]..append_line_feed = false',
                '[+].Close Data File = == $cli_handle',
            ])
            base = 'https://fmp26//$/wrong?script=fmIDE&$cli_probe=old&param=' + quote(parameter, safe='')
            args = [sys.executable, '-m', 'fmide_cli', '-url', base,
                    '-fmp', os.environ.get('FMIDE_LIVE_PROTOCOL', 'fmp'), '-file', LIVE_FILE,
                    '-$', 'cli_probe=first', '-$', 'cli_probe=last = + & 🦄',
                    '-frontmatter', assignments]
            result = subprocess.run(args, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            deadline = time.monotonic() + 15
            data = None
            while time.monotonic() < deadline:
                try:
                    data = json.loads(output.read_text(encoding='utf-8-sig'))
                    break
                except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
                    time.sleep(0.1)
            self.assertIsNotNone(data, 'No result: inspect FileMaker for a dialog; do not blindly retry.')
            self.assertEqual(data['file'], LIVE_FILE.removesuffix('.fmp12'))
            self.assertTrue(data['version'], data)
            self.assertEqual(data['text'], 'Malmö 🦄 + & = % / done')
            self.assertEqual(data['variable'], 'last = + & 🦄')
            print('Live FileMaker result: ' + json.dumps(data, ensure_ascii=False))
