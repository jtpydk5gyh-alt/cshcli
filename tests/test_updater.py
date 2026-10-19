import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from cshcli.updater import (ARCHIVE_ROOT, UpdateUnavailable, compare,
                             fetch_checksums, install, newest_remote_version,
                             parse_version, select_wheel, verify,
                             verify_signature)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *arguments):
        self.close()
        return False


def opener_for(body: bytes, status: int = 200):
    def opener(request, timeout=None):
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "no", {}, None)
        return FakeResponse(body)
    return opener


class VersionTests(unittest.TestCase):
    def test_a_normal_version_reads(self):
        self.assertEqual(parse_version("0.2.0"), (0, 2, 0))
        self.assertEqual(parse_version("v1.10.3"), (1, 10, 3))

    def test_nonsense_is_refused(self):
        for value in ("main", "0.2", "0.2.0.1", "0.2.x", "", None, 2):
            with self.subTest(value=value):
                with self.assertRaises(UpdateUnavailable):
                    parse_version(value)


class RemoteTests(unittest.TestCase):
    def test_no_published_release_reports_none(self):
        self.assertIsNone(newest_remote_version(opener_for(b"", status=404)))

    def test_a_release_returns_its_tag(self):
        body = json.dumps({"tag_name": "v0.3.0"}).encode()
        self.assertEqual(newest_remote_version(opener_for(body)), "v0.3.0")

    def test_a_network_failure_is_not_an_update(self):
        def broken(request, timeout=None):
            raise urllib.error.URLError("no route")
        with self.assertRaises(UpdateUnavailable):
            newest_remote_version(broken)

    def test_a_json_body_that_is_not_json_is_refused(self):
        with self.assertRaises(UpdateUnavailable):
            newest_remote_version(opener_for(b"<html>nope</html>"))


class CompareTests(unittest.TestCase):
    def test_the_same_version_is_current(self):
        report = compare("0.2.0", "v0.2.0")
        self.assertEqual(report["action"], "current")

    def test_an_older_install_is_an_update(self):
        self.assertEqual(compare("0.1.0", "v0.2.0")["action"], "update")

    def test_a_newer_install_is_ahead_and_says_why(self):
        report = compare("0.3.0", "v0.2.0")
        self.assertEqual(report["action"], "ahead")
        self.assertIn("main", report["detail"])

    def test_no_release_means_unknown_and_warns_about_main(self):
        report = compare("0.2.0", None)
        self.assertEqual(report["action"], "unknown")
        self.assertIn("main", report["detail"])

    def test_an_unreadable_remote_version_is_unknown_not_current(self):
        self.assertEqual(compare("0.2.0", "nightly")["action"], "unknown")

    def test_the_report_never_promises_anything_by_default(self):
        for published in (None, "v0.2.0", "v0.3.0", "v0.1.0", "garbage"):
            with self.subTest(published=published):
                report = compare("0.2.0", published)
                self.assertNotIn(report["action"], ("installing", "installing_anything"))

    def test_without_a_release_the_install_would_come_from_main(self):
        self.assertTrue(compare("0.2.0", None)["from_main"])

    def test_with_a_release_the_install_comes_from_that_release(self):
        for published in ("v0.2.0", "v0.3.0", "garbage"):
            with self.subTest(published=published):
                self.assertFalse(compare("0.2.0", published)["from_main"],
                                 "instalar desde la release, no desde la cabeza de main")


class ChecksumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_a_wheel_file_verifies(self):
        target = self.root / "cshcli-0.2.0.whl"
        target.write_bytes(b"contents")
        digest = hashlib.sha256(b"contents").hexdigest()
        self.assertTrue(verify(target, digest))
        self.assertTrue(verify(target, digest.upper()))

    def test_a_tampered_file_does_not_verify(self):
        target = self.root / "cshcli-0.2.0.whl"
        target.write_bytes(b"contents")
        digest = hashlib.sha256(b"contents").hexdigest()
        target.write_bytes(b"tampered")
        self.assertFalse(verify(target, digest))

    def test_checksums_are_parsed(self):
        body = ("f476879a85e83745c9b36ebe54ee4b6a0ddbed7e9bad4e78f18b5105b36b8fe6  "
                "cshcli-0.2.0-py3-none-any.whl\n"
                "short  nonsense.txt\n\n").encode()
        parsed = fetch_checksums(ARCHIVE_ROOT.replace("main.zip", "SHA256SUMS"),
                                 opener_for(body))
        self.assertEqual(list(parsed), ["cshcli-0.2.0-py3-none-any.whl"])

    def test_a_download_failure_is_refused(self):
        def broken(request, timeout=None):
            raise urllib.error.URLError("no route")
        with self.assertRaises(UpdateUnavailable):
            fetch_checksums("https://example.invalid/SHA256SUMS", broken)

    def test_installing_a_mismatch_removes_the_file(self):
        target = self.root / "cshcli-0.2.0.whl"
        target.write_bytes(b"tampered")
        with self.assertRaises(UpdateUnavailable) as caught:
            install(target, hashlib.sha256(b"contents").hexdigest())
        self.assertIn("nothing was installed", str(caught.exception))
        self.assertFalse(target.exists(), "a failed verification must leave no file behind")

    def test_installing_without_a_checksum_is_refused(self):
        target = self.root / "cshcli-0.2.0.whl"
        target.write_bytes(b"contents")
        with self.assertRaises(UpdateUnavailable):
            install(target, "")


class SignatureGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "SHA256SUMS"
        self.target.write_text("a" * 64 + "  cshcli-0.2.0.whl\n", encoding="utf-8")
        self.signature = self.root / "SHA256SUMS.minisig"
        self.public = self.root / "release.pub"

    def test_without_a_signer_the_signature_cannot_be_verified(self):
        with mock.patch("cshcli.updater.find_signer", return_value=None):
            verdict = verify_signature(self.target, self.signature, self.public)
        self.assertFalse(verdict["valid"])
        self.assertIn("minisign", verdict["detail"])

    def test_without_the_public_key_the_signature_cannot_be_verified(self):
        verdict = verify_signature(self.target, self.signature,
                                   self.root / "no-existe.pub", signer="minisign")
        self.assertFalse(verdict["valid"])
        self.assertIn("public key", verdict["detail"])

    def test_without_a_signature_file_the_release_cannot_be_trusted(self):
        self.public.write_text("untrusted comment: minisign public key 5BECC463E66EA9A4\n"
                               "RWSkqW7mY8TsWwxeoiTSEHYJrTWUbthX8y1Kbnf8fZPW3smL3zue+nXl\n",
                               encoding="utf-8")
        verdict = verify_signature(self.target, self.root / "no-existe.minisig",
                                   self.public, signer="minisign")
        self.assertFalse(verdict["valid"])
        self.assertIn("no signature", verdict["detail"])


class WheelSelectionTests(unittest.TestCase):
    def test_the_wheel_for_this_interpreter_is_preferred(self):
        digests = {"cshcli-1.0.0-cp312-cp312-win_amd64.whl": "a" * 64,
                   "cshcli-1.0.0-py3-none-any.whl": "b" * 64}
        chosen = select_wheel(digests)
        self.assertTrue(chosen.endswith(".whl"))

    def test_a_universal_wheel_is_chosen_when_there_is_no_built_one(self):
        digests = {"cshcli-1.0.0.tar.gz": "a" * 64,
                   "cshcli-1.0.0-py3-none-any.whl": "b" * 64}
        self.assertEqual(select_wheel(digests), "cshcli-1.0.0-py3-none-any.whl")

    def test_a_release_without_a_wheel_is_refused(self):
        with self.assertRaises(UpdateUnavailable):
            select_wheel({"cshcli-1.0.0.tar.gz": "a" * 64})


if __name__ == "__main__":
    unittest.main()