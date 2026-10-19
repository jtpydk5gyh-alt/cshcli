"""The first run, from a real installation, all the way to the chat.

This is the promise the project makes to somebody who has never seen it: run
`cshcli`, answer two questions, and you are talking to your agent. Every
other test drives the code from the inside. This one builds the wheel,
installs it somewhere else, and runs the command a person would run.

It found a real defect: the wizard asked for the provider key through
`getpass`, which reads the console instead of the piped input, so a wizard
driven by anything other than a terminal waited forever for a keypress that
never came.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_wheel(into):
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(into), str(ROOT)],
        capture_output=True, text=True)
    if result.returncode != 0:
        return None
    made = sorted(into.glob("cshcli-*.whl"))
    return made[0] if made else None


class FirstRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.wheel = build_wheel(Path(cls.temp.name))
        if cls.wheel is None:
            raise unittest.SkipTest("no se pudo construir el wheel")
        cls.installed = Path(cls.temp.name) / "instalado"
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--target",
             str(cls.installed), str(cls.wheel)], capture_output=True, text=True)
        if result.returncode != 0:
            raise unittest.SkipTest(f"no se pudo instalar el wheel: {result.stderr[-200:]}")

    def setUp(self):
        self.home = Path(self.temp.name) / f"home-{self._testMethodName}"
        self.environment = dict(os.environ)
        self.environment["PYTHONPATH"] = str(self.installed)
        self.environment["CSHCLI_HOME"] = str(self.home)
        self.environment.pop("CSHCLI_TOKEN", None)
        self.environment.pop("CSHCLI_URL", None)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_cli(self, arguments, entrada):
        return subprocess.run([sys.executable, "-m", "cshcli", *arguments], input=entrada,
                              capture_output=True, text=True, env=self.environment, timeout=90)

    def test_a_new_person_ends_up_talking_to_their_agent(self):
        first = self.run_cli(["start"], "1\nana\n\nopenai\nsk-de-prueba\n")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("1) Sesión", first.stdout)
        self.assertIn("¿Cómo te llamas?", first.stdout)
        self.assertIn("Proyecto 'demo' creado.", first.stdout)
        self.assertIn("Listo.", first.stdout)
        self.assertIn("Escribe 'cshcli'", first.stdout)

    def test_the_second_run_opens_the_chat_without_asking_anything(self):
        self.run_cli(["start"], "1\nana\n\nopenai\nsk-de-prueba\n")
        second = self.run_cli([], "/salir\n")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("ana", second.stdout)
        self.assertIn("demo", second.stdout)
        self.assertIn("openai", second.stdout)
        self.assertIn("/buscar", second.stdout)

    def test_the_wizard_never_waits_forever_for_a_key_that_cannot_be_typed(self):
        first = self.run_cli(["start"], "1\nana\n\nopenai\n")
        self.assertNotEqual(first.returncode, 0,
                            "sin clave no se puede terminar, y hay que decirlo")
        self.assertIn("input_required", first.stderr)
        self.assertIn("cshcli key set", first.stderr,
                      "el motivo debe decir como guardar la clave sin terminal")

    def test_the_key_is_kept_out_of_the_repository(self):
        tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                                 capture_output=True, text=True)
        names = [n for n in tracked.stdout.split("\0") if n]
        offenders = [n for n in names if n.endswith(".key") or n.endswith("password")]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
