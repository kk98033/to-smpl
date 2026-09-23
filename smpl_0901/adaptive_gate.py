"""Hybrid v3 quality estimation and regional safety gate.

The production adaptive-fast tracker combines optional upstream confidence
with the deterministic causal geometry fallback implemented here.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


QUALITY_EDGES = (
    (1, 8), (2, 5), (9, 12),
    (2, 3), (3, 4), (5, 6), (6, 7),
)
REFERENCE_BOOTSTRAP_FRAMES = 15
REFERENCE_HISTORY_FRAMES = 15
REFERENCE_RECOVERY_STREAK = 8
REFERENCE_RECOVERY_GAP = 0.35
REFERENCE_RECOVERY_MAD = 0.12
REGION_BODY25 = {
    "torso": (0, 1, 2, 5, 8, 9, 12),
    "right_arm": (2, 3, 4),
    "left_arm": (5, 6, 7),
}
# SMPL joint index minus one: body_pose does not contain the pelvis/root.
REGION_POSE = {
    "torso": (2, 5, 8, 12, 13),
    "right_arm": (16, 18),
    "left_arm": (15, 17),
}
REGION_SMPL24 = {
    "torso": (0, 3, 6, 9, 12, 13, 14, 15),
    "right_arm": (17, 19, 21),
    "left_arm": (16, 18, 20),
}


@dataclass(frozen=True)
class RegionalGateResult:
    root: np.ndarray
    body: np.ndarray
    update_region: dict[str, bool]
    reasons: dict[str, tuple[str, ...]]
    residual_mm: dict[str, float]
    confidence: dict[str, float]


class GeometryQualityEstimator:
    """Causal confidence fallback for recordings without detector confidence."""

    def __init__(self, seed: np.ndarray, source_fps: float):
        self.previous = np.asarray(seed, dtype=np.float32).copy()
        self.source_fps = max(float(source_fps), 1.0)
        self.reference_lengths = {
            edge: max(float(np.linalg.norm(self.previous[edge[1]] - self.previous[edge[0]])), 1e-4)
            for edge in QUALITY_EDGES
        }
        self.length_history = {
            edge: deque([length], maxlen=REFERENCE_HISTORY_FRAMES)
            for edge, length in self.reference_lengths.items()
        }
        self.recovery_streak = {edge: 0 for edge in QUALITY_EDGES}
        self.update_count = 0

    def update(self, target: np.ndarray, *, source_fps: float | None = None) -> np.ndarray:
        points = np.asarray(target, dtype=np.float32)
        weights = np.ones(25, dtype=np.float32)
        finite = np.isfinite(points).all(axis=1)
        weights[~finite] = 0.0

        # Softly reduce impossible frame-to-frame speeds.  Five metres/second is
        # kept at full confidence; confidence reaches zero at 12 m/s.
        active_fps = self.source_fps if source_fps is None else max(float(source_fps), 1.0)
        speed = np.linalg.norm(points - self.previous, axis=1) * active_fps
        speed_weight = np.clip((12.0 - speed) / 7.0, 0.0, 1.0)
        weights *= speed_weight.astype(np.float32)

        # Bone lengths should be temporally stable.  A single triangulation
        # outlier must not become the permanent reference: bootstrap from the
        # causal median of the first 15 frames, then use the normal adaptive
        # reference.  A conservative stable-window recovery handles a later
        # persistent scale/reference change without learning isolated outliers.
        for start, end in QUALITY_EDGES:
            length = float(np.linalg.norm(points[end] - points[start]))
            edge = (start, end)
            history = self.length_history[edge]
            if np.isfinite(length) and length > 1e-4:
                history.append(length)
            robust_reference = max(float(np.median(history)), 1e-4)

            if self.update_count < REFERENCE_BOOTSTRAP_FRAMES:
                self.reference_lengths[edge] = robust_reference
                self.recovery_streak[edge] = 0
            else:
                reference = self.reference_lengths[edge]
                history_values = np.asarray(history, dtype=np.float64)
                relative_mad = float(
                    np.median(np.abs(history_values - robust_reference))
                    / robust_reference
                )
                reference_gap = abs(robust_reference - reference) / max(reference, 1e-4)
                stable_disagreement = (
                    len(history) == REFERENCE_HISTORY_FRAMES
                    and relative_mad <= REFERENCE_RECOVERY_MAD
                    and reference_gap >= REFERENCE_RECOVERY_GAP
                )
                self.recovery_streak[edge] = (
                    self.recovery_streak[edge] + 1 if stable_disagreement else 0
                )
                if self.recovery_streak[edge] >= REFERENCE_RECOVERY_STREAK:
                    self.reference_lengths[edge] = robust_reference
                    self.recovery_streak[edge] = 0

            reference = self.reference_lengths[edge]
            relative = abs(length - reference) / max(reference, 1e-4)
            edge_weight = float(np.clip((0.45 - relative) / 0.33, 0.0, 1.0))
            weights[start] = min(weights[start], edge_weight)
            weights[end] = min(weights[end], edge_weight)
            if self.update_count >= REFERENCE_BOOTSTRAP_FRAMES and edge_weight >= 0.5:
                self.reference_lengths[edge] = 0.98 * reference + 0.02 * length

        # Pelvis is the translation anchor and synthetic Body25 foot duplicates
        # are not used by the upper-body fitter.
        weights[8] = 1.0 if finite[8] else 0.0
        self.previous = np.where(finite[:, None], points, self.previous)
        self.update_count += 1
        return weights


def stabilized_target(target: np.ndarray, previous_prediction: np.ndarray,
                      weights: np.ndarray) -> np.ndarray:
    """Replace only the unreliable fraction with the last accepted model joint."""
    observed = np.asarray(target, dtype=np.float32)
    previous = np.asarray(previous_prediction, dtype=np.float32)
    blend = np.asarray(weights, dtype=np.float32).reshape(25, 1)
    safe = blend * observed + (1.0 - blend) * previous
    safe[8] = observed[8]
    return safe.astype(np.float32)


def weighted_residual_mm(pred: np.ndarray, target: np.ndarray, weights: np.ndarray,
                         indices: tuple[int, ...]) -> float:
    selected = np.asarray(indices, dtype=np.int64)
    value = np.linalg.norm(pred[selected] - target[selected], axis=1) * 1000.0
    weight = np.asarray(weights, dtype=np.float64)[selected]
    return float(np.sum(value * weight) / max(float(np.sum(weight)), 1e-6))


def regional_gate(candidate_root: np.ndarray, candidate_body: np.ndarray,
                  previous_root: np.ndarray, previous_body: np.ndarray,
                  candidate_body25: np.ndarray, target_body25: np.ndarray,
                  weights: np.ndarray, diagnostics: dict[str, object]) -> RegionalGateResult:
    """Hold only unsafe regions; keep independent valid limbs moving."""
    root = np.asarray(candidate_root, dtype=np.float32).reshape(3).copy()
    body = np.asarray(candidate_body, dtype=np.float32).reshape(23, 3).copy()
    old_root = np.asarray(previous_root, dtype=np.float32).reshape(3)
    old_body = np.asarray(previous_body, dtype=np.float32).reshape(23, 3)
    delta = diagnostics.get("delta_deg", [None] * 24)
    twist = diagnostics.get("twist_deg", [None] * 24)

    update: dict[str, bool] = {}
    reasons: dict[str, tuple[str, ...]] = {}
    residuals: dict[str, float] = {}
    confidences: dict[str, float] = {}
    for name, joints in REGION_BODY25.items():
        confidence = float(np.mean(np.asarray(weights)[list(joints)]))
        residual = weighted_residual_mm(
            candidate_body25, target_body25, weights, joints)
        region_delta = max(
            (float(delta[index]) for index in REGION_SMPL24[name]
             if delta[index] is not None and np.isfinite(delta[index])), default=0.0)
        region_twist = max(
            (float(twist[index]) for index in REGION_SMPL24[name]
             if twist[index] is not None and np.isfinite(twist[index])), default=0.0)
        failures = []
        if confidence < 0.35:
            failures.append("confidence<0.35")
        limit = 130.0 if name == "torso" else 110.0
        if residual > limit:
            failures.append(f"residual>{limit:g}mm")
        if region_delta > 90.0:
            failures.append("delta>90deg")
        if region_twist > 100.0:
            failures.append("twist>100deg")
        safe = not failures
        update[name] = safe
        reasons[name] = tuple(failures)
        residuals[name] = residual
        confidences[name] = confidence
        if not safe:
            body[list(REGION_POSE[name])] = old_body[list(REGION_POSE[name])]
            if name == "torso":
                root = old_root.copy()

    return RegionalGateResult(root, body, update, reasons, residuals, confidences)
