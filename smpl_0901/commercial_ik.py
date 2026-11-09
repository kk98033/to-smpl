"""Asset-independent humanoid IK for the commercial deployment path.

This module intentionally does not import torch, smplx, chumpy, a parametric
body model, or a learned checkpoint.  It uses a 22-joint humanoid wire order,
calibrates only bone lengths, and solves local rotations analytically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation


JOINT_NAMES = (
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee",
    "right_knee", "spine2", "left_ankle", "right_ankle", "spine3",
    "left_foot", "right_foot", "neck", "left_collar", "right_collar",
    "head", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand",
)
PARENTS = np.asarray(
    (-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19, 20, 21),
    dtype=np.int32,
)
UPPER11 = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12)
LOWER4 = (10, 11, 13, 14)
BODY15 = tuple(range(15))
SPINE_JOINTS = (3, 6, 9)


def _unit(value, fallback=None):
    vector = np.asarray(value, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    if np.isfinite(norm) and norm > 1e-8:
        return vector / norm
    return np.zeros(3) if fallback is None else _unit(fallback)


def _basis(right, up, forward_hint=None):
    x_axis = _unit(right, (1, 0, 0))
    up = np.asarray(up, dtype=np.float64)
    y_axis = _unit(up - x_axis * np.dot(up, x_axis), (0, 1, 0))
    z_axis = _unit(np.cross(x_axis, y_axis), (0, 0, 1))
    if forward_hint is not None and np.dot(z_axis, forward_hint) < 0:
        z_axis *= -1
        x_axis *= -1
    x_axis = _unit(np.cross(y_axis, z_axis), x_axis)
    return Rotation.from_matrix(np.stack((x_axis, y_axis, z_axis), axis=1))


def _alignment(source, target):
    source, target = _unit(source), _unit(target)
    if not np.any(source) or not np.any(target):
        return Rotation.identity()
    cross = np.cross(source, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(source, target), -1, 1))
    if sine < 1e-8:
        if cosine > 0:
            return Rotation.identity()
        helper = np.asarray((1.0, 0.0, 0.0))
        if abs(source[0]) > 0.8:
            helper = np.asarray((0.0, 1.0, 0.0))
        return Rotation.from_rotvec(_unit(np.cross(source, helper)) * np.pi)
    return Rotation.from_rotvec(cross / sine * np.arctan2(sine, cosine))


def _limit_delta(previous, current, limit_deg):
    delta = previous.inv() * current
    vector = delta.as_rotvec()
    magnitude, limit = float(np.linalg.norm(vector)), float(np.deg2rad(limit_deg))
    if magnitude > limit > 0:
        vector *= limit / magnitude
    return previous * Rotation.from_rotvec(vector)


def _median_length(frames, start, end, fallback):
    values = np.linalg.norm(frames[:, end] - frames[:, start], axis=1)
    values = values[np.isfinite(values) & (values > 0.03) & (values < 1.5)]
    return float(np.median(values)) if values.size else float(fallback)


@dataclass(frozen=True)
class GenericRig:
    rest_joints: np.ndarray
    parents: np.ndarray

    @classmethod
    def calibrate(cls, body25_frames):
        frames = np.asarray(body25_frames, dtype=np.float32)
        if frames.ndim != 3 or frames.shape[1:] != (25, 3):
            raise ValueError(f"calibration must be [N,25,3], got {frames.shape}")
        torso = _median_length(frames, 8, 1, 0.55)
        shoulders = _median_length(frames, 2, 5, torso * 0.72)
        hips = _median_length(frames, 9, 12, torso * 0.36)
        lu, ru = _median_length(frames, 5, 6, torso * .55), _median_length(frames, 2, 3, torso * .55)
        lf, rf = _median_length(frames, 6, 7, torso * .48), _median_length(frames, 3, 4, torso * .48)
        lt, rt = _median_length(frames, 12, 13, torso * .78), _median_length(frames, 9, 10, torso * .78)
        ls, rs = _median_length(frames, 13, 14, torso * .76), _median_length(frames, 10, 11, torso * .76)
        head = _median_length(frames, 1, 0, torso * .32)
        hand, foot = max(.12, .16 * (lf + rf)), max(.16, .19 * (ls + rs))
        rest = np.zeros((24, 3), dtype=np.float32)
        rest[1], rest[2] = (hips / 2, 0, 0), (-hips / 2, 0, 0)
        rest[3], rest[6], rest[9], rest[12] = (0, torso*.24, 0), (0, torso*.50, 0), (0, torso*.76, 0), (0, torso, 0)
        rest[15] = (0, torso + head*.72, 0)
        rest[13], rest[14] = (shoulders*.22, torso*.94, 0), (-shoulders*.22, torso*.94, 0)
        rest[16], rest[17] = (shoulders/2, torso, 0), (-shoulders/2, torso, 0)
        rest[18], rest[19] = rest[16] + (lu, 0, 0), rest[17] + (-ru, 0, 0)
        rest[20], rest[21] = rest[18] + (lf, 0, 0), rest[19] + (-rf, 0, 0)
        rest[22], rest[23] = rest[20] + (hand, 0, 0), rest[21] + (-hand, 0, 0)
        rest[4], rest[5] = rest[1] + (0, -lt, 0), rest[2] + (0, -rt, 0)
        rest[7], rest[8] = rest[4] + (0, -ls, 0), rest[5] + (0, -rs, 0)
        rest[10], rest[11] = rest[7] + (0, 0, foot), rest[8] + (0, 0, foot)
        return cls(rest, PARENTS.copy())


@dataclass(frozen=True)
class GenericIkResult:
    pose_rotvec: np.ndarray
    joints24: np.ndarray
    body25: np.ndarray
    residual_mm: float
    joint_residual_mm: np.ndarray
    torso_orientation_deg: float
    elapsed_seconds: float
    held_joints: tuple[int, ...]
    residual_joints: tuple[int, ...]


class GenericIkTracker:
    """Causal fixed-length humanoid IK with no parametric-body dependency."""

    def __init__(self, rig, max_delta_deg=75.0):
        self.rig, self.max_delta_deg = rig, float(max_delta_deg)
        self.previous = self.previous_target = self.previous_timestamp_ns = None

    def reset(self):
        self.previous = self.previous_target = self.previous_timestamp_ns = None

    def _fk(self, local):
        positions = np.zeros((24, 3), dtype=np.float64)
        globals_ = []
        for joint, parent in enumerate(self.rig.parents):
            if parent < 0:
                globals_.append(local[joint])
                continue
            parent_rotation = globals_[int(parent)]
            positions[joint] = positions[int(parent)] + parent_rotation.apply(
                self.rig.rest_joints[joint] - self.rig.rest_joints[int(parent)])
            globals_.append(parent_rotation * local[joint])
        return positions, globals_

    def _set_direction(self, local, joint, child, target_vector, plane=None):
        _, globals_ = self._fk(local)
        parent = int(self.rig.parents[joint])
        parent_global = Rotation.identity() if parent < 0 else globals_[parent]
        current = globals_[joint]
        source = current.apply(self.rig.rest_joints[child] - self.rig.rest_joints[joint])
        desired = _alignment(source, target_vector) * current
        normal = _unit(plane) if plane is not None else np.zeros(3)
        if np.any(normal):
            axis = _unit(target_vector)
            old = desired.apply((0, 0, 1))
            old = _unit(old - axis * np.dot(old, axis))
            new = _unit(normal - axis * np.dot(normal, axis))
            if np.any(old) and np.any(new):
                desired = _alignment(old, new) * desired
        local[joint] = parent_global.inv() * desired

    def solve(self, body25, confidence=None, timestamp_ns=None):
        """Solve one pelvis-relative BODY25 frame into generic local rotations."""
        started = time.perf_counter()
        target = np.asarray(body25, dtype=np.float64).copy()
        if target.shape != (25, 3):
            raise ValueError(f"body25 must be [25,3], got {target.shape}")
        conf = (np.ones(25, dtype=np.float64) if confidence is None
                else np.asarray(confidence, dtype=np.float64).reshape(25))
        finite = np.isfinite(target).all(axis=1)
        relative = target - target[8] if finite[8] else target.copy()
        # Orientation/anatomy completion is allowed to fill short gaps, but a
        # runaway extrapolation several metres from the pelvis must never
        # drive the rig or the safety residual. Human whole-body joints stay
        # comfortably inside this deliberately generous radius.
        plausible = finite & (np.linalg.norm(relative, axis=1) < 2.5)
        usable = plausible & np.isfinite(conf) & (conf > 0)
        if self.previous_target is not None:
            # Reject discontinuities before temporal rotation limiting. The
            # previous trustworthy joint is held below, preserving a stable
            # avatar while the upstream observer reacquires the person.
            usable &= np.linalg.norm(
                relative - self.previous_target, axis=1
            ) < 0.75
        # Zero confidence may denote a causally imputed finite joint.
        missing_upper = [
            joint for joint in UPPER11
            if not plausible[joint] and self.previous_target is None
        ]
        if missing_upper:
            raise ValueError(f"incomplete upper-body joints: {missing_upper}")
        held = []
        if self.previous_target is not None:
            for joint in range(25):
                if not usable[joint]:
                    target[joint] = self.previous_target[joint]
                    held.append(joint)
        target -= target[8]

        local = [Rotation.identity() for _ in range(24)]
        up = _unit(target[1] - target[8])
        shoulder_axis = _unit(target[5] - target[2])
        hip_axis = _unit(target[12] - target[9])
        side = _unit(shoulder_axis + hip_axis)
        if not np.any(side):
            side = shoulder_axis if np.any(shoulder_axis) else hip_axis
        front = _unit(np.cross(side, up))
        if not np.any(front):
            front = np.asarray((0.0, 0.0, 1.0))
        side = _unit(np.cross(up, front))
        root_global = _basis(side, up, front)
        local[0] = root_global

        torso_delta = _alignment(root_global.apply((0.0, 1.0, 0.0)),
                                 target[1] - target[8])
        torso_vector = torso_delta.as_rotvec()
        for joint, weight in zip(SPINE_JOINTS, (0.20, 0.30, 0.50)):
            local[joint] = Rotation.from_rotvec(torso_vector * weight)

        self._set_direction(local, 13, 16, target[5] - target[1])
        self._set_direction(local, 14, 17, target[2] - target[1])
        left_plane = np.cross(target[6] - target[5], target[7] - target[6])
        right_plane = np.cross(target[3] - target[2], target[4] - target[3])
        self._set_direction(local, 16, 18, target[6] - target[5], left_plane)
        self._set_direction(local, 17, 19, target[3] - target[2], right_plane)
        self._set_direction(local, 18, 20, target[7] - target[6], left_plane)
        self._set_direction(local, 19, 21, target[4] - target[3], right_plane)
        # Hand21 is driven independently; do not add a second wrist twist.
        local[20] = local[21] = Rotation.identity()
        local[22] = local[23] = Rotation.identity()

        head_vector = target[0] - target[1]
        if np.dot(head_vector, front) < -0.05:
            head_vector = head_vector - front * np.dot(head_vector, front)
        self._set_direction(local, 12, 15, head_vector)
        if usable[12] and usable[13] and usable[14]:
            self._set_direction(local, 1, 4, target[13] - target[12])
            self._set_direction(local, 4, 7, target[14] - target[13])
        if usable[9] and usable[10] and usable[11]:
            self._set_direction(local, 2, 5, target[10] - target[9])
            self._set_direction(local, 5, 8, target[11] - target[10])

        if self.previous is not None:
            limit = self.max_delta_deg
            if timestamp_ns is not None and self.previous_timestamp_ns is not None:
                dt = max(0.0, (int(timestamp_ns) - int(self.previous_timestamp_ns)) * 1e-9)
                limit = min(limit, max(8.0, 540.0 * dt))
            local = [_limit_delta(old, new, limit)
                     for old, new in zip(self.previous, local)]

        joints24, _ = self._fk(local)
        predicted = np.full((25, 3), np.nan, dtype=np.float64)
        mapping = {8: 0, 12: 1, 9: 2, 13: 4, 10: 5, 14: 7, 11: 8,
                   1: 12, 0: 15, 5: 16, 2: 17, 6: 18, 3: 19,
                   7: 20, 4: 21}
        for body_joint, rig_joint in mapping.items():
            predicted[body_joint] = joints24[rig_joint]
        residual_joints = tuple(
            joint for joint in BODY15
            if usable[joint] and np.isfinite(predicted[joint]).all()
        )
        residual = np.linalg.norm(
            predicted[list(residual_joints)] - target[list(residual_joints)], axis=1)
        pose = np.zeros((52, 3), dtype=np.float32)
        pose[:22] = np.asarray(
            [rotation.as_rotvec() for rotation in local[:22]], dtype=np.float32)
        fitted_front = _unit(np.cross(
            joints24[16] - joints24[17], joints24[12] - joints24[0]))
        torso_angle = float(np.degrees(np.arccos(
            np.clip(np.dot(fitted_front, front), -1, 1))))

        self.previous = tuple(local)
        self.previous_target = target.copy()
        self.previous_timestamp_ns = None if timestamp_ns is None else int(timestamp_ns)
        return GenericIkResult(
            pose_rotvec=pose,
            joints24=joints24.astype(np.float32),
            body25=predicted.astype(np.float32),
            residual_mm=float(np.mean(residual) * 1000.0),
            joint_residual_mm=(residual * 1000.0).astype(np.float32),
            torso_orientation_deg=torso_angle,
            elapsed_seconds=time.perf_counter() - started,
            held_joints=tuple(held),
            residual_joints=residual_joints,
        )
