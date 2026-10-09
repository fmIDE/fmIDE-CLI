from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fmide_cli.cli import main
from fmide_cli.system import open_url
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

    @patch("fmide_cli.cli.open_url")
    def test_no_arguments_print_usage_without_accessing_filemaker(self, opener):
        code, out, err = self.run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("usage: fmide", out)
        self.assertIn("-file", out)
        self.assertEqual(err, "")
        opener.assert_not_called()

    def test_missing_database_requires_explicit_target(self):
        for args in (["--dry-run"], ["-fmp", "26", "--dry-run"], ["-url", "fmp26://$/"]):
            with self.subTest(args=args):
                code, out, err = self.run_cli(args)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertIn("specify -file NAME or include it in -url", err)

    @patch("fmide_cli.cli.shutil.which", return_value="/opt/homebrew/bin/brew")
    @patch("fmide_cli.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0))
    def test_brew_upgrade_targets_the_fmide_formula(self, run, _):
        code, out, err = self.run_cli(["brew", "upgrade"])
        self.assertEqual(code, 0)
        self.assertIn("brew upgrade fmide/cli/fmide", out)
        self.assertIn("fmide --version", out)
        self.assertEqual(err, "")
        run.assert_called_once_with(
            ["/opt/homebrew/bin/brew", "upgrade", "fmide/cli/fmide"], check=False)

    @patch("fmide_cli.cli.shutil.which", return_value=None)
    @patch("fmide_cli.cli.subprocess.run")
    def test_brew_upgrade_reports_missing_homebrew(self, run, _):
        code, out, err = self.run_cli(["brew", "upgrade"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("not found on PATH", err)
        run.assert_not_called()

    def test_brew_rejects_unknown_subcommands(self):
        code, out, err = self.run_cli(["brew", "install"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("usage: fmide brew upgrade", err)

    @patch("fmide_cli.cli.brew_upgrade", return_value=0)
    @patch("fmide_cli.cli.is_homebrew_install", return_value=True)
    @patch("fmide_cli.cli.latest_release_version")
    def test_update_uses_brew_for_homebrew_install(self, latest, _, brew):
        code, out, err = self.run_cli(["update"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("managed by Homebrew", out)
        brew.assert_called_once_with()
        latest.assert_not_called()

    @patch("fmide_cli.cli.latest_release_version", return_value="99.0.0")
    @patch("fmide_cli.cli.is_homebrew_install", return_value=False)
    def test_update_reports_new_release_without_self_modifying(self, _, latest):
        code, out, err = self.run_cli(["update"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("latest stable release is v99.0.0", out)
        self.assertIn("same method you used to install it", out)
        self.assertIn(".venv/bin/python -m pip install .", out)
        latest.assert_called_once_with()

    @patch("fmide_cli.cli.latest_release_version", return_value="0.4.4")
    @patch("fmide_cli.cli.is_homebrew_install", return_value=False)
    def test_update_reports_current_version(self, _, latest):
        code, out, err = self.run_cli(["update"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("already have the latest release", out)
        latest.assert_called_once_with()

    @patch("fmide_cli.cli.latest_release_version", side_effect=OSError("offline"))
    @patch("fmide_cli.cli.is_homebrew_install", return_value=False)
    def test_update_offline_gives_release_link_and_install_guidance(self, _, latest):
        code, out, err = self.run_cli(["update"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Could not check the latest GitHub release", out)
        self.assertIn("github.com/fmIDE/fmIDE-CLI/releases", out)
        self.assertIn("same method you used to install it", out)
        latest.assert_called_once_with()

    def test_update_help_and_unknown_arguments(self):
        code, out, err = self.run_cli(["update", "--help"])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("usage: fmide update", out)
        code, out, err = self.run_cli(["update", "--force"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("usage: fmide update", err)

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
            open_url("fmp://$/DB")

    @patch("fmide_cli.system.sys.platform", "darwin")
    @patch("fmide_cli.system.subprocess.run", side_effect=subprocess.CalledProcessError(1, "open"))
    def test_dispatch_failure(self, _):
        with self.assertRaises(InputError):
            open_url("fmp://$/DB")
