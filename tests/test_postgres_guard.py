import os
import unittest

from tests.postgres_guard import REASON, require_database


class PostgresGuardTests(unittest.TestCase):
    def test_without_a_dsn_the_test_is_skipped_with_a_reason(self):
        with self.assertRaises(unittest.SkipTest) as caught:
            require_database("")
        self.assertIn("CSHCLI_REMOTE_DSN", str(caught.exception))
        self.assertIn("PostgreSQL", str(caught.exception))

    def test_a_server_that_answers_is_not_skipped(self):
        dsn = os.environ.get("CSHCLI_TEST_DSN", "").strip()
        if not dsn:
            self.skipTest("sin CSHCLI_TEST_DSN no hay servidor con el que probar")
        require_database(dsn)

    def test_an_unreachable_server_is_skipped_and_says_which_error(self):
        with self.assertRaises(unittest.SkipTest) as caught:
            require_database("postgresql://alguien@127.0.0.1:1/nada", timeout=2)
        message = str(caught.exception)
        self.assertIn(REASON.split(".")[0], message)
        self.assertTrue(message.rstrip().endswith(")") or "Error" in message,
                        "el motivo debe decir que error fue")

    def test_the_reason_says_what_was_not_proven(self):
        self.assertIn("proven", REASON)


if __name__ == "__main__":
    unittest.main()
