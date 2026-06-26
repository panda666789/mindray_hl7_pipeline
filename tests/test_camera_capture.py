"""Tests for camera timing and selection helpers."""

import sys
import unittest
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parents[1] / "apps" / "client"
sys.path.insert(0, str(CLIENT_DIR))

from camera_capture import camera_roles_from_selection, camera_timestamp_row, stable_frame_timestamp


class CameraCaptureTests(unittest.TestCase):
    def test_stable_frame_timestamp_uses_video_frame_index(self):
        self.assertAlmostEqual(stable_frame_timestamp(1000.0, 0, 30.0), 1000.0)
        self.assertAlmostEqual(stable_frame_timestamp(1000.0, 30, 30.0), 1001.0)
        self.assertAlmostEqual(stable_frame_timestamp(1000.0, 45, 30.0), 1001.5)

    def test_camera_timestamp_row_keeps_capture_and_stable_video_times(self):
        row = camera_timestamp_row(
            frame_index=2,
            capture_timestamp=2000.5,
            segment_start_timestamp=1000.0,
            segment=1,
            fps=30.0,
        )

        self.assertEqual(row["frame"], 2)
        self.assertAlmostEqual(row["timestamp"], 2000.5)
        self.assertAlmostEqual(row["capture_timestamp"], 2000.5)
        self.assertAlmostEqual(row["video_timestamp"], 1000.0 + 2 / 30.0)
        self.assertEqual(row["segment"], 1)

    def test_camera_roles_follow_selected_camera_order(self):
        cameras = [
            (0, "Camera 0 (MSMF 640x480)"),
            (1, "Camera 1 (MSMF 640x480)"),
            (2, "Camera 2 (MSMF 640x480)"),
        ]

        roles = camera_roles_from_selection(
            cameras,
            ["Camera 2 (MSMF 640x480)", "Camera 0 (MSMF 640x480)"],
        )

        self.assertEqual(
            roles,
            {
                "nir_camera": (2, "Camera 2 (MSMF 640x480)"),
                "rgb_camera": (0, "Camera 0 (MSMF 640x480)"),
            },
        )



if __name__ == "__main__":
    unittest.main()
