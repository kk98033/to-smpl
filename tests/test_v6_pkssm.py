from __future__ import annotations

import numpy as np

from smpl_0901 import pkssm_v6 as v6


def test_arm_completion_expires_to_zero_confidence_but_stays_finite() -> None:
    state = v6.RegionalJointStateEstimator()
    joints = np.arange(59 * 3, dtype=np.float32).reshape(59, 3) / 100.0
    confidence = np.ones(59, dtype=np.float32)
    state.update(joints, confidence, 1_000_000_000)

    missing = joints.copy()
    missing[10] = np.nan
    first = state.update(missing, confidence, 1_066_666_667)
    second = state.update(missing, confidence, 1_133_333_334)
    expired = state.update(missing, confidence, 1_200_000_001)

    assert 10 in first.predicted and 10 in second.predicted
    assert first.confidence[10] > second.confidence[10] > 0.0
    assert 10 in expired.stale
    assert expired.confidence[10] == 0.0
    assert np.isfinite(expired.joints[10]).all()


def test_one_missing_arm_does_not_reduce_other_regions() -> None:
    state = v6.RegionalJointStateEstimator()
    joints = np.arange(59 * 3, dtype=np.float32).reshape(59, 3) / 100.0
    confidence = np.ones(59, dtype=np.float32)
    state.update(joints, confidence, 1_000_000_000)
    missing = joints.copy()
    missing[8] = np.nan
    result = state.update(missing, confidence, 1_066_666_667)
    assert result.confidence[8] < 1.0
    np.testing.assert_allclose(result.confidence[[0, 5, 6, 7, 9, 10, 11, 12]], 1.0)


def test_fast_coherent_arm_uses_motion_gate_without_relaxing_torso() -> None:
    candidate_root = np.ones(3, np.float32)
    previous_root = np.zeros(3, np.float32)
    candidate_body = np.ones((23, 3), np.float32)
    previous_body = np.zeros((23, 3), np.float32)
    target = np.zeros((25, 3), np.float32)
    candidate = target.copy()
    candidate[4, 0] = 0.45  # 150 mm mean right-arm residual
    weights = np.ones(25, np.float32)
    diagnostics = {"delta_deg": [0.0] * 24, "twist_deg": [0.0] * 24}

    slow = v6.MotionState(
        {"right_arm": False, "left_arm": False},
        {"right_arm": 0.0, "left_arm": 0.0},
        {"right_arm": 0.0, "left_arm": 0.0},
    )
    fast = v6.MotionState(
        {"right_arm": True, "left_arm": False},
        {"right_arm": 2.0, "left_arm": 0.0},
        {"right_arm": 1.0, "left_arm": 0.0},
    )
    slow_result = v6.regional_gate(
        candidate_root, candidate_body, previous_root, previous_body,
        candidate, target, weights, diagnostics, slow,
    )
    fast_result = v6.regional_gate(
        candidate_root, candidate_body, previous_root, previous_body,
        candidate, target, weights, diagnostics, fast,
    )
    assert not slow_result.update_region["right_arm"]
    assert fast_result.update_region["right_arm"]
    assert slow_result.update_region["torso"]
    assert fast_result.update_region["torso"]
