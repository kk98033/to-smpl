import json
import tempfile
import unittest
from pathlib import Path

from smpl_0901.dashboard import read_last_json_record


class DashboardTests(unittest.TestCase):
    def test_reads_latest_complete_jsonl_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fit.jsonl"
            path.write_text(
                json.dumps({"frame": 1}) + "\n" +
                json.dumps({"frame": 2, "smpl_parameters": {"body_pose": [0.0] * 69}}) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(read_last_json_record(path)["frame"], 2)

    def test_ignores_partial_last_jsonl_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fit.jsonl"
            path.write_text('{"frame": 9}\n{"frame":', encoding="utf-8")
            self.assertEqual(read_last_json_record(path)["frame"], 9)

    def test_missing_jsonl_returns_none(self):
        self.assertIsNone(read_last_json_record(Path("does-not-exist.fit.jsonl")))


if __name__ == "__main__":
    unittest.main()
