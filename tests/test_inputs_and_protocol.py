import json
import re
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from smpl_0901.protocol_v2_udp import (
    PACKET_SIZE,
    pack_protocol_v2_frame,
    unpack_protocol_v2_frame,
)
from smpl_0901.raw_skeleton_udp import (
    PACKET_SIZE as RAW_PACKET_SIZE,
    pack_raw_skeleton_frame,
    unpack_raw_skeleton_frame,
)
from smpl_0901.service import (
    FACTORY_IDS,
    FIT_PROFILES,
    body25_confidence_from_factory59,
    body25_from_factory59,
    iter_json_records,
    parse_joint_frame,
    Smpl0901Bridge,
)


class InputContractTests(unittest.TestCase):
    def test_new_main_predict_59_array(self):
        points = np.arange(59 * 3, dtype=np.float32).reshape(59, 3)
        frame = parse_joint_frame(
            {
                "schema": "factory_59pt_body_hands",
                "frame_index": 7,
                "timestamp_s": 1.25,
                "ptp_epoch_ns": 1_250_000_123,
                "coordinate_frame": "factory-rig-b-calibration-world",
                "_input_units": "m",
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
        np.testing.assert_allclose(frame.raw_joints, points)
        self.assertEqual(frame.input_unit, "m")
        self.assertEqual(frame.ptp_epoch_ns, 1_250_000_123)
        self.assertTrue(frame.ptp_exact)
        self.assertEqual(frame.coordinate_frame, "factory-rig-b-calibration-world")

    def test_dt_pose_v1_udp_payload_uses_declared_metres_and_ptp(self):
        points = (np.arange(59 * 3, dtype=np.float32).reshape(59, 3) / 1000.0)
        joints = points.tolist()
        joints[4] = None
        frame = parse_joint_frame(
            {
                "schema": "dt-pose.pose3d/v1",
                "source": "rig_b",
                "frame": 23,
                "timestamp_ns": 1_756_700_000_123_456_789,
                "units": "m",
                "layout": "factory59",
                "joints": joints,
                "single_person": True,
            },
            units="auto",
            axis_map="x,y,z",
            fallback_id=0,
        )
        self.assertEqual(frame.frame_id, 23)
        self.assertEqual(frame.input_unit, "m")
        self.assertEqual(frame.ptp_epoch_ns, 1_756_700_000_123_456_789)
        self.assertTrue(frame.ptp_exact)
        np.testing.assert_allclose(frame.joints[5:], points[5:])
        self.assertTrue(np.isnan(frame.raw_joints[4]).all())
        self.assertEqual(frame.confidence[4], 0.0)

    def test_dt_pose_v1_refuses_a_non_factory59_layout(self):
        with self.assertRaisesRegex(ValueError, "layout must be factory59"):
            parse_joint_frame(
                {
                    "schema": "dt-pose.pose3d/v1",
                    "units": "m",
                    "layout": "coco17",
                    "joints": np.zeros((59, 3)).tolist(),
                },
                units="auto",
                axis_map="x,y,z",
                fallback_id=0,
            )

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

    def test_upper_body_profile_stops_before_occluded_legs(self):
        self.assertEqual(FIT_PROFILES["upper-body"], tuple(range(10)) + (12,))
        self.assertIn(9, FIT_PROFILES["upper-body"])
        self.assertIn(12, FIT_PROFILES["upper-body"])
        self.assertNotIn(10, FIT_PROFILES["upper-body"])
        self.assertNotIn(13, FIT_PROFILES["upper-body"])
        self.assertIn(14, FIT_PROFILES["full"])

    def test_body25_confidence_uses_weakest_joint_for_midpoints(self):
        confidence = np.ones(59, dtype=np.float32)
        confidence[5] = 0.8
        confidence[6] = 0.3
        confidence[11] = 0.2
        confidence[12] = 0.9
        mapped = body25_confidence_from_factory59(confidence)
        self.assertAlmostEqual(float(mapped[1]), 0.3)
        self.assertAlmostEqual(float(mapped[8]), 0.2)
        self.assertAlmostEqual(float(mapped[5]), 0.8)


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

    def test_raw_skeleton_v1_round_trip_stays_below_mtu(self):
        points = np.arange(59 * 3, dtype=np.float32).reshape(59, 3)
        points[-1] = np.nan
        confidence = np.ones(59, dtype=np.float32)
        confidence[-1] = 0.0
        packet = pack_raw_skeleton_frame(
            frame_id=77,
            ptp_epoch_ns=1_725_150_000_123_456_789,
            points=points,
            confidence=confidence,
            unit="mm",
            coordinate_frame="factory-rig-b-calibration-world",
        )

        self.assertEqual(len(packet), RAW_PACKET_SIZE)
        self.assertEqual(RAW_PACKET_SIZE, 1032)
        self.assertLess(RAW_PACKET_SIZE, 1500)
        decoded = unpack_raw_skeleton_frame(packet)
        self.assertEqual(decoded["frameId"], 77)
        self.assertEqual(decoded["unit"], "mm")
        self.assertEqual(decoded["coordinateFrame"], "factory-rig-b-calibration-world")
        np.testing.assert_allclose(decoded["points"][:-1], points[:-1])
        self.assertTrue(np.isnan(decoded["points"][-1]).all())
        np.testing.assert_allclose(decoded["confidence"], confidence)


    def test_bridge_sends_raw_skeleton_to_independent_destination(self):
        class FakeSocket:
            def __init__(self):
                self.calls = []

            def sendto(self, packet, destination):
                self.calls.append((packet, destination))

        points = np.zeros((59, 3), dtype=np.float32)
        frame = parse_joint_frame(
            {
                "frame_index": 9,
                "ptp_epoch_ns": 123456789,
                "_input_units": "mm",
                "coordinate_frame": "factory-world",
                "keypoints_3d": points.tolist(),
                "reliable": [True] * 59,
            },
            units="auto", axis_map="x,-y,z", fallback_id=0,
        )
        bridge = Smpl0901Bridge.__new__(Smpl0901Bridge)
        bridge.sock = FakeSocket()
        bridge.raw_destination = ("127.0.0.1", 9096)

        self.assertTrue(bridge.send_raw_skeleton(frame))

        self.assertEqual(bridge.sock.calls[0][1], ("127.0.0.1", 9096))
        decoded = unpack_raw_skeleton_frame(bridge.sock.calls[0][0])
        self.assertEqual(decoded["frameId"], 9)
        self.assertEqual(decoded["coordinateFrame"], "factory-world")

    def test_raw_skeleton_coordinate_frame_has_fixed_utf8_limit(self):
        with self.assertRaisesRegex(ValueError, "coordinate frame"):
            pack_raw_skeleton_frame(
                frame_id=1, ptp_epoch_ns=1,
                points=np.zeros((59, 3), dtype=np.float32),
                confidence=np.ones(59, dtype=np.float32),
                unit="m", coordinate_frame="x" * 64,
            )

    def test_unity_0901_codec_matches_server_packet_size(self):
        codec = (
            Path(__file__).parents[1]
            / "unity"
            / "SMPL0901Player"
            / "Runtime"
            / "Smpl0901BinaryCodec.cs"
        ).read_text(encoding="utf-8")
        match = re.search(r"PacketSize\s*=\s*(\d+)", codec)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), PACKET_SIZE)
        self.assertIn('header != "SMV2"', codec)

    def test_unity_rsv1_codec_matches_raw_sender_contract(self):
        expected_size = struct.calcsize("<4sHHIQB3x64s177f59f")
        self.assertEqual(expected_size, 1032)
        codec = (
            Path(__file__).parents[1]
            / "unity"
            / "SMPL0901Player"
            / "Runtime"
            / "Rsv1RawSkeletonCodec.cs"
        ).read_text(encoding="utf-8")
        size = re.search(r"PacketSize\s*=\s*(\d+)", codec)
        count = re.search(r"JointCount\s*=\s*(\d+)", codec)
        self.assertIsNotNone(size)
        self.assertIsNotNone(count)
        self.assertEqual(int(size.group(1)), expected_size)
        self.assertEqual(int(count.group(1)), 59)
        self.assertIn('magic != "RSV1"', codec)
        self.assertIn("reader.ReadUInt64()", codec)

    def test_unity_player_keeps_hybrid_alignment_contract(self):
        unity_root = Path(__file__).parents[1] / "unity" / "SMPL0901Player"
        player = (unity_root / "Runtime" / "Smpl0901LivePlayer.cs").read_text(
            encoding="utf-8"
        )
        raw = (unity_root / "Runtime" / "Rsv1RawSkeletonRenderer.cs").read_text(
            encoding="utf-8"
        )
        hands = (unity_root / "Runtime" / "Smpl0901RawHandRetargeter.cs").read_text(
            encoding="utf-8"
        )
        panel = (unity_root / "Runtime" / "Smpl0901TrackingPanel.cs").read_text(
            encoding="utf-8"
        )

        self.assertIn("RuntimePelvis", player)
        self.assertLess(player.index("ApplyBodyPose(frame.body.pose)"),
                        player.index("handRetargeter.ApplyHands(frame.hands)"))
        self.assertIn("followSmplPelvis", raw)
        self.assertIn("player.RuntimePelvis.position", raw)
        self.assertIn("SetAlignmentOffset", raw)
        self.assertIn("ShowPreviewTPose", raw)
        self.assertIn("public bool requireManualStart = true", raw)
        self.assertIn("segment.bone.localRotation, targetRotation", hands)
        self.assertIn("pelvisCorrectionEuler", player)
        self.assertIn("public bool requireManualStart = true", player)
        self.assertIn("ShowTPose", player)
        self.assertIn("GetComponentsInChildren<SkinnedMeshRenderer>(true)", player)
        self.assertIn("if (!renderCharacter) SetCharacterVisible(false)", player)
        self.assertIn("showDebugDetails", panel)
        self.assertIn("SetManualOffset", panel)
        self.assertIn("Reset Raw Offset", panel)
        self.assertIn("Start Receiving", panel)
        self.assertIn("Stop Receiving", panel)
        self.assertIn("Live Pose Rot", panel)
        self.assertIn("Display Rot", panel)
        self.assertIn("BindingStatus", player)
        self.assertIn("new Vector3(-90f, 0f, 0f)", player)
        self.assertIn("Quaternion.Euler(supRigPelvisEuler)", player)
        self.assertIn("invertX ? -x : x", raw)
        root_motion = (unity_root / "Runtime" / "Smpl0901RootMotionDriver.cs").read_text(
            encoding="utf-8"
        )
        self.assertIn("new Vector3(0f, 180f, 0f)", root_motion)
        self.assertIn("SetDisplayEuler", root_motion)


if __name__ == "__main__":
    unittest.main()
