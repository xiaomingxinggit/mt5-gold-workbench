import sys
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from gui import state_directory
from mt5_workbench.config import legacy_state_directory
from mt5_workbench.ui.qml_trade_bridge import _records_dir


class StateDirectoryTests(unittest.TestCase):
    def test_source_run_uses_current_user_application_data(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/test/AppData/Local",
                                     "MT5_WORKBENCH_DATA_DIR": ""}):
            expected = Path("C:/Users/test/AppData/Local/MT5Workbench/state/executions")
            self.assertEqual(state_directory("executions"), expected)
            self.assertEqual(_records_dir("executions"), expected)

    def test_packaged_run_uses_same_data_when_executable_moves(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/test/AppData/Local",
                                     "MT5_WORKBENCH_DATA_DIR": ""}):
            for executable in ("C:/Downloads/MT5Workbench.exe", "D:/Apps/MT5Workbench.exe"):
                with patch.object(sys, "executable", executable):
                    self.assertEqual(state_directory("controls"),
                                     Path("C:/Users/test/AppData/Local/MT5Workbench/state/controls"))

    def test_legacy_locations_remain_discoverable(self):
        self.assertEqual(legacy_state_directory(), Path(__file__).resolve().parents[1] / "state")
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "C:/OldApp/MT5Workbench.exe"):
            self.assertEqual(legacy_state_directory(), Path("C:/OldApp/state"))


if __name__ == "__main__":
    unittest.main()
