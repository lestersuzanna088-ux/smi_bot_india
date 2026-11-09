"""Проверка данных страны (data/) — в отдельном процессе, чтобы не смешивать профиль страны
с эталонным профилем, на котором test_core.py проверяет движок."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CountryData(unittest.TestCase):
    def test_country_data(self):
        env = {k: v for k, v in os.environ.items() if k != "SMI_COUNTRY_FILE"}
        r = subprocess.run([sys.executable, "-m", "unittest", "-v", "tests.country_checks"],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, "\n" + r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
