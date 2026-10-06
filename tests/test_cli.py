from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fmide_cli.cli import main
from fmide_cli.system import frontmost_file, open_url
from fmide_cli.urls import InputError
from tests.test_urls import query


class CLITests(unittest.TestCase):
    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    @patch("fmide_cli.cli.open_url")
    def test_dry_run_does_not_dispatch(self, opener):
        code, out, err = self.run_cli(["-file", "fmIDE", "--dry-run", "-$", "layout_name=Examples"])
        self.assertEqual(code, 0)
        self.assertEqual(query(out.strip())["$layout_name"], "Examples")
        self.assertEqual(err, "")
        opener.assert_not_called()

    @patch("fmide_cli.cli.open_url")
    def test_dispatch_once_and_no_url_logging(self, opener):
        code, out, err = self.run_cli(["-file", "fmIDE", "hello"])
        self.assertEqual((code, out, err), (0, "", ""))
        opener.assert_called_once_with("fmp://$/fmIDE?script=fmIDE&param=hello")

    def test_stdin(self):
        with patch("sys.stdin", io.StringIO("one\ntwo")):
            code, out, _ = self.run_cli(["-file", "fmIDE", "--dry-run", "-"])
        self.assertEqual(code, 0)
        self.assertEqual(query(out.strip())["param"], "one\rtwo")

    def test_parameter_file_utf8_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "script.fmJAML"
            path.write_text("Malmö\n🦄", encoding="utf-8-sig")
            code, out, _ = self.run_cli(["-file", "fmIDE", "--dry-run", "--parameter-file", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(query(out.strip())["param"], "Malmö\r🦄")

    def test_missing_parameter_file(self):
        code, out, err = self.run_cli(["-file", "fmIDE", "--parameter-file", "/missing/fmide-script"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("fmide:", err)
        self.assertNotIn("Traceback", err)

    def test_leading_dash_parameter(self):
        code, out, _ = self.run_cli(["-file", "fmIDE", "--dry-run", "--", "---\n$x=1\n---\nbody"])
        self.assertEqual(code, 0)
        self.assertTrue(query(out.strip())["param"].startswith("---\r"))

    def test_conflicting_parameter_inputs(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main(["--parameter-file", "-", "inline"])
        self.assertEqual(exc.exception.code, 2)

    def test_unknown_option(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main(["--unknown"])
        self.assertEqual(exc.exception.code, 2)

    @patch("fmide_cli.cli.frontmost_file", return_value="fmIDE")
    def test_implicit_frontmost(self, resolver):
        code, out, _ = self.run_cli(["--dry-run", "-fmp", "26"])
        self.assertEqual(code, 0)
        resolver.assert_called_once_with("fmp26")
        self.assertEqual(out.strip(), "fmp26://$/fmIDE?script=fmIDE")

    @patch("fmide_cli.cli.open_url", side_effect=InputError("launch failed"))
    def test_launch_failure(self, _):
        code, out, err = self.run_cli(["-file", "fmIDE"])
        self.assertEqual((code, out, err), (1, "", "fmide: launch failed\n"))


class SystemTests(unittest.TestCase):
    @patch("fmide_cli.system.sys.platform", "darwin")
    @patch("fmide_cli.system.subprocess.run")
    def test_open_uses_argument_list(self, run):
        url = "fmp://$/DB?script=fmIDE&param=%24%28touch%20oops%29"
        open_url(url)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/open", url])
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("fmide_cli.system.sys.platform", "linux")
    def test_other_platform_requires_explicit_file_and_preview(self):
        with self.assertRaises(InputError):
            frontmost_file("fmp")
        with self.assertRaises(InputError):
            open_url("fmp://$/DB")

    @patch("fmide_cli.system.sys.platform", "darwin")
    @patch("fmide_cli.system.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "Actual DB\n"))
    def test_frontmost_success(self, run):
        self.assertEqual(frontmost_file("fmp26"), "Actual DB")
        self.assertEqual(run.call_args.args[0][-1], "fmp26")

    @patch("fmide_cli.system.sys.platform", "darwin")
    @patch("fmide_cli.system.subprocess.run", side_effect=subprocess.TimeoutExpired("osascript", 15))
    def test_frontmost_timeout_has_actionable_error(self, _):
        with self.assertRaisesRegex(InputError, "-file NAME"):
            frontmost_file("fmp26")

    @patch("fmide_cli.system.sys.platform", "darwin")
    @patch("fmide_cli.system.subprocess.run", side_effect=subprocess.CalledProcessError(1, "open"))
    def test_dispatch_failure(self, _):
        with self.assertRaises(InputError):
            open_url("fmp://$/DB")
