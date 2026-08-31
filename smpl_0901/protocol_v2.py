"""Ground-truth-free runtime payload helpers for the 2026-08-04 integration.

The module deliberately has no Torch dependency.  It separates the three
runtime data paths that Unity needs: body pose, anchored root motion, and raw
wrist-local hand joints.  Quality state is carried with every frame so Unity
can display and record why a pose was accepted or held.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

import numpy as np


PROTOCOL_VERSION = 2
HAND_JOINT_COUNT = 21
POSE_DIM = 156
BETA_DIM = 10


class SolverState(str, Enum):
    TRACKING = "TRACKING"
    RECOVERED = "RECOVERED"
    ADAPTIVE_100 = "ADAPTIVE_100"
    KAMA_REINITIALIZE = "KAMA_REINITIALIZE"
    HOLD_INPUT_INVALID = "HOLD_INPUT_INVALID"
    TRACKING_LOST = "TRACKING_LOST"
    FAILED_HOLD = "FAILED_HOLD"


@dataclass(frozen=True)
class QualityPayload:
    inputValid: bool
    inputScore: float
    fitResidualMm: float
    worstJointResidualMm: float
    torsoOrientationDeg: float
    solverState: str
    stepsUsed: int
    reasons: list[str]


@dataclass(frozen=True)
class BodyPayload:
    rootPosition: list[float]
    pelvisWorld: list[float]
    rootRotation: list[float]
    rootConfidence: float
    pose: list[float]
    betas: list[float]


@dataclass(frozen=True)
class HandsPayload:
    leftLocalJoints: list[float]
    leftConfidence: list[float]
    rightLocalJoints: list[float]
    rightConfidence: list[float]


@dataclass(frozen=True)
class FramePayloadV2:
    protocolVersion: int
    frameId: int
    timestamp: float
    units: str
    calibrationId: str
    body: BodyPayload
    hands: HandsPayload
    quality: QualityPayload

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AdaptiveGateConfig:
    mean_residual_yellow_mm: float = 50.0
    worst_joint_yellow_mm: float = 120.0
    torso_yellow_deg: float = 10.0
    red_after_consecutive_failures: int = 2
    lost_after_consecutive_invalid: int = 3
    green_after_consecutive_passes: int = 3
    cooldown_frames: int = 3


@dataclass(frozen=True)
class GateDecision:
    state: SolverState
    accept_output: bool
    extra_steps: int
    should_reinitialize: bool


class AdaptiveGateController:
    """Hysteretic no-GT controller for Input Gate and fitting residuals."""

    def __init__(self, config: AdaptiveGateConfig | None = None):
        self.config = config or AdaptiveGateConfig()
        self.invalid_streak = 0
        self.fit_fail_streak = 0
        self.pass_streak = 0
        self.cooldown_remaining = 0

    def update(
        self,
        *,
        input_valid: bool,
        mean_residual_mm: float | None,
        worst_joint_mm: float | None,
        torso_deg: float | None,
    ) -> GateDecision:
        cfg = self.config
        if not input_valid:
            self.invalid_streak += 1
            self.fit_fail_streak = 0
            self.pass_streak = 0
            state = (
                SolverState.TRACKING_LOST
                if self.invalid_streak >= cfg.lost_after_consecutive_invalid
                else SolverState.HOLD_INPUT_INVALID
            )
            return GateDecision(state, False, 0, False)

        self.invalid_streak = 0
        values = (mean_residual_mm, worst_joint_mm, torso_deg)
        finite = all(value is not None and np.isfinite(value) for value in values)
        failed = (
            not finite
            or float(mean_residual_mm) > cfg.mean_residual_yellow_mm
            or float(worst_joint_mm) > cfg.worst_joint_yellow_mm
            or float(torso_deg) > cfg.torso_yellow_deg
        )

        if failed:
            self.fit_fail_streak += 1
            self.pass_streak = 0
            if self.cooldown_remaining > 0:
                self.cooldown_remaining -= 1
                return GateDecision(SolverState.FAILED_HOLD, False, 0, False)
            if self.fit_fail_streak >= cfg.red_after_consecutive_failures:
                self.cooldown_remaining = cfg.cooldown_frames
                return GateDecision(SolverState.KAMA_REINITIALIZE, False, 100, True)
            return GateDecision(SolverState.ADAPTIVE_100, False, 100, False)

        self.fit_fail_streak = 0
        self.pass_streak += 1
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
        state = SolverState.TRACKING if self.pass_streak >= cfg.green_after_consecutive_passes else SolverState.RECOVERED
        return GateDecision(state, True, 0, False)


@dataclass(frozen=True)
class RootMotionConfig:
    smoothing_alpha: float = 0.35
    dead_zone_m: float = 0.015
    max_speed_mps: float = 3.0
    apply_vertical: bool = False


class RootMotionStabilizer:
    """Convert absolute pelvis world coordinates to a stable anchored delta."""

    def __init__(self, config: RootMotionConfig | None = None):
        self.config = config or RootMotionConfig()
        self.anchor: np.ndarray | None = None
        self.filtered_delta = np.zeros(3, dtype=np.float32)
        self.last_timestamp: float | None = None

    def reset(self) -> None:
        self.anchor = None
        self.filtered_delta[:] = 0.0
        self.last_timestamp = None

    def update(self, pelvis_world: Iterable[float], timestamp: float, reliable: bool) -> np.ndarray:
        pelvis = np.asarray(pelvis_world, dtype=np.float32).reshape(3)
        if not reliable or not np.isfinite(pelvis).all():
            return self.filtered_delta.copy()
        if self.anchor is None:
            self.anchor = pelvis.copy()
            self.filtered_delta[:] = 0.0
            self.last_timestamp = float(timestamp)
            return self.filtered_delta.copy()

        raw_delta = pelvis - self.anchor
        if not self.config.apply_vertical:
            raw_delta[1] = 0.0
        raw_delta[np.abs(raw_delta) < self.config.dead_zone_m] = 0.0

        previous_timestamp = float(timestamp) if self.last_timestamp is None else float(self.last_timestamp)
        dt = max(float(timestamp) - previous_timestamp, 1.0 / 120.0)
        max_step = self.config.max_speed_mps * dt
        change = raw_delta - self.filtered_delta
        distance = float(np.linalg.norm(change))
        if distance > max_step:
            raw_delta = self.filtered_delta + change * (max_step / max(distance, 1e-8))
        alpha = float(np.clip(self.config.smoothing_alpha, 0.0, 1.0))
        self.filtered_delta = ((1.0 - alpha) * self.filtered_delta + alpha * raw_delta).astype(np.float32)
        self.last_timestamp = float(timestamp)
        return self.filtered_delta.copy()


def _normalise(vector: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm < 1e-6:
        return None
    return vector / norm


def wrist_local_hand(
    joints_world: np.ndarray,
    confidence: np.ndarray | None = None,
    *,
    side: str,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Create a palm-coordinate 21-joint hand without requiring ground truth.

    Input uses MediaPipe/COCO-WholeBody hand order: wrist=0, index MCP=5,
    middle MCP=9, pinky MCP=17.  The right palm x-axis is mirrored so both
    hands use the same semantic local convention.
    """

    joints = np.asarray(joints_world, dtype=np.float32)
    if joints.shape != (HAND_JOINT_COUNT, 3):
        raise ValueError(f"Expected hand shape (21, 3), got {joints.shape}")
    conf = np.ones(HAND_JOINT_COUNT, dtype=np.float32) if confidence is None else np.asarray(confidence, dtype=np.float32)
    if conf.shape != (HAND_JOINT_COUNT,):
        raise ValueError(f"Expected confidence shape (21,), got {conf.shape}")
    side_lower = side.lower()
    if side_lower not in {"left", "right"}:
        raise ValueError("side must be 'left' or 'right'")

    required = (0, 5, 9, 17)
    valid = np.isfinite(joints).all() and all(conf[index] > 0.0 for index in required)
    if not valid:
        return np.zeros_like(joints), np.clip(conf, 0.0, 1.0), False

    wrist = joints[0]
    x_axis = joints[5] - joints[17]
    if side_lower == "right":
        x_axis = -x_axis
    x_axis = _normalise(x_axis)
    y_hint = _normalise(joints[9] - wrist)
    if x_axis is None or y_hint is None:
        return np.zeros_like(joints), np.clip(conf, 0.0, 1.0), False
    z_axis = _normalise(np.cross(x_axis, y_hint))
    if z_axis is None:
        return np.zeros_like(joints), np.clip(conf, 0.0, 1.0), False
    y_axis = _normalise(np.cross(z_axis, x_axis))
    if y_axis is None:
        return np.zeros_like(joints), np.clip(conf, 0.0, 1.0), False

    basis = np.stack((x_axis, y_axis, z_axis), axis=1)
    local = (joints - wrist) @ basis
    return local.astype(np.float32), np.clip(conf, 0.0, 1.0), True


