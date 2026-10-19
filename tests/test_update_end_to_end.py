import hashlib
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
from cshcli import updater

MINISIGN = Path(os.path.expanduser("~")) / "cshcli-tools" / "bin" / \
    "minisign-win64" / "x86_64" / "minisign.exe"
TAG = "v9.9.9"
WHEEL = "cshcli-9.9.9-py3-none-any.whl"
OTHER = "cshcli-9.9.9.tar.gz"


def minisign():
    if MINISIGN.exists():
        return str(MINISIGN)
    found = shutil.which("minisign")
    if found:
        return found
    return None


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *arguments):
        pass


class ReleaseEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.signer = minisign()
        if not self.signer:
            self.skipTest("requires minisign")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.served = self.root / "served"
        self.release = self.served / TAG
        self.release.mkdir(parents=True)
        self.target = self.root / "update"

        self.wheel_bytes = b"a real wheel would be a zip, the bytes are what matter"
        (self.release / WHEEL).write_bytes(self.wheel_bytes)
        (self.release / OTHER).write_bytes(b"source tarball")
        digest = hashlib.sha256(self.wheel_bytes).hexdigest()
        (self.release / updater.CHECKSUMS_NAME).write_text(
            f"{digest}  {WHEEL}\n", encoding="utf-8")

        self.keys = self.root / "keys"
        self.keys.mkdir()
        self.public = self.keys / "release.pub"
        self.private = self.keys / "release.key"
        self.password = "clave-de-prueba"
        environment = dict(os.environ)
        environment["MINISIGN_PASSWORD"] = self.password
        generated = subprocess.run(
            [self.signer, "-G", "-W", "-p", str(self.public), "-s", str(self.private)],
            capture_output=True, text=True, env=environment)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.sign()

        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), lambda *a, **k: QuietHandler(*a, directory=str(self.served), **k))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.installed = []

    def sign(self, target=None):
        target = target or (self.release / updater.CHECKSUMS_NAME)
        environment = dict(os.environ)
        environment["MINISIGN_PASSWORD"] = self.password
        result = subprocess.run(
            [self.signer, "-S", "-W", "-m", str(target), "-s", str(self.private),
             "-x", str(target) + ".minisig"],
            capture_output=True, text=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)

    def fake_pip(self, command):
        self.installed.append(command)
        class Result:
            returncode = 0
            stderr = ""
        return Result()

    def apply(self, **keywords):
        arguments = {"public_key": self.public, "signer": self.signer,
                     "runner": self.fake_pip, "assets": self.base}
        arguments.update(keywords)
        return updater.apply_release(TAG, self.target, **arguments)

    def test_a_signed_release_installs_its_wheel(self):
        result = self.apply()
        self.assertTrue(result["signature"]["verified"])
        self.assertEqual(result["wheel"], WHEEL)
        self.assertEqual(len(self.installed), 1)
        self.assertIn(WHEEL, self.installed[0][-1])
        installed = Path(self.installed[0][-1])
        self.assertTrue(installed.is_file())
        self.assertEqual(installed.read_bytes(), self.wheel_bytes)

    def test_the_checksum_file_and_the_signature_are_downloaded_first(self):
        self.apply()
        for name in (updater.CHECKSUMS_NAME, updater.SIGNATURE_NAME, WHEEL):
            self.assertTrue((self.target / name).is_file(), name)

    def test_a_release_without_a_signature_installs_nothing(self):
        (self.release / updater.SIGNATURE_NAME).unlink()
        with self.assertRaises(updater.UpdateUnavailable) as caught:
            self.apply()
        self.assertIn("carries no signature", str(caught.exception))
        self.assertEqual(self.installed, [])

    def test_a_checksum_file_that_was_altered_installs_nothing(self):
        path = self.release / updater.CHECKSUMS_NAME
        path.write_text("0" * 64 + "  " + WHEEL + "\n", encoding="utf-8")
        with self.assertRaises(updater.UpdateUnavailable) as caught:
            self.apply()
        self.assertIn("not signed", str(caught.exception))
        self.assertEqual(self.installed, [])

    def test_a_wheel_that_does_not_match_the_signed_checksum_installs_nothing(self):
        (self.release / WHEEL).write_bytes(b"a different wheel")
        with self.assertRaises(updater.UpdateUnavailable) as caught:
            self.apply()
        self.assertIn("checksum does not match", str(caught.exception))
        self.assertEqual(self.installed, [])

    def test_a_signature_from_another_key_installs_nothing(self):
        other = self.root / "otra.key"
        other_public = self.root / "otra.pub"
        environment = dict(os.environ)
        environment["MINISIGN_PASSWORD"] = self.password
        subprocess.run([self.signer, "-G", "-W", "-p", str(other_public),
                        "-s", str(other)], capture_output=True, text=True,
                       env=environment)
        environment["MINISIGN_PASSWORD"] = self.password
        subprocess.run([self.signer, "-S", "-W", "-m",
                        str(self.release / updater.CHECKSUMS_NAME), "-s", str(other),
                        "-x", str(self.release / updater.SIGNATURE_NAME)],
                       capture_output=True, text=True, env=environment)
        with self.assertRaises(updater.UpdateUnavailable) as caught:
            self.apply()
        self.assertIn("not signed", str(caught.exception))
        self.assertEqual(self.installed, [])

    def test_without_a_signer_nothing_is_installed(self):
        with mock.patch.object(updater, "find_signer", return_value=None):
            with self.assertRaises(updater.UpdateUnavailable) as caught:
                self.apply(signer=None)
        self.assertIn("not signed", str(caught.exception))
        self.assertEqual(self.installed, [])

    def test_the_wheel_is_chosen_and_not_whatever_sorts_first(self):
        digests = {OTHER: "a" * 64, "aaa-first.whl": "b" * 64, WHEEL: "c" * 64}
        self.assertEqual(updater.select_wheel(digests), WHEEL)

    def test_a_release_without_any_wheel_is_refused(self):
        with self.assertRaises(updater.UpdateUnavailable):
            updater.select_wheel({OTHER: "a" * 64})


class ProjectKeyTests(unittest.TestCase):
    def test_the_key_that_trusts_the_project_ships_inside_the_package(self):
        key = Path(updater.__file__).with_name("release.pub")
        self.assertTrue(key.is_file(),
                        "el actualizador necesita la clave publica dentro del paquete")
        lines = key.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("5BECC463E66EA9A4", lines[0])

    def test_the_key_is_declared_as_package_data_so_it_ships_in_the_wheel(self):
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8")
        self.assertIn("[tool.setuptools.package-data]", pyproject)
        self.assertIn('cshcli = ["release.pub"]', pyproject)


if __name__ == "__main__":
    unittest.main()
