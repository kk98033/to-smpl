import unittest

import numpy as np

from live_smpl_unity_bridge import (
    FACTORY_IDS,
    body25_from_factory59,
    parse_axis_map,
    parse_joint_frame,
)


class JointAdapterTests(unittest.TestCase):
    def test_factory_array_to_body25(self):
        points = np.arange(59 * 3, dtype=np.float32).reshape(59, 3)
        body, left, right = body25_from_factory59(points)
        np.testing.assert_array_equal(body[2], points[6])
        np.testing.assert_array_equal(body[5], points[5])
        np.testing.assert_array_equal(body[8], (points[11] + points[12]) * 0.5)
        np.testing.assert_array_equal(left, points[17:38])
        np.testing.assert_array_equal(right, points[38:59])

    def test_official_id_mapping_mm_and_axes(self):
        mapping = {str(joint_id): [1000.0, 2000.0, 3000.0] for joint_id in FACTORY_IDS}
        frame = parse_joint_frame(
            {"frame_index": 7, "keypoint_3d": mapping},
            units="mm",
            axis_map="x,-y,z",
            fallback_id=0,
        )
        self.assertEqual(frame.frame_id, 7)
        np.testing.assert_allclose(frame.joints[0], [1.0, -2.0, 3.0])

    def test_reject_wrong_schema(self):
        with self.assertRaises(ValueError):
            parse_joint_frame(
                {"schema": "unknown", "keypoints_3d": np.zeros((59, 3)).tolist()},
                units="m",
                axis_map="x,y,z",
                fallback_id=0,
            )

    def test_axis_map_is_permutation(self):
        self.assertEqual(parse_axis_map("y,z,x"), ((1, 1.0), (2, 1.0), (0, 1.0)))
        with self.assertRaises(ValueError):
            parse_axis_map("x,x,z")


if __name__ == "__main__":
    unittest.main()