def build_frame_payload(
    *,
    frame_id: int,
    timestamp: float,
    root_position: np.ndarray,
    pelvis_world: np.ndarray,
    root_rotation_xyzw: np.ndarray,
    root_confidence: float,
    pose: np.ndarray,
    betas: np.ndarray,
    left_local: np.ndarray,
    left_confidence: np.ndarray,
    right_local: np.ndarray,
    right_confidence: np.ndarray,
    quality: QualityPayload,
    calibration_id: str,
) -> FramePayloadV2:
    pose_array = np.asarray(pose, dtype=np.float32).reshape(-1)
    beta_array = np.asarray(betas, dtype=np.float32).reshape(-1)
    rotation = np.asarray(root_rotation_xyzw, dtype=np.float32).reshape(-1)
    if pose_array.size != POSE_DIM:
        raise ValueError(f"pose must contain {POSE_DIM} values")
    if beta_array.size != BETA_DIM:
        raise ValueError(f"betas must contain {BETA_DIM} values")
    if rotation.size != 4:
        raise ValueError("root rotation must be quaternion (x, y, z, w)")
    return FramePayloadV2(
        protocolVersion=PROTOCOL_VERSION,
        frameId=int(frame_id),
        timestamp=float(timestamp),
        units="meter",
        calibrationId=str(calibration_id),
        body=BodyPayload(
            rootPosition=np.asarray(root_position, dtype=np.float32).reshape(3).tolist(),
            pelvisWorld=np.asarray(pelvis_world, dtype=np.float32).reshape(3).tolist(),
            rootRotation=rotation.tolist(),
            rootConfidence=float(np.clip(root_confidence, 0.0, 1.0)),
            pose=pose_array.tolist(),
            betas=beta_array.tolist(),
        ),
        hands=HandsPayload(
            leftLocalJoints=np.asarray(left_local, dtype=np.float32).reshape(-1).tolist(),
            leftConfidence=np.asarray(left_confidence, dtype=np.float32).reshape(21).tolist(),
            rightLocalJoints=np.asarray(right_local, dtype=np.float32).reshape(-1).tolist(),
            rightConfidence=np.asarray(right_confidence, dtype=np.float32).reshape(21).tolist(),
        ),
        quality=quality,
    )
