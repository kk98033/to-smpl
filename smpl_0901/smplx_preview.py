"""SMPL-X diagnostic preview driven by fitted SMPL body and raw Hand21 joints.

The production Unity protocol remains unchanged.  This module exists only for
the local Dashboard preview: it transfers the compatible SMPL body rotations
to SMPL-X and solves wrist/finger swing rotations from the same Hand21 targets
that Unity's RawHandRetargeter receives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


HAND21_CHAINS = {
    "thumb": (1, 2, 3, 4),
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}

# SMPL-X kinematic indices.  Pose-vector order is index, middle, pinky, ring,
# thumb for each hand, matching smplx.joint_names.JOINT_NAMES.
SMPLX_HAND_CHAINS = {
    "left": {
        "index": (25, 26, 27, 67),
        "middle": (28, 29, 30, 68),
        "pinky": (31, 32, 33, 70),
        "ring": (34, 35, 36, 69),
        "thumb": (37, 38, 39, 66),
    },
    "right": {
        "index": (40, 41, 42, 72),
        "middle": (43, 44, 45, 73),
        "pinky": (46, 47, 48, 75),
        "ring": (49, 50, 51, 74),
        "thumb": (52, 53, 54, 71),
    },
}
WRIST_JOINT = {"left": 20, "right": 21}
PALM_FINGERS = ("index", "middle", "pinky")


def _normalise(vector: np.ndarray) -> np.ndarray | None:
    value = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(value))
    if not np.isfinite(norm) or norm < 1e-7:
        return None
    return value / norm


def _align(source: np.ndarray, target: np.ndarray) -> Rotation:
    source_unit = _normalise(source)
    target_unit = _normalise(target)
    if source_unit is None or target_unit is None:
        return Rotation.identity()
    cross = np.cross(source_unit, target_unit)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(source_unit, target_unit), -1.0, 1.0))
    if sine < 1e-8:
        if cosine > 0:
            return Rotation.identity()
        helper = np.array((1.0, 0.0, 0.0))
        if abs(source_unit[0]) > 0.8:
            helper = np.array((0.0, 1.0, 0.0))
        axis = _normalise(np.cross(source_unit, helper))
        return Rotation.identity() if axis is None else Rotation.from_rotvec(axis * np.pi)
    return Rotation.from_rotvec(cross / sine * np.arctan2(sine, cosine))


def _global_rotations(local_rotvec: np.ndarray, parents: np.ndarray) -> list[Rotation]:
    local = Rotation.from_rotvec(np.asarray(local_rotvec, dtype=np.float64))
    result: list[Rotation] = []
    for index in range(len(parents)):
        current = local[index]
        parent = int(parents[index])
        result.append(current if parent < 0 else result[parent] * current)
    return result


def _limit_delta(previous: np.ndarray, current: np.ndarray, limit_deg: float) -> np.ndarray:
    old = Rotation.from_rotvec(np.asarray(previous, dtype=np.float64))
    new = Rotation.from_rotvec(np.asarray(current, dtype=np.float64))
    delta = old.inv() * new
    vector = delta.as_rotvec()
    magnitude = float(np.linalg.norm(vector))
    limit = np.deg2rad(limit_deg)
    if magnitude > limit:
        vector *= limit / magnitude
    return (old * Rotation.from_rotvec(vector)).as_rotvec().astype(np.float32)


def solve_hand_pose(
    side: str,
    hand21: np.ndarray,
    confidence: np.ndarray,
    rest_joints: np.ndarray,
    parents: np.ndarray,
    local_rotvec: np.ndarray,
    previous_hand_pose: np.ndarray | None = None,
    *,
    min_confidence: float = 0.05,
    max_delta_deg: float = 55.0,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Solve one SMPL-X wrist plus 15 finger rotations from Hand21 directions."""
    if side not in ("left", "right"):
        raise ValueError("side must be left or right")
    target = np.asarray(hand21, dtype=np.float32)
    scores = np.asarray(confidence, dtype=np.float32).reshape(-1)
    pose = np.asarray(local_rotvec, dtype=np.float32).copy()
    if target.shape != (21, 3) or scores.shape != (21,):
        raise ValueError("hand21/confidence must have shapes [21,3] and [21]")
    required = (0, 5, 9, 17)
    if not np.isfinite(target).all() or any(scores[index] <= min_confidence for index in required):
        return pose, np.zeros((15, 3), dtype=np.float32), False

    wrist = WRIST_JOINT[side]
    globals_before = _global_rotations(pose[:55], parents)
    parent = int(parents[wrist])
    source_vectors, target_vectors = [], []
    for finger in PALM_FINGERS:
        first_joint = SMPLX_HAND_CHAINS[side][finger][0]
        hand_index = HAND21_CHAINS[finger][0]
        source = _normalise(rest_joints[first_joint] - rest_joints[wrist])
        observed = _normalise(target[hand_index] - target[0])
        if source is not None and observed is not None:
            source_vectors.append(source)
            target_vectors.append(observed)
    if len(source_vectors) < 2:
        return pose, np.zeros((15, 3), dtype=np.float32), False
    desired_global, _ = Rotation.align_vectors(
        np.asarray(target_vectors), np.asarray(source_vectors)
    )
    desired_local = globals_before[parent].inv() * desired_global
    pose[wrist] = _limit_delta(pose[wrist], desired_local.as_rotvec(), max_delta_deg)

    hand_order = ("index", "middle", "pinky", "ring", "thumb")
    solved = np.zeros((15, 3), dtype=np.float32)
    previous = (
        np.zeros((15, 3), dtype=np.float32)
        if previous_hand_pose is None else np.asarray(previous_hand_pose, dtype=np.float32).reshape(15, 3)
    )
    for finger_offset, finger in enumerate(hand_order):
        smpl_chain = SMPLX_HAND_CHAINS[side][finger]
        target_chain = HAND21_CHAINS[finger]
        for level in range(3):
            joint = smpl_chain[level]
            child = smpl_chain[level + 1]
            target_start = target_chain[level]
            target_end = target_chain[level + 1]
            if min(scores[target_start], scores[target_end]) <= min_confidence:
                value = previous[finger_offset * 3 + level]
            else:
                globals_now = _global_rotations(pose[:55], parents)
                parent = int(parents[joint])
                rest_vector = rest_joints[child] - rest_joints[joint]
                target_vector = target[target_end] - target[target_start]
                swing = _align(globals_now[parent].apply(rest_vector), target_vector)
                desired_global = swing * globals_now[parent]
                desired_local = globals_now[parent].inv() * desired_global
                index = finger_offset * 3 + level
                value = _limit_delta(previous[index], desired_local.as_rotvec(), max_delta_deg)
            pose[joint] = value
            solved[finger_offset * 3 + level] = value
    return pose, solved, True


