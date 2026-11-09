"""V6.1 input orientation and anatomy stabilization for PK-SSM streams.

V6 completes missing joints, but a finite PK-SSM observation can still be
semantically wrong: left/right may swap, a limb may reverse in one frame, or
an anatomically impossible bone can persist long enough to poison the causal
state. This module adds a deterministic guard before SMPL fitting.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from .pkssm_v6 import CompletionResult, RegionalJointStateEstimator


LEFT_RIGHT_PAIRS = (
    (1, 2), (3, 4), (5, 6), (7, 8), (9, 10),
    (11, 12), (13, 14), (15, 16),
)
TORSO = (0, 5, 6, 11, 12)
LEFT_ARM = (5, 7, 9)
RIGHT_ARM = (6, 8, 10)
BONE_SPECS = {
    "shoulder": ((5, 6), (0.18, 0.75), "torso"),
    "hip": ((11, 12), (0.12, 0.65), "torso"),
    "left_upper": ((5, 7), (0.12, 0.65), "left_arm"),
    "left_forearm": ((7, 9), (0.12, 0.65), "left_arm"),
    "right_upper": ((6, 8), (0.12, 0.65), "right_arm"),
    "right_forearm": ((8, 10), (0.12, 0.65), "right_arm"),
}


@dataclass(frozen=True)
class V61CompletionResult(CompletionResult):
    ready: bool
    stable_streak: int
    corrected_left_right: bool
    rejected_regions: tuple[str, ...]
    orientation_jump_deg: float | None
    shoulder_jump_deg: float | None


def _unit(vector: np.ndarray) -> np.ndarray | None:
    value = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(value))
    if not np.isfinite(norm) or norm < 1e-8:
        return None
    return value / norm


def _angle_degrees(first: np.ndarray, second: np.ndarray) -> float:
    a = _unit(first)
    b = _unit(second)
    if a is None or b is None:
        return float("nan")
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b), -1.0, 1.0))))


def _torso_geometry(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    selected = np.asarray((5, 6, 11, 12))
    if not np.isfinite(points[selected]).all():
        return None
    shoulder = points[5] - points[6]
    mid_shoulder = (points[5] + points[6]) * 0.5
    mid_hip = (points[11] + points[12]) * 0.5
    vertical = mid_shoulder - mid_hip
    normal = np.cross(shoulder, vertical)
    if _unit(shoulder) is None or _unit(vertical) is None or _unit(normal) is None:
        return None
    return shoulder, vertical, normal


def _swap_left_right(points: np.ndarray, confidence: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    swapped = points.copy()
    scores = confidence.copy()
    for left, right in LEFT_RIGHT_PAIRS:
        swapped[[left, right]] = swapped[[right, left]]
        scores[[left, right]] = scores[[right, left]]
    return swapped, scores


class OrientationAnatomyStateEstimator(RegionalJointStateEstimator):
    """V6 completion plus causal orientation/anatomy validation."""

    def __init__(self, *, stable_frames: int = 6, torso_jump_deg: float = 75.0,
                 shoulder_jump_deg: float = 95.0, arm_jump_deg: float = 105.0) -> None:
        super().__init__()
        self.stable_frames = max(int(stable_frames), 1)
        self.torso_jump_deg = float(torso_jump_deg)
        self.shoulder_jump_deg = float(shoulder_jump_deg)
        self.arm_jump_deg = float(arm_jump_deg)
        self.stable = np.full((17, 3), np.nan, np.float32)
        self.stable_confidence = np.zeros(17, np.float32)
        self.stable_streak = 0
        self.ready = False
        self.length_history = {name: deque(maxlen=31) for name in BONE_SPECS}
        self.head_sign_history: deque[float] = deque(maxlen=31)
        self.pending_arm_vectors: dict[str, tuple[np.ndarray, np.ndarray] | None] = {
            "left_arm": None, "right_arm": None,
        }
        self.pending_arm_streak = {"left_arm": 0, "right_arm": 0}
        self.pending_torso_geometry = None
        self.pending_torso_streak = 0

    def reset(self) -> None:
        super().reset()
        self.stable = np.full((17, 3), np.nan, np.float32)
        self.stable_confidence = np.zeros(17, np.float32)
        self.stable_streak = 0
        self.ready = False
        self.length_history = {name: deque(maxlen=31) for name in BONE_SPECS}
        self.head_sign_history = deque(maxlen=31)
        self.pending_arm_vectors = {"left_arm": None, "right_arm": None}
        self.pending_arm_streak = {"left_arm": 0, "right_arm": 0}
        self.pending_torso_geometry = None
        self.pending_torso_streak = 0

    @staticmethod
    def _continuity_cost(candidate: np.ndarray, previous: np.ndarray) -> float:
        selected = np.asarray((5, 6, 7, 8, 9, 10, 11, 12))
        valid = np.isfinite(candidate[selected]).all(axis=1) & np.isfinite(previous[selected]).all(axis=1)
        if not np.any(valid) or not np.isfinite(candidate[[11, 12]]).all() or not np.isfinite(previous[[11, 12]]).all():
            return float("inf")
        current = candidate[selected][valid] - (candidate[11] + candidate[12]) * 0.5
        prior = previous[selected][valid] - (previous[11] + previous[12]) * 0.5
        return float(np.linalg.norm(current - prior, axis=1).mean())

    def _bone_rejections(self, points: np.ndarray) -> set[str]:
        rejected: set[str] = set()
        for name, ((start, end), absolute, region) in BONE_SPECS.items():
            if not np.isfinite(points[[start, end]]).all():
                rejected.add(region)
                continue
            length = float(np.linalg.norm(points[end] - points[start]))
            low, high = absolute
            history = self.length_history[name]
            if len(history) >= 5:
                median = float(np.median(history))
                low = max(low, median * 0.55)
                high = min(high, median * 1.65)
            if not low <= length <= high:
                rejected.add(region)
        geometry = _torso_geometry(points)
        if geometry is None or not 0.25 <= float(np.linalg.norm(geometry[1])) <= 1.0:
            rejected.add("torso")
        return rejected


    def _segment_in_absolute_range(self, points: np.ndarray, start: int, end: int,
                                   low: float, high: float) -> bool:
        if not np.isfinite(points[[start, end]]).all():
            return False
        length = float(np.linalg.norm(points[end] - points[start]))
        return low <= length <= high

    def _restore_coherent_observations(
        self,
        completed: np.ndarray,
        completed_confidence: np.ndarray,
        observed: np.ndarray,
        observed_confidence: np.ndarray,
    ) -> None:
        """Prefer an atomic current observation over mixed-time extrapolation.

        V6 predicts every joint independently. A complete and anatomically
        plausible current region is safer than mixing observed and extrapolated
        endpoints from different instants.
        """
        torso_indices = np.asarray((5, 6, 11, 12))
        torso_geometry = _torso_geometry(observed)
        torso_ok = (
            torso_geometry is not None
            and self._segment_in_absolute_range(observed, 5, 6, 0.18, 0.75)
            and self._segment_in_absolute_range(observed, 11, 12, 0.12, 0.65)
            and 0.25 <= float(np.linalg.norm(torso_geometry[1])) <= 1.0
        )
        if torso_ok:
            completed[torso_indices] = observed[torso_indices]
            completed_confidence[torso_indices] = observed_confidence[torso_indices]

        for chain in (LEFT_ARM, RIGHT_ARM):
            shoulder, elbow, wrist = chain
            arm_ok = (
                np.isfinite(observed[list(chain)]).all()
                and self._segment_in_absolute_range(observed, shoulder, elbow, 0.12, 0.65)
                and self._segment_in_absolute_range(observed, elbow, wrist, 0.12, 0.65)
            )
            if arm_ok:
                indices = np.asarray(chain)
                completed[indices] = observed[indices]
                completed_confidence[indices] = observed_confidence[indices]

        if np.isfinite(observed[0]).all():
            completed[0] = observed[0]
            completed_confidence[0] = observed_confidence[0]

    def _arm_jump(self, points: np.ndarray, region: str) -> float:
        chain = LEFT_ARM if region == "left_arm" else RIGHT_ARM
        if not np.isfinite(points[list(chain)]).all() or not np.isfinite(self.stable[list(chain)]).all():
            return float("nan")
        current = (points[chain[1]] - points[chain[0]], points[chain[2]] - points[chain[1]])
        previous = (self.stable[chain[1]] - self.stable[chain[0]], self.stable[chain[2]] - self.stable[chain[1]])
        return max(_angle_degrees(current[0], previous[0]), _angle_degrees(current[1], previous[1]))

    def _arm_vectors(self, points: np.ndarray, region: str) -> tuple[np.ndarray, np.ndarray] | None:
        chain = LEFT_ARM if region == "left_arm" else RIGHT_ARM
        if not np.isfinite(points[list(chain)]).all():
            return None
        return (points[chain[1]] - points[chain[0]],
                points[chain[2]] - points[chain[1]])

    def _coherent_reacquisition(self, points: np.ndarray, region: str) -> bool:
        """Accept a far-away arm after two mutually consistent observations."""
        current = self._arm_vectors(points, region)
        previous = self.pending_arm_vectors[region]
        if current is None:
            self.pending_arm_vectors[region] = None
            self.pending_arm_streak[region] = 0
            return False
        coherent = (previous is not None and
                    max(_angle_degrees(current[0], previous[0]),
                        _angle_degrees(current[1], previous[1])) <= 55.0)
        self.pending_arm_streak[region] = self.pending_arm_streak[region] + 1 if coherent else 1
        self.pending_arm_vectors[region] = (current[0].copy(), current[1].copy())
        if self.pending_arm_streak[region] >= 2:
            self.pending_arm_vectors[region] = None
            self.pending_arm_streak[region] = 0
            return True
        return False

    def _coherent_torso_reacquisition(self, points: np.ndarray) -> bool:
        """Allow a real turn while rejecting an isolated 180-degree flip."""
        current = _torso_geometry(points)
        previous = self.pending_torso_geometry
        if current is None:
            self.pending_torso_geometry = None
            self.pending_torso_streak = 0
            return False
        coherent = (
            previous is not None
            and _angle_degrees(current[0], previous[0]) <= 35.0
            and _angle_degrees(current[2], previous[2]) <= 35.0
        )
        self.pending_torso_streak = self.pending_torso_streak + 1 if coherent else 1
        self.pending_torso_geometry = tuple(value.copy() for value in current)
        if self.pending_torso_streak >= 3:
            self.pending_torso_geometry = None
            self.pending_torso_streak = 0
            return True
        return False

    def _hold_region(self, points: np.ndarray, scores: np.ndarray, region: str) -> tuple[int, ...]:
        indices = {"torso": TORSO, "left_arm": (7, 9), "right_arm": (8, 10), "head": (0,)}[region]
        held: list[int] = []
        for index in indices:
            if np.isfinite(self.stable[index]).all():
                points[index] = self.stable[index]
                scores[index] = 0.0
                held.append(index)
        return tuple(held)

    def _update_length_history(self, points: np.ndarray, rejected: set[str]) -> None:
        for name, ((start, end), _, region) in BONE_SPECS.items():
            if region not in rejected and np.isfinite(points[[start, end]]).all():
                self.length_history[name].append(float(np.linalg.norm(points[end] - points[start])))

    def update(self, joints: np.ndarray, confidence: np.ndarray, timestamp_ns: int) -> V61CompletionResult:
        old_last = self.last.copy()
        old_previous = self.previous.copy()
        old_last_ns = self.last_ns.copy()
        old_previous_ns = self.previous_ns.copy()
        old_age = self.age.copy()
        base = super().update(joints, confidence, timestamp_ns)
        points = base.joints.copy()
        scores = base.confidence.copy()
        observed = np.asarray(joints, dtype=np.float32)
        observed_confidence = np.asarray(confidence, dtype=np.float32)
        self._restore_coherent_observations(
            points, scores, observed, observed_confidence
        )
        rejected = self._bone_rejections(points)
        corrected_left_right = False
        orientation_jump = float("nan")
        shoulder_jump = float("nan")

        current_geometry = _torso_geometry(points)
        stable_geometry = _torso_geometry(self.stable)
        if current_geometry is not None and stable_geometry is not None:
            shoulder_jump = _angle_degrees(current_geometry[0], stable_geometry[0])
            orientation_jump = _angle_degrees(current_geometry[2], stable_geometry[2])
            if orientation_jump > self.torso_jump_deg or shoulder_jump > self.shoulder_jump_deg:
                swapped, swapped_scores = _swap_left_right(points[:17], scores[:17])
                swapped_geometry = _torso_geometry(swapped)
                if swapped_geometry is not None:
                    swapped_orientation = _angle_degrees(swapped_geometry[2], stable_geometry[2])
                    swapped_shoulder = _angle_degrees(swapped_geometry[0], stable_geometry[0])
                    original_cost = self._continuity_cost(points[:17], self.stable)
                    swapped_cost = self._continuity_cost(swapped, self.stable)
                    if (swapped_orientation < self.torso_jump_deg
                            and swapped_shoulder < self.shoulder_jump_deg
                            and swapped_cost < original_cost * 0.70):
                        points[:17] = swapped
                        scores[:17] = swapped_scores
                        orientation_jump = swapped_orientation
                        shoulder_jump = swapped_shoulder
                        corrected_left_right = True
                        rejected.discard("torso")
                    else:
                        hard_flip = max(orientation_jump, shoulder_jump) >= 120.0
                        if hard_flip:
                            self.pending_torso_geometry = None
                            self.pending_torso_streak = 0
                            rejected.add("torso")
                        elif self._coherent_torso_reacquisition(points):
                            rejected.discard("torso")
                        else:
                            rejected.add("torso")
            else:
                self.pending_torso_geometry = None
                self.pending_torso_streak = 0

        for region in ("left_arm", "right_arm"):
            jump = self._arm_jump(points, region)
            if np.isfinite(jump) and jump > self.arm_jump_deg:
                if not self._coherent_reacquisition(points, region):
                    rejected.add(region)
            else:
                self.pending_arm_vectors[region] = None
                self.pending_arm_streak[region] = 0

        current_geometry = _torso_geometry(points)
        if current_geometry is not None and np.isfinite(points[0]).all():
            mid_shoulder = (points[5] + points[6]) * 0.5
            head = points[0] - mid_shoulder
            normal = current_geometry[2].copy()
            head[1] = 0.0
            normal[1] = 0.0
            head_u = _unit(head)
            normal_u = _unit(normal)
            if head_u is not None and normal_u is not None:
                score = float(np.dot(head_u, normal_u))
                reference = float(np.median(self.head_sign_history)) if len(self.head_sign_history) >= 5 else 0.0
                if reference != 0.0 and score * np.sign(reference) < -0.25:
                    rejected.add("head")
                elif abs(score) >= 0.15:
                    self.head_sign_history.append(score)

        held: list[int] = []
        if "torso" in rejected:
            observed_shoulders = points[[5, 6]].copy()
            held.extend(self._hold_region(points, scores, "torso"))
            # Preserve independently valid arm motion by re-anchoring each
            # current local arm vector to the last trusted shoulder.
            for region, shoulder, endpoints in (
                ("left_arm", 5, (7, 9)),
                ("right_arm", 6, (8, 10)),
            ):
                side = 0 if shoulder == 5 else 1
                if (
                    region not in rejected
                    and np.isfinite(observed_shoulders[side]).all()
                    and np.isfinite(points[shoulder]).all()
                ):
                    offset = points[shoulder] - observed_shoulders[side]
                    points[list(endpoints)] += offset
        for region in ("left_arm", "right_arm", "head"):
            if region in rejected:
                held.extend(self._hold_region(points, scores, region))

        # Initialization needs a trustworthy body frame. Arms and head are
        # independently guarded and must not delay the complete bridge startup.
        startup_indices = np.asarray((5, 6, 11, 12))
        # PK-SSM has no trustworthy per-joint confidence. Finite raw
        # coordinates plus the anatomy/orientation checks are the signal.
        directly_observed = bool(np.isfinite(observed[startup_indices]).all())
        clean = (
            "torso" not in rejected
            and directly_observed
            and np.isfinite(points[startup_indices]).all()
        )
        self.stable_streak = self.stable_streak + 1 if clean else 0
        region_indices = {"torso": TORSO, "left_arm": (7, 9), "right_arm": (8, 10), "head": (0,)}
        for region, indices in region_indices.items():
            if region not in rejected:
                for index in indices:
                    if np.isfinite(points[index]).all():
                        self.stable[index] = points[index]
                        self.stable_confidence[index] = scores[index]
        self._update_length_history(points, rejected)
        self.ready = self.ready or self.stable_streak >= self.stable_frames

        rejected_indices = set(held)
        for region in rejected:
            rejected_indices.update(region_indices[region])
        for index in rejected_indices:
            self.last[index] = old_last[index]
            self.previous[index] = old_previous[index]
            self.last_ns[index] = old_last_ns[index]
            self.previous_ns[index] = old_previous_ns[index]
            self.age[index] = min(int(old_age[index]) + 1, 1_000_000)
        for index in range(17):
            if index not in rejected_indices and np.isfinite(points[index]).all():
                self.previous[index] = old_last[index]
                self.previous_ns[index] = old_last_ns[index]
                self.last[index] = points[index]
                self.last_ns[index] = int(timestamp_ns)
                self.age[index] = 0

        return V61CompletionResult(
            points, scores, base.predicted,
            tuple(sorted(set(base.stale).union(held))),
            tuple(sorted(set(base.rejected_outliers).union(rejected_indices))),
            self.ready, self.stable_streak, corrected_left_right,
            tuple(sorted(rejected)),
            None if not np.isfinite(orientation_jump) else orientation_jump,
            None if not np.isfinite(shoulder_jump) else shoulder_jump,
        )
