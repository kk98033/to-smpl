"""Hybrid v2: torso-root hypotheses plus explicit swing/twist Joint IK."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from scipy.spatial.transform import Rotation
from smplx.lbs import batch_rigid_transform, batch_rodrigues, blend_shapes, vertices2joints

from smpl_0901.frame0_initializer import build_root_candidates


LOWER_BODY_POSE = (0, 1, 3, 4, 6, 7, 9, 10)
SPINE_POSE = (2, 5, 8)
COLLAR_POSE = (12, 13)
FORWARD_LOCK = (11, 14, 19, 20)
ARM_CHAINS = (
    # SMPL joint, child, Body25 start/end, maximum axial twist.
    (16, 18, 5, 6, 45.0),
    (17, 19, 2, 3, 45.0),
    (18, 20, 6, 7, 20.0),
    (19, 21, 3, 4, 20.0),
)
UPPER11 = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12)
TORSO_ROOT_POINTS = (0, 1, 2, 5, 8, 9, 12)


@dataclass(frozen=True)
class JointIkV2Result:
    root_orient: torch.Tensor
    body_pose: torch.Tensor
    translation: torch.Tensor
    pred_body25: torch.Tensor
    pred_smpl24: torch.Tensor
    pred_vertices: torch.Tensor
    selected_root: str
    candidate_scores: tuple[tuple[str, float, float], ...]


def _alignment(source_vector: np.ndarray, target_vector: np.ndarray) -> Rotation:
    source = np.asarray(source_vector, dtype=np.float64)
    target = np.asarray(target_vector, dtype=np.float64)
    source_norm = float(np.linalg.norm(source))
    target_norm = float(np.linalg.norm(target))
    if source_norm < 1e-8 or target_norm < 1e-8:
        return Rotation.identity()
    source /= source_norm
    target /= target_norm
    cross = np.cross(source, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if sine < 1e-8:
        if cosine > 0.0:
            return Rotation.identity()
        helper = np.array([1.0, 0.0, 0.0])
        if abs(source[0]) > 0.8:
            helper = np.array([0.0, 1.0, 0.0])
        axis = np.cross(source, helper)
        axis /= max(float(np.linalg.norm(axis)), 1e-8)
        return Rotation.from_rotvec(axis * np.pi)
    return Rotation.from_rotvec(cross / sine * np.arctan2(sine, cosine))


def _clamp_rotvec(vector: np.ndarray, max_degrees: float) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float64)
    magnitude = float(np.linalg.norm(value))
    limit = np.deg2rad(max_degrees)
    if magnitude <= limit or magnitude < 1e-8:
        return value.astype(np.float32)
    return (value * (limit / magnitude)).astype(np.float32)


def _twist(rotation: Rotation, axis: np.ndarray, max_degrees: float) -> Rotation:
    """Project a local quaternion onto `axis` and clamp its signed twist."""
    unit = np.asarray(axis, dtype=np.float64)
    unit /= max(float(np.linalg.norm(unit)), 1e-8)
    quaternion = rotation.as_quat()  # scipy order: x, y, z, w
    projected = unit * float(np.dot(quaternion[:3], unit))
    twist_quaternion = np.concatenate((projected, quaternion[3:4]))
    norm = float(np.linalg.norm(twist_quaternion))
    if norm < 1e-8:
        return Rotation.identity()
    twist_quaternion /= norm
    signed = 2.0 * np.arctan2(
        float(np.dot(twist_quaternion[:3], unit)), float(twist_quaternion[3]))
    signed = (signed + np.pi) % (2.0 * np.pi) - np.pi
    limit = np.deg2rad(max_degrees)
    return Rotation.from_rotvec(unit * float(np.clip(signed, -limit, limit)))


def _rest_joints(smpl_layer, fixed_betas: torch.Tensor) -> torch.Tensor:
    beta = fixed_betas.reshape(1, 10)
    shaped = smpl_layer.v_template.unsqueeze(0) + blend_shapes(beta, smpl_layer.shapedirs)
    return vertices2joints(smpl_layer.J_regressor, shaped)


def _forward_kinematics(rest_joints: torch.Tensor, parents: torch.Tensor,
                        root_np: np.ndarray, body_np: np.ndarray, device):
    pose = np.concatenate((root_np.reshape(1, 3), body_np.reshape(23, 3)), axis=0)
    rotations = batch_rodrigues(
        torch.tensor(pose, dtype=torch.float32, device=device)
    ).view(1, 24, 3, 3)
    joints, transforms = batch_rigid_transform(rotations, rest_joints, parents)
    return (
        joints[0].detach().cpu().numpy(),
        transforms[0, :, :3, :3].detach().cpu().numpy(),
    )


def _facing_angle(target: np.ndarray, smpl24: np.ndarray,
                  facing_sign: float = 1.0) -> float:
    torso = np.cross(
        target[5] - target[2], (target[2] + target[5]) * 0.5 - target[8])
    feet = facing_sign * (
        (smpl24[10] - smpl24[7]) + (smpl24[11] - smpl24[8])) * 0.5
    torso[1] = 0.0
    feet[1] = 0.0
    denominator = float(np.linalg.norm(torso) * np.linalg.norm(feet))
    if denominator < 1e-8:
        return 0.0
    cosine = float(np.clip(np.dot(torso, feet) / denominator, -1.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def _kabsch_root(source_body25: np.ndarray, target_body25: np.ndarray) -> np.ndarray:
    indices = list(TORSO_ROOT_POINTS)
    source = source_body25[indices] - source_body25[[8]]
    target = target_body25[indices] - target_body25[[8]]
    weights = np.asarray((2.0, 1.5, 1.0, 1.0, 1.5, 1.0, 1.0), dtype=np.float64)
    try:
        rotation, _ = Rotation.align_vectors(target, source, weights=weights)
        return rotation.as_rotvec().astype(np.float32)
    except (ValueError, np.linalg.LinAlgError):
        return np.zeros(3, dtype=np.float32)


def _distribute_spine(body_np: np.ndarray) -> None:
    rotations = [Rotation.from_rotvec(body_np[index]) for index in SPINE_POSE]
    total = rotations[0] * rotations[1] * rotations[2]
    total_vector = _clamp_rotvec(total.as_rotvec(), 55.0)
    for index, weight in zip(SPINE_POSE, (0.20, 0.30, 0.50)):
        body_np[index] = _clamp_rotvec(total_vector * weight, 30.0)


def solve_joint_ik_v2(
    smpl_layer,
    body25_regressor: torch.Tensor,
    target_body25: torch.Tensor,
    fixed_betas: torch.Tensor,
    previous_root: torch.Tensor,
    previous_body: torch.Tensor,
    previous_translation: torch.Tensor,
    *,
    prior_root: torch.Tensor | None = None,
    prior_body: torch.Tensor | None = None,
    facing_sign: float = 1.0,
) -> JointIkV2Result:
    """Generate a bounded SMPL candidate from joints plus optional OG prior."""
    del previous_translation
    device = target_body25.device
    target_np = target_body25[0].detach().cpu().numpy()
    base = previous_body if prior_body is None else prior_body
    base_body_np = base.detach().cpu().numpy().reshape(23, 3).astype(np.float32).copy()
    previous_body_np = previous_body.detach().cpu().numpy().reshape(23, 3).astype(np.float32)
    previous_root_np = previous_root.detach().cpu().numpy().reshape(3).astype(np.float32)

    base_body_np[list(LOWER_BODY_POSE)] = previous_body_np[list(LOWER_BODY_POSE)]
    _distribute_spine(base_body_np)
    for index in COLLAR_POSE:
        base_body_np[index] = _clamp_rotvec(base_body_np[index], 35.0)
    base_body_np[list(FORWARD_LOCK)] = 0.0

    with torch.no_grad():
        rest = _rest_joints(smpl_layer, fixed_betas)
        rest_np = rest[0].detach().cpu().numpy()
        betas = fixed_betas.reshape(1, 10)
        neutral = smpl_layer(
            betas=betas,
            global_orient=torch.zeros((1, 1, 3), device=device),
            body_pose=torch.zeros((1, 23, 3), device=device),
        )
        neutral_body25 = torch.einsum(
            "bvc,jv->bjc", neutral.vertices, body25_regressor)[0].cpu().numpy()
        standard_roots, _ = build_root_candidates(target_np)
        # The analytical root is the only stateless production candidate used
        # during normal tracking. The helper also returns neutral and 180-degree
        # hypotheses, but those belong to Frame-0/reinitialisation only. If they
        # are admitted every frame, a flipped local optimum can win once and
        # force the temporal gate to HOLD for dozens of following frames.
        root_options = [("analytical", standard_roots.reshape(-1, 3)[0])]
        root_options.extend((
            ("torso_nose_kabsch", _kabsch_root(neutral_body25, target_np)),
            ("previous", previous_root_np),
        ))
        if prior_root is not None:
            root_options.append((
                "og_prior", prior_root.detach().cpu().numpy().reshape(3).astype(np.float32)))

        previous_rotation = Rotation.from_rotvec(previous_root_np)
        evaluated = []
        diagnostics = []
        for label, root_np in root_options:
            body_np = base_body_np.copy()
            for joint, child, target_start, target_end, twist_limit in ARM_CHAINS:
                _, global_rotations = _forward_kinematics(
                    rest, smpl_layer.parents, root_np, body_np, device)
                parent = int(smpl_layer.parents[joint])
                parent_global = global_rotations[parent]
                rest_vector = rest_np[child] - rest_np[joint]
                target_vector = target_np[target_end] - target_np[target_start]
                swing = _alignment(parent_global @ rest_vector, target_vector)
                prior_twist = _twist(
                    Rotation.from_rotvec(body_np[joint - 1]), rest_vector, twist_limit)
                desired_global = swing.as_matrix() @ parent_global @ prior_twist.as_matrix()
                desired_local = parent_global.T @ desired_global
                body_np[joint - 1] = Rotation.from_matrix(
                    desired_local).as_rotvec().astype(np.float32)
            body_np[list(FORWARD_LOCK)] = 0.0

            root_value = torch.tensor(root_np[None], dtype=torch.float32, device=device)
            body_value = torch.tensor(body_np[None], dtype=torch.float32, device=device)
            output = smpl_layer(
                betas=betas, global_orient=root_value.unsqueeze(1), body_pose=body_value)
            unaligned = torch.einsum("bvc,jv->bjc", output.vertices, body25_regressor)
            translation = target_body25[:, 8] - unaligned[:, 8]
            body25 = unaligned + translation[:, None]
            smpl24 = output.joints[:, :24] + translation[:, None]
            residual = torch.linalg.norm(
                body25[0, list(UPPER11)] - target_body25[0, list(UPPER11)], dim=-1
            ).mean().item()
            facing = _facing_angle(
                target_np, smpl24[0].cpu().numpy(), facing_sign)
            root_delta = float((previous_rotation.inv() * Rotation.from_rotvec(root_np)).magnitude())
            score = residual + 0.005 * root_delta + 0.02 * min(facing / 90.0, 2.0)
            evaluated.append((score, root_delta, label, root_value, body_value,
                              translation, body25, smpl24, output))
            diagnostics.append((label, float(residual * 1000.0), facing))

        facing_valid = [item for item in evaluated if _facing_angle(
            target_np, item[7][0].cpu().numpy(), facing_sign) <= 90.0]
        facing_pool = facing_valid if facing_valid else evaluated
        temporal_valid = [item for item in facing_pool if item[1] <= np.pi / 2.0]
        pool = temporal_valid if temporal_valid else facing_pool
        (_, _, selected, root, body, translation, pred_body25,
         pred_smpl24, output) = min(pool, key=lambda item: item[0])
        vertices = output.vertices + translation[:, None]

    return JointIkV2Result(
        root_orient=root,
        body_pose=body,
        translation=translation,
        pred_body25=pred_body25,
        pred_smpl24=pred_smpl24,
        pred_vertices=vertices,
        selected_root=selected,
        candidate_scores=tuple(diagnostics),
    )
