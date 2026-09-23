from __future__ import annotations

import numpy as np

from smpl_0901.adaptive_gate import GeometryQualityEstimator


def _body25(*, right_forearm: float = 0.20) -> np.ndarray:
    points = np.zeros((25, 3), dtype=np.float32)
    points[8] = (0.0, 0.0, 0.0)
    points[1] = (0.0, 0.75, 0.0)
    points[2] = (0.20, 0.65, 0.0)
    points[3] = (0.40, 0.65, 0.0)
    points[4] = (0.40 + right_forearm, 0.65, 0.0)
    points[5] = (-0.20, 0.65, 0.0)
    points[6] = (-0.40, 0.65, 0.0)
    points[7] = (-0.60, 0.65, 0.0)
    points[9] = (0.10, 0.0, 0.0)
    points[12] = (-0.10, 0.0, 0.0)
    return points


def test_bootstrap_recovers_from_short_first_frame_right_forearm() -> None:
    seed = _body25(right_forearm=0.10)
    estimator = GeometryQualityEstimator(seed, source_fps=30.0)
    target = _body25(right_forearm=0.20)

    weights = None
    for _ in range(16):
        weights = estimator.update(target, source_fps=2.0)

    assert weights is not None
    assert float(np.mean(weights[[2, 3, 4]])) > 0.95
    assert np.isclose(estimator.reference_lengths[(3, 4)], 0.20, atol=0.01)


def test_single_bone_length_outlier_does_not_rebase_reference() -> None:
    target = _body25(right_forearm=0.20)
    estimator = GeometryQualityEstimator(target, source_fps=30.0)
    for _ in range(20):
        estimator.update(target, source_fps=2.0)

    reference_before = estimator.reference_lengths[(3, 4)]
    estimator.update(_body25(right_forearm=0.50), source_fps=2.0)
    reference_after = estimator.reference_lengths[(3, 4)]

    assert np.isclose(reference_before, 0.20, atol=0.01)
    assert np.isclose(reference_after, reference_before, atol=0.005)
