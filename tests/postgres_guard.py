"""One way to ask a test whether a real PostgreSQL is there.

The tests that need a database used to each discover the absence on their
own, and every one of them paid the connection timeout. Six of those turned a
missing server into a suite that took twenty minutes instead of seven, and the
error said "connection timeout" rather than "there is no server", which reads
like a broken product.

The check happens once, in setUp, and says plainly what is missing.
"""

import unittest

REASON = (
    "requires a real PostgreSQL: set CSHCLI_REMOTE_DSN and install "
    "cshcli[remote]. No server was reachable, so nothing about PostgreSQL is "
    "proven here."
)


def require_database(dsn, timeout=10):
    """Skip the calling test unless a real PostgreSQL answers right now."""
    if not dsn:
        raise unittest.SkipTest(REASON)
    try:
        import psycopg
    except ImportError:
        raise unittest.SkipTest(f"{REASON} (no driver)") from None
    try:
        psycopg.connect(dsn, connect_timeout=timeout).close()
    except Exception as error:
        raise unittest.SkipTest(f"{REASON} ({type(error).__name__})") from None