@dataclass(frozen=True)
class SmplXPreviewResult:
    vertices: object
    joints: object
    body_pose: np.ndarray
    left_hand_pose: np.ndarray
    right_hand_pose: np.ndarray
    left_valid: bool
    right_valid: bool


class SmplXPreview:
    """Load licensed SMPL-X locally and produce a dashboard-only forward mesh."""

    def __init__(self, model_file: Path, device) -> None:
        import smplx
        import torch

        self.torch = torch
        self.device = device
        self.model = smplx.create(
            str(model_file.parent.parent), model_type="smplx", gender="neutral",
            ext=model_file.suffix.lstrip("."), use_pca=False,
            flat_hand_mean=True, num_betas=10, num_expression_coeffs=10,
        ).to(device)
        self.model.eval()
        with torch.no_grad():
            neutral = self.model(return_verts=True)
        self.rest_joints = neutral.joints[0].detach().cpu().numpy()
        self.parents = self.model.parents.detach().cpu().numpy()
        self.faces = np.asarray(self.model.faces, dtype=np.int32)
        self.previous_left = np.zeros((15, 3), dtype=np.float32)
        self.previous_right = np.zeros((15, 3), dtype=np.float32)

    def _retarget_surface_to_smpl24(self, output, target_smpl24):
        """Warp SMPL-X smoothly onto the fitted SMPL skeleton.

        SMPL and SMPL-X share body-pose semantics, but their joint centres and
        shape spaces are not numerically identical.  Copying rotations alone
        leaves a visible 5--10 cm offset.  Blend each corresponding joint's
        translation delta with the official SMPL-X skinning weights; fingers
        inherit their wrist correction and retain their independently solved
        rotations.
        """
        torch = self.torch
        target = torch.as_tensor(
            np.asarray(target_smpl24, dtype=np.float32).reshape(24, 3),
            device=self.device,
        )[:22]
        pelvis = output.joints[:, 0:1]
        source_joints = output.joints - pelvis
        vertices = output.vertices - pelvis
        joint_delta = torch.zeros(
            (1, 55, 3), dtype=vertices.dtype, device=self.device
        )
        joint_delta[:, :22] = target[None] - source_joints[:, :22]
        joint_delta[:, 22:25] = joint_delta[:, 15:16]
        joint_delta[:, 25:40] = joint_delta[:, 20:21]
        joint_delta[:, 40:55] = joint_delta[:, 21:22]
        correction = torch.einsum(
            "vj,bjk->bvk", self.model.lbs_weights, joint_delta
        )
        corrected_vertices = vertices + correction
        corrected_joints = source_joints.clone()
        corrected_joints[:, :22] = target[None]
        corrected_joints[:, 22:55] += joint_delta[:, 22:55]
        return corrected_vertices, corrected_joints

    def forward(
        self,
        root: np.ndarray,
        smpl_body: np.ndarray,
        betas,
        target_smpl24: np.ndarray,
        left_hand21: np.ndarray,
        left_confidence: np.ndarray,
        right_hand21: np.ndarray,
        right_confidence: np.ndarray,
    ) -> SmplXPreviewResult:
        body = np.asarray(smpl_body, dtype=np.float32).reshape(23, 3)[:21].copy()
        local = np.zeros((55, 3), dtype=np.float32)
        local[0] = np.asarray(root, dtype=np.float32).reshape(3)
        local[1:22] = body
        local, left_pose, left_valid = solve_hand_pose(
            "left", left_hand21, left_confidence, self.rest_joints,
            self.parents, local, self.previous_left,
        )
        local, right_pose, right_valid = solve_hand_pose(
            "right", right_hand21, right_confidence, self.rest_joints,
            self.parents, local, self.previous_right,
        )
        if left_valid:
            self.previous_left = left_pose.copy()
        else:
            left_pose = self.previous_left.copy()
        if right_valid:
            self.previous_right = right_pose.copy()
        else:
            right_pose = self.previous_right.copy()

        # The wrist rotations solved above belong to SMPL-X body_pose, while
        # finger rotations are passed through the two explicit hand tensors.
        body = local[1:22]
        tensor = self.torch.as_tensor
        with self.torch.no_grad():
            output = self.model(
                betas=betas.reshape(1, 10),
                global_orient=tensor(local[0:1], device=self.device),
                body_pose=tensor(body.reshape(1, 63), device=self.device),
                left_hand_pose=tensor(left_pose.reshape(1, 45), device=self.device),
                right_hand_pose=tensor(right_pose.reshape(1, 45), device=self.device),
                return_verts=True,
            )
            vertices, joints = self._retarget_surface_to_smpl24(
                output, target_smpl24
            )
        return SmplXPreviewResult(
            vertices, joints, body, left_pose, right_pose, left_valid, right_valid
        )
