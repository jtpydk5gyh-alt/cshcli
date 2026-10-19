"""The plan's final verification matrix, tied to the tests that prove it.

The matrix in `docs/superpowers/plans/2026-10-14-cshcli.md` is the contract of
the whole project: these are the things that have to be true. A matrix that
lists requirements nobody checks is a wish list.

Every row that can be proven on one machine names the test that proves it. If
one of those tests is renamed or deleted, this fails and the matrix has to be
updated on purpose rather than drifting.

Two rows cannot be proven here and say so instead of pretending: two machines,
and the integration run that only the CI on the final SHA can provide.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-10-14-cshcli.md"

PROVEN_HERE = {
    "Open source repository": [],
    "Safe invitation": [
        ("tests/test_store.py", "test_concurrent_invitation_acceptance_has_exactly_one_winner"),
        ("tests/test_store.py", "test_invitation_expires_and_is_single_use_and_hash_only"),
    ],
    "Roles": [
        ("tests/test_store.py", "test_viewer_can_read_but_cannot_mutate_or_invite"),
        ("tests/test_store.py", "test_deploy_is_owner_only_and_environment_is_exact"),
    ],
    "Memory without silent loss": [
        ("tests/test_store.py", "test_concurrent_memory_cas_prevents_lost_updates"),
    ],
    "Lease exclusion": [
        ("tests/test_store.py", "test_eleven_agents_across_two_users_have_one_lease_winner"),
        ("tests/test_store.py", "test_resource_conflicts_follow_directory_boundaries_and_windows_case"),
    ],
    "Persistent fences": [
        ("tests/test_store.py", "test_expiry_invalidates_stale_holder_and_fences_survive_restart"),
    ],
    "Local HTTP": [
        ("tests/test_server.py", "test_server_refuses_public_bind"),
        ("tests/test_server.py", "test_authentication_and_browser_requests_are_rejected"),
    ],
    "Personal provider secrets": [
        ("tests/test_store.py", "test_events_are_persistent_project_scoped_and_do_not_contain_secrets"),
        ("tests/test_broker.py", "test_child_environment_strips_api_keys_and_cshcli_secrets"),
    ],
    "Files without real collisions": [
        ("tests/test_git_verify.py", "test_a_path_outside_every_lease_is_refused"),
        ("tests/test_runner.py", "test_a_path_outside_the_lease_is_refused_before_the_write"),
        ("tests/test_runner.py", "test_an_untracked_fence_is_refused"),
    ],
    "Race-free deploy": [
        ("tests/test_deploy.py", "test_eleven_workers_racing_one_environment_change_it_once"),
        ("tests/test_deploy.py", "test_a_failed_health_check_restores_the_previous_digest"),
        ("tests/test_chaos.py", "test_re_running_an_interrupted_deploy_is_idempotent"),
    ],
    "Valid native login": [
        ("tests/test_provider_auth.py", "test_begin_uses_pkce_and_a_one_use_state"),
        ("tests/test_provider_auth.py", "test_revoke_drops_the_token_and_the_account"),
    ],
    "Eleven agents with spend control": [
        ("tests/test_usage.py", "test_eleven_agents_against_a_limit_of_ten"),
        ("tests/test_usage.py", "test_an_exhausted_budget_refuses"),
    ],
}

NEEDS_SOMETHING_ELSE = {
    "Two machines": "a second machine; the remote coordinator over HTTPS with PostgreSQL",
    "Compatible integration": "the CI on the final integrated SHA",
}


def matrix_rows():
    text = PLAN.read_text(encoding="utf-8")
    section = text.split("## Final verification matrix", 1)[1]
    rows = []
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("| ---") or line.startswith("| Requirement"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 3:
            rows.append((cells[0], cells[1], cells[2]))
    return rows


class VerificationMatrixTests(unittest.TestCase):
    def test_the_matrix_is_read_from_the_plan(self):
        rows = matrix_rows()
        self.assertGreaterEqual(len(rows), 14, "la matriz del plan deberia tener sus filas")

    def test_every_row_of_the_matrix_is_accounted_for(self):
        known = set(PROVEN_HERE) | set(NEEDS_SOMETHING_ELSE)
        for requirement, _minimum, _milestone in matrix_rows():
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, known,
                              "toda fila de la matriz dice quien la demuestra")

    def test_every_named_proof_test_still_exists(self):
        for requirement, proofs in PROVEN_HERE.items():
            for module, name in proofs:
                with self.subTest(requirement=requirement, test=name):
                    path = ROOT / module
                    self.assertTrue(path.is_file(), f"{module} no existe")
                    text = path.read_text(encoding="utf-8")
                    self.assertRegex(text, rf"def {re.escape(name)}\(",
                                     f"la prueba que demostraba '{requirement}' ya no existe")

    def test_the_repository_is_the_open_source_one_the_matrix_asks_for(self):
        licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", licence)
        remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                                capture_output=True, text=True, check=False)
        self.assertEqual(remote.returncode, 0, "no hay remoto origin")
        self.assertIn("github.com/jtpydk5gyh-alt/cshcli", remote.stdout)

    def test_the_rows_that_cannot_be_proven_here_say_so_in_the_status(self):
        status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
        self.assertIn("second machine", status)
        self.assertIn("Not published", status)


if __name__ == "__main__":
    unittest.main()
