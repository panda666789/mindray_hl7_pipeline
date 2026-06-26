"""Tests for dashboard data loading."""

import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pandas  # noqa: F401
    import streamlit  # noqa: F401
except ModuleNotFoundError:
    pandas = None
    streamlit = None

DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "apps" / "dashboard"
sys.path.insert(0, str(DASHBOARD_DIR))


@unittest.skipIf(pandas is None or streamlit is None, "dashboard dependencies not installed")
class DashboardDataLoaderTests(unittest.TestCase):
    def test_segmented_camera_files_mark_session_as_recording(self):
        from data_loader import scan_sessions

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "patient1" / "record1"
            camera = session / "Camera1"
            camera.mkdir(parents=True)
            (camera / "timestamps_seg001.csv").write_text(
                "frame,timestamp,capture_timestamp,video_timestamp,segment\n"
                "0,1000,1000,1000,1\n",
                encoding="utf-8",
            )
            (camera / "video_seg001.avi").write_bytes(b"video")

            sessions = scan_sessions(tmp)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["name"], str(Path("patient1") / "record1"))


if __name__ == "__main__":
    unittest.main()
