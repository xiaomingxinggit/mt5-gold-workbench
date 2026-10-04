import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from gui import state_directory


class StateDirectoryTests(unittest.TestCase):
    def test_source_run_keeps_records_in_project(self):
        self.assertEqual(state_directory("executions"),
                         Path(__file__).resolve().parents[1] / "state" / "executions")

    def test_packaged_run_keeps_records_beside_executable(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", r"C:\MT5Workbench\MT5Workbench.exe"):
            self.assertEqual(state_directory("controls"),
                             Path(r"C:\MT5Workbench\state\controls"))


if __name__ == "__main__":
    unittest.main()
