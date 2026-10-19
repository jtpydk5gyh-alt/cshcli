import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from cshcli import cli, updater


NEW_WHEEL = "cshcli-next.whl"


class CliUpdateTests(unittest.TestCase):
    @staticmethod
    def newer():
        major, minor, patch = updater.parse_version(updater.current_version())
        return f"{major}.{minor + 1}.{patch}"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = str(Path(self.temp.name))
        patcher = mock.patch.dict(os.environ, {"CSHCLI_HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *arguments, **keywords):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch("builtins.input",
                                                                   **keywords):
            code = cli.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_update_reports_and_changes_nothing(self):
        with mock.patch.object(updater, "newest_remote_version", return_value=self.newer()):
            code, out, err = self.run_cli("update")
        report = json.loads(out)
        self.assertEqual(report["action"], "update")
        self.assertIn("No se ha cambiado nada", err)
        self.assertEqual(code, 0)

    def test_update_never_asks_to_type_anything_without_apply(self):
        with mock.patch.object(updater, "newest_remote_version", return_value=self.newer()):
            with mock.patch("builtins.input") as prompt:
                code, _, _ = self.run_cli("update")
        prompt.assert_not_called()

    def test_a_wrong_typed_version_installs_nothing(self):
        with mock.patch.object(updater, "newest_remote_version", return_value=self.newer()):
            code, _, err = self.run_cli("update", "--apply", return_value="0.0.1")
        self.assertEqual(code, 1)
        self.assertIn("No coincide", err)
        self.assertFalse((Path(self.home) / "update").exists(),
                         "a refused confirmation must not download anything")

    def test_a_network_failure_touches_nothing(self):
        def broken():
            raise updater.UpdateUnavailable("GitHub could not be reached")
        with mock.patch.object(updater, "newest_remote_version", broken):
            code, out, err = self.run_cli("update")
        self.assertEqual(code, 1)
        self.assertEqual(out.strip(), "")
        self.assertIn("No se ha tocado nada", err)

    def test_apply_with_nothing_to_install_says_so_and_does_not_ask(self):
        with mock.patch.object(updater, "newest_remote_version", return_value=None):
            with mock.patch("builtins.input") as prompt:
                code, _, err = self.run_cli("update", "--apply")
        prompt.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("No hay nada que instalar", err)

    def test_apply_when_current_says_so_and_does_not_ask(self):
        with mock.patch.object(updater, "newest_remote_version",
                               return_value=updater.current_version()):
            with mock.patch("builtins.input") as prompt:
                code, _, _ = self.run_cli("update", "--apply")
        prompt.assert_not_called()
        self.assertEqual(code, 0)

    def test_apply_downloads_and_verifies_before_installing(self):
        import hashlib
        payload = b"wheel-bytes"
        digest = hashlib.sha256(payload).hexdigest()
        expected = Path(self.home) / "update" / NEW_WHEEL
        with mock.patch.object(updater, "newest_remote_version", return_value=self.newer()):
            with mock.patch.object(updater, "apply_release") as applier:
                applier.return_value = {"installed": "ok"}
                code, out, _ = self.run_cli("update", "--apply", return_value=self.newer())
        self.assertEqual(code, 0)
        applier.assert_called_once()
        self.assertEqual(applier.call_args[0][0], self.newer())
        self.assertEqual(applier.call_args[0][1], expected.parent)

    def test_apply_refuses_when_the_release_is_not_signed(self):
        def refuse(*arguments, **keywords):
            raise updater.UpdateUnavailable(
                "The release is not signed by this project. Nothing was installed.")
        with mock.patch.object(updater, "newest_remote_version", return_value=self.newer()):
            with mock.patch.object(updater, "apply_release", refuse):
                code, _, err = self.run_cli("update", "--apply", return_value=self.newer())
        self.assertEqual(code, 1)
        self.assertIn("No se instaló", err)
        self.assertIn("not signed", err)

    def test_apply_does_not_start_when_the_confirmation_does_not_match(self):
        with mock.patch.object(updater, "newest_remote_version", return_value=self.newer()):
            with mock.patch.object(updater, "apply_release") as applier:
                code, _, err = self.run_cli("update", "--apply", return_value="0.0.1")
        applier.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("No coincide", err)


if __name__ == "__main__":
    unittest.main()