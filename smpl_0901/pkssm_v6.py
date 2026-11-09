"""Hybrid V6 PK-SSM adapter and motion-aware regional gate.

This experimental module keeps the V5 SMPL/IK solver intact.  It changes the
input state estimator and the acceptance policy so that a missing arm cannot
freeze a valid torso or the opposite arm.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np


TORSO_FACTORY17 = (0, 5, 6, 11, 12)
RIGHT_ARM_FACTORY17 = (6, 8, 10)
LEFT_ARM_FACTORY17 = (5, 7, 9)
LOWER_FACTORY17 = (13, 14, 15, 16)
REGION_TTL = {"torso": 6, "right_arm": 2, "left_arm": 2, "lower": 4, "other": 2}
REGION_SPEED_CAP_MPS = {
    "torso": 3.0, "right_arm": 8.0, "left_arm": 8.0,
    "lower": 5.0, "other": 4.0,
}
REGION_BODY25 = {
    "torso": (0, 1, 2, 5, 8, 9, 12),
    "right_arm": (2, 3, 4),
    "left_arm": (5, 6, 7),
}
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
TORSO_RESIDUAL_LIMIT_MM = 130.0
ARM_RESIDUAL_LIMIT_MM = 115.0
FAST_ARM_RESIDUAL_LIMIT_MM = 165.0
TORSO_DELTA_LIMIT_DEG = 90.0
ARM_DELTA_LIMIT_DEG = 95.0
FAST_ARM_DELTA_LIMIT_DEG = 120.0


def _factory_region(index: int) -> str:
    if index in TORSO_FACTORY17:
        return "torso"
    if index in RIGHT_ARM_FACTORY17:
        return "right_arm"
    if index in LEFT_ARM_FACTORY17:
        return "left_arm"
    if index in LOWER_FACTORY17:
        return "lower"
    return "other"


@dataclass(frozen=True)
class CompletionResult:
    joints: np.ndarray
    confidence: np.ndarray
    predicted: tuple[int, ...]
    stale: tuple[int, ...]
    rejected_outliers: tuple[int, ...]


class RegionalJointStateEstimator:
    """Causal constant-velocity completion with anatomical TTLs.

    Missing values always become finite once a joint has been observed.  Only
    short-horizon predictions receive non-zero confidence.  Older carried
    coordinates have confidence zero, so they keep tensor geometry finite but
    cannot pull the optimizer away from the last accepted model pose.
    """

    def __init__(self) -> None:
        self.last = np.full((17, 3), np.nan, np.float32)
        self.previous = np.full((17, 3), np.nan, np.float32)
        self.last_ns = np.zeros(17, np.int64)
        self.previous_ns = np.zeros(17, np.int64)
        self.age = np.full(17, 1_000_000, np.int32)

    def reset(self) -> None:
        self.__init__()

    def update(self, joints: np.ndarray, confidence: np.ndarray,
               timestamp_ns: int) -> CompletionResult:
        points = np.asarray(joints, np.float32)
        scores = np.asarray(confidence, np.float32).reshape(-1)
        if points.shape != (59, 3) or scores.shape != (59,):
            raise ValueError("V6 state estimator expects Factory59 joints/confidence")
        out = points.copy()
        out_scores = scores.copy()
        self.age = np.minimum(self.age + 1, 1_000_000)
        predicted: list[int] = []
        stale: list[int] = []
        rejected: list[int] = []

        finite = np.isfinite(points[:17]).all(axis=1)
        # Reject only clearly impossible single-joint teleports.  Arm limits are
        # deliberately high so real fast hand motion is not suppressed.
        for index in np.flatnonzero(finite):
            if self.last_ns[index] <= 0 or not np.isfinite(self.last[index]).all():
                continue
            dt = max((int(timestamp_ns) - int(self.last_ns[index])) * 1e-9, 1e-4)
            speed = float(np.linalg.norm(points[index] - self.last[index]) / dt)
            region = _factory_region(int(index))
            hard_limit = REGION_SPEED_CAP_MPS[region] * 1.75
            if speed > hard_limit:
                finite[index] = False
                out_scores[index] = 0.0
                rejected.append(int(index))

        for index in range(17):
            region = _factory_region(index)
            if finite[index]:
                self.previous[index] = self.last[index]
                self.previous_ns[index] = self.last_ns[index]
                self.last[index] = points[index]
                self.last_ns[index] = int(timestamp_ns)
                self.age[index] = 0
                continue
            if not np.isfinite(self.last[index]).all():
                continue
            ttl = REGION_TTL[region]
            if self.age[index] <= ttl:
                velocity = np.zeros(3, np.float32)
                dt_history = (self.last_ns[index] - self.previous_ns[index]) * 1e-9
                if dt_history > 1e-4 and np.isfinite(self.previous[index]).all():
                    velocity = (self.last[index] - self.previous[index]) / dt_history
                    speed = float(np.linalg.norm(velocity))
                    cap = REGION_SPEED_CAP_MPS[region]
                    if speed > cap:
                        velocity *= cap / max(speed, 1e-8)
                horizon = max((int(timestamp_ns) - int(self.last_ns[index])) * 1e-9, 0.0)
                out[index] = self.last[index] + velocity * horizon
                # Prediction is evidence only briefly; confidence decays fast.
                out_scores[index] = float(0.28 * (0.45 ** max(self.age[index] - 1, 0)))
                predicted.append(index)
            else:
                out[index] = self.last[index]
                out_scores[index] = 0.0
                stale.append(index)
        return CompletionResult(out, out_scores, tuple(predicted), tuple(stale), tuple(rejected))


@dataclass(frozen=True)
class MotionState:
    fast_coherent: dict[str, bool]
    wrist_speed_mps: dict[str, float]
    limb_coherence: dict[str, float]


class RegionalMotionEstimator:
    def __init__(self) -> None:
        self.history = {"right_arm": deque(maxlen=4), "left_arm": deque(maxlen=4)}

    def update(self, target: np.ndarray, confidence: np.ndarray,
               timestamp_ns: int) -> MotionState:
        points = np.asarray(target, np.float32)
        scores = np.asarray(confidence, np.float32)
        fast: dict[str, bool] = {}
        speeds: dict[str, float] = {}
        coherence: dict[str, float] = {}
        for name, joints in (("right_arm", (2, 3, 4)), ("left_arm", (5, 6, 7))):
            if np.all(scores[list(joints)] >= 0.5) and np.isfinite(points[list(joints)]).all():
                self.history[name].append((int(timestamp_ns), points[list(joints)].copy()))
            hist = self.history[name]
            if len(hist) < 2:
                fast[name] = False; speeds[name] = 0.0; coherence[name] = 0.0
                continue
            t0, p0 = hist[-2]; t1, p1 = hist[-1]
            dt = max((t1 - t0) * 1e-9, 1e-4)
            displacement = p1 - p0
            elbow_speed = float(np.linalg.norm(displacement[1]) / dt)
            wrist_speed = float(np.linalg.norm(displacement[2]) / dt)
            a = displacement[1]; b = displacement[2]
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            directional = float(np.dot(a, b) / denom) if denom > 1e-8 else 0.0
            length0 = np.linalg.norm(p0[1:] - p0[:-1], axis=1)
            length1 = np.linalg.norm(p1[1:] - p1[:-1], axis=1)
            length_error = float(np.max(np.abs(length1 - length0) / np.maximum(length0, 1e-4)))
            coherent = directional >= 0.0 and length_error <= 0.35
            speeds[name] = wrist_speed
            coherence[name] = directional
            fast[name] = bool(coherent and 0.6 <= wrist_speed <= 8.0 and elbow_speed <= 8.0)
        return MotionState(fast, speeds, coherence)


@dataclass(frozen=True)
class V6GateResult:
    root: np.ndarray
    body: np.ndarray
    update_region: dict[str, bool]
    reasons: dict[str, tuple[str, ...]]
    residual_mm: dict[str, float]
    confidence: dict[str, float]


def weighted_residual_mm(pred: np.ndarray, target: np.ndarray,
                         weights: np.ndarray, indices: tuple[int, ...]) -> float:
    selected = np.asarray(indices, np.int64)
    distance = np.linalg.norm(pred[selected] - target[selected], axis=1) * 1000.0
    weight = np.asarray(weights, np.float64)[selected]
    return float(np.sum(distance * weight) / max(float(np.sum(weight)), 1e-6))


def regional_gate(candidate_root: np.ndarray, candidate_body: np.ndarray,
                  previous_root: np.ndarray, previous_body: np.ndarray,
                  candidate_body25: np.ndarray, target_body25: np.ndarray,
                  weights: np.ndarray, diagnostics: dict[str, object],
                  motion: MotionState) -> V6GateResult:
    root = np.asarray(candidate_root, np.float32).reshape(3).copy()
    body = np.asarray(candidate_body, np.float32).reshape(23, 3).copy()
    old_root = np.asarray(previous_root, np.float32).reshape(3)
    old_body = np.asarray(previous_body, np.float32).reshape(23, 3)
    delta = diagnostics.get("delta_deg", [None] * 24)
    twist = diagnostics.get("twist_deg", [None] * 24)
    updates={}; reasons={}; residuals={}; confidences={}
    for name, joints in REGION_BODY25.items():
        confidence = float(np.mean(np.asarray(weights)[list(joints)]))
        residual = weighted_residual_mm(candidate_body25, target_body25, weights, joints)
        region_delta = max((float(delta[i]) for i in REGION_SMPL24[name]
                            if delta[i] is not None and np.isfinite(delta[i])), default=0.0)
        region_twist = max((float(twist[i]) for i in REGION_SMPL24[name]
                            if twist[i] is not None and np.isfinite(twist[i])), default=0.0)
        fast = bool(motion.fast_coherent.get(name, False))
        residual_limit = (
            TORSO_RESIDUAL_LIMIT_MM if name == "torso" else
            FAST_ARM_RESIDUAL_LIMIT_MM if fast else ARM_RESIDUAL_LIMIT_MM
        )
        delta_limit = (
            TORSO_DELTA_LIMIT_DEG if name == "torso" else
            FAST_ARM_DELTA_LIMIT_DEG if fast else ARM_DELTA_LIMIT_DEG
        )
        failures=[]
        if confidence < 0.35: failures.append("confidence<0.35")
        if residual > residual_limit: failures.append(f"residual>{residual_limit:g}mm")
        if region_delta > delta_limit: failures.append(f"delta>{delta_limit:g}deg")
        if region_twist > 100.0: failures.append("twist>100deg")
        safe=not failures
        updates[name]=safe; reasons[name]=tuple(failures)
        residuals[name]=residual; confidences[name]=confidence
        if not safe:
            body[list(REGION_POSE[name])] = old_body[list(REGION_POSE[name])]
            if name == "torso": root=old_root.copy()
    return V6GateResult(root, body, updates, reasons, residuals, confidences)
