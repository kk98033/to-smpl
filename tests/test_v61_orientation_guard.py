from __future__ import annotations

import numpy as np

from smpl_0901.pkssm_v61 import OrientationAnatomyStateEstimator


def body17() -> np.ndarray:
    joints = np.zeros((59, 3), dtype=np.float32)
    joints[0] = (0.0, 0.82, 0.15)
    joints[1:5] = joints[0]
    joints[5] = (0.22, 0.62, 0.0)
    joints[6] = (-0.22, 0.62, 0.0)
    joints[7] = (0.48, 0.48, 0.03)
    joints[8] = (-0.48, 0.48, 0.03)
    joints[9] = (0.68, 0.30, 0.08)
    joints[10] = (-0.68, 0.30, 0.08)
    joints[11] = (0.13, 0.0, 0.0)
    joints[12] = (-0.13, 0.0, 0.0)
    joints[13] = (0.13, -0.42, 0.0)
    joints[14] = (-0.13, -0.42, 0.0)
    joints[15] = (0.13, -0.82, 0.04)
    joints[16] = (-0.13, -0.82, 0.04)
    return joints


def prime(state: OrientationAnatomyStateEstimator) -> np.ndarray:
    joints = body17()
    confidence = np.ones(59, dtype=np.float32)
    for index in range(8):
        result = state.update(joints, confidence, 1_000_000_000 + index * 66_666_667)
    assert result.ready
    return joints


def test_stable_window_delays_initialization() -> None:
    state = OrientationAnatomyStateEstimator(stable_frames=4)
    joints = body17()
    confidence = np.ones(59, dtype=np.float32)
    results = [state.update(joints, confidence, 1_000_000_000 + i * 66_666_667)
               for i in range(4)]
    assert [item.ready for item in results] == [False, False, False, True]


def test_startup_uses_finite_torso_when_joint_confidence_is_unavailable() -> None:
    state = OrientationAnatomyStateEstimator(stable_frames=3)
    joints = body17()
    confidence = np.zeros(59, dtype=np.float32)
    results = [
        state.update(joints, confidence, 1_000_000_000 + i * 66_666_667)
        for i in range(3)
    ]
    assert [item.stable_streak for item in results] == [1, 2, 3]
    assert results[-1].ready


def test_left_right_identity_flip_is_corrected() -> None:
    state = OrientationAnatomyStateEstimator()
    joints = prime(state)
    flipped = joints.copy()
    for left, right in ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10),
                        (11, 12), (13, 14), (15, 16)):
        flipped[[left, right]] = flipped[[right, left]]
    result = state.update(flipped, np.ones(59, np.float32), 1_600_000_000)
    assert result.corrected_left_right
    np.testing.assert_allclose(result.joints[:17], joints[:17])


def test_impossible_arm_length_is_held_with_zero_confidence() -> None:
    state = OrientationAnatomyStateEstimator()
    joints = prime(state)
    broken = joints.copy()
    broken[8] = (-2.0, 0.48, 0.03)
    broken[10] = (-2.3, 0.30, 0.08)
    result = state.update(broken, np.ones(59, np.float32), 1_600_000_000)
    assert "right_arm" in result.rejected_regions
    np.testing.assert_allclose(result.joints[[8, 10]], joints[[8, 10]])
    np.testing.assert_allclose(result.confidence[[8, 10]], 0.0)


def test_single_frame_arm_reversal_is_held() -> None:
    state = OrientationAnatomyStateEstimator()
    joints = prime(state)
    reversed_arm = joints.copy()
    reversed_arm[8] = (0.04, 0.76, -0.03)
    reversed_arm[10] = (0.24, 0.94, -0.08)
    result = state.update(reversed_arm, np.ones(59, np.float32), 1_600_000_000)
    assert "right_arm" in result.rejected_regions
    np.testing.assert_allclose(result.joints[[8, 10]], joints[[8, 10]])


def test_opposite_head_cue_is_ignored_after_reference_lock() -> None:
    state = OrientationAnatomyStateEstimator()
    joints = prime(state)
    backwards = joints.copy()
    backwards[0, 2] = -0.15
    result = state.update(backwards, np.ones(59, np.float32), 1_600_000_000)
    assert "head" in result.rejected_regions
    np.testing.assert_allclose(result.joints[0], joints[0])
    assert result.confidence[0] == 0.0
