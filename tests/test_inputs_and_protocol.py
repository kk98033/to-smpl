import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from smpl_0901.protocol_v2_udp import (
    PACKET_SIZE,
    pack_protocol_v2_frame,
    unpack_protocol_v2_frame,
)
from smpl_0901.service import (
    FACTORY_IDS,
    body25_from_factory59,
    iter_json_records,
    parse_joint_frame,
)


class InputContractTests(unittest.TestCase):
    def test_new_main_predict_59_array(self):
        points = np.arange(59 * 3, dtype=np.float32).reshape(59, 3)
        frame = parse_joint_frame(
            {
                "schema": "factory_59pt_body_hands",
                "frame_index": 7,
                "timestamp_s": 1.25,
                "keypoints_3d": points.tolist(),
                "reprojection_errors_px": [0.0] * 58 + [121.0],
            },
            units="m",
            axis_map="x,y,z",
            fallback_id=0,
        )
        np.testing.assert_allclose(frame.joints, points)
        self.assertEqual(frame.frame_id, 7)
        self.assertEqual(frame.confidence[-1], 0.0)

    def test_old_wholebody_mapping(self):
        mapping = {str(i): [float(i), 0.0, 1.0] for i in FACTORY_IDS}
        frame = parse_joint_frame(
            {"keypoint_3d": mapping}, units="mm", axis_map="x,-y,z", fallback_id=3
        )
        self.assertEqual(frame.joints.shape, (59, 3))
        np.testing.assert_allclose(frame.joints[17], [0.091, 0.0, 0.001])

    def test_npz_prefers_smoothed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.npz"
            np.savez(
                path,
                keypoints_3d=np.zeros((1, 59, 3), dtype=np.float32),
                keypoints_3d_smoothed=np.ones((1, 59, 3), dtype=np.float32),
                reprojection_errors_px=np.zeros((1, 59), dtype=np.float32),
                triangulation_view_counts=np.full((1, 59), 4),
            )
            record = next(iter_json_records(f"npz://{path}"))
            self.assertEqual(np.asarray(record["keypoints_3d"]).shape, (59, 3))
            self.assertTrue(np.allclose(record["keypoints_3d"], 1.0))
            self.assertTrue(all(record["reliable"]))

    def test_old_container_json_carries_units(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "joints_3d_4view.json"
            points = {str(i): [1000.0, 0.0, 0.0] for i in FACTORY_IDS}
            path.write_text(
                json.dumps({
                    "metadata": {"unit": "mm"},
                    "frames": {"106": {"keypoint_3d": points}},
                }),
                encoding="utf-8",
            )
            record = next(iter_json_records(f"json://{path}"))
            frame = parse_joint_frame(
                record, units="auto", axis_map="x,y,z", fallback_id=0
            )
            self.assertEqual(frame.frame_id, 106)
            np.testing.assert_allclose(frame.joints[:, 0], 1.0)

    def test_body25_and_hands(self):
        points = np.arange(59 * 3, dtype=np.float32).reshape(59, 3)
        body, left, right = body25_from_factory59(points)
        self.assertEqual(body.shape, (25, 3))
        self.assertEqual(left.shape, (21, 3))
        self.assertEqual(right.shape, (21, 3))
        np.testing.assert_allclose(body[1], (points[5] + points[6]) * 0.5)


class ProtocolTests(unittest.TestCase):
    def test_protocol_v2_round_trip(self):
        frame = {
            "protocolVersion": 2,
            "frameId": 42,
            "body": {
                "rootPosition": [1, 2, 3],
                "pelvisWorld": [4, 5, 6],
                "rootRotation": [0, 0, 0, 1],
                "rootConfidence": 0.9,
                "pose": [0.0] * 156,
            },
            "hands": {
                "leftLocalJoints": [0.0] * 63,
                "leftConfidence": [1.0] * 21,
                "rightLocalJoints": [0.0] * 63,
                "rightConfidence": [1.0] * 21,
            },
            "quality": {
                "inputValid": True,
                "inputScore": 1.0,
                "fitResidualMm": 12.0,
                "worstJointResidualMm": 20.0,
                "torsoOrientationDeg": 2.0,
                "solverState": "TRACKING",
                "stepsUsed": 100,
                "reasons": [],
            },
        }
        packet = pack_protocol_v2_frame(frame)
        self.assertEqual(len(packet), PACKET_SIZE)
        decoded = unpack_protocol_v2_frame(packet)
        self.assertEqual(decoded["frameId"], 42)
        self.assertEqual(decoded["protocolVersion"], 2)


if __name__ == "__main__":
    unittest.main()
