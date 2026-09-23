"""SMPL-skeleton Joint IK with an optional Learnable-SMPLify rotation prior."""

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
    (16, 18, 5, 6),
    (17, 19, 2, 3),
    (18, 20, 6, 7),
    (19, 21, 3, 4),
)


@dataclass(frozen=True)
class JointIkResult:
    root_orient: torch.Tensor
    body_pose: torch.Tensor
    translation: torch.Tensor
    pred_body25: torch.Tensor
    pred_smpl24: torch.Tensor
    pred_vertices: torch.Tensor


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


def _facing_mismatch(target: np.ndarray, smpl24: np.ndarray) -> bool:
    torso = np.cross(
        target[5] - target[2],
        (target[2] + target[5]) * 0.5 - target[8],
    )
    feet = ((smpl24[10] - smpl24[7]) + (smpl24[11] - smpl24[8])) * 0.5
    torso[1] = 0.0
    feet[1] = 0.0
    denominator = float(np.linalg.norm(torso) * np.linalg.norm(feet))
    if denominator < 1e-8:
        return False
    cosine = float(np.clip(np.dot(torso, feet) / denominator, -1.0, 1.0))
    return cosine < 0.0


def solve_joint_ik(
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
) -> JointIkResult:
    """Solve observed upper-limb swing in SMPL local coordinates.

    `prior_body=None` selects direct IK with previous accepted pose as prior.
    Passing an OG body pose selects the hybrid variant.  The prior supplies
    twist/unobserved rotations; root and observed arm swing always come from
    the current Body25 target.
    """
    device = target_body25.device
    target_np = target_body25[0].detach().cpu().numpy()
    base = previous_body if prior_body is None else prior_body
    base_body_np = base.detach().cpu().numpy().reshape(23, 3).astype(np.float32).copy()
    previous_np = previous_body.detach().cpu().numpy().reshape(23, 3).astype(np.float32)

    # Occluded lower body remains anchored to the last accepted state.
    base_body_np[list(LOWER_BODY_POSE)] = previous_np[list(LOWER_BODY_POSE)]
    for index in SPINE_POSE:
        base_body_np[index] = _clamp_rotvec(base_body_np[index], 35.0)
    for index in COLLAR_POSE:
        base_body_np[index] = _clamp_rotvec(base_body_np[index], 45.0)
    base_body_np[list(FORWARD_LOCK)] = 0.0

    with torch.no_grad():
        rest = _rest_joints(smpl_layer, fixed_betas)
        betas = fixed_betas.reshape(1, 10)
        root_candidates, _ = build_root_candidates(target_np)
        previous_root_np = previous_root.detach().cpu().numpy().reshape(3).astype(np.float32)
        roots = np.concatenate((root_candidates.reshape(-1, 3), previous_root_np[None]), axis=0)
        previous_rotation = Rotation.from_rotvec(previous_root_np)
        evaluated = []

        def evaluate(root_np: np.ndarray, body_np: np.ndarray, label: str) -> None:
            """Evaluate one complete SMPL pose without mixing score units."""
            root_value = torch.tensor(root_np[None], dtype=torch.float32, device=device)
            body_value = torch.tensor(body_np[None], dtype=torch.float32, device=device)
            output_value = smpl_layer(
                betas=betas, global_orient=root_value.unsqueeze(1), body_pose=body_value)
            unaligned = torch.einsum(
                "bvc,jv->bjc", output_value.vertices, body25_regressor)
            translation_value = target_body25[:, 8] - unaligned[:, 8]
            body25_value = unaligned + translation_value[:, None]
            smpl24_value = output_value.joints[:, :24] + translation_value[:, None]
            residual = torch.linalg.norm(
                body25_value[0, list((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12))]
                - target_body25[0, list((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12))],
                dim=-1,
            ).mean().item()
            root_delta = (previous_rotation.inv() * Rotation.from_rotvec(root_np)).magnitude()
            score = residual + 0.005 * float(root_delta)
            evaluated.append((
                _facing_mismatch(target_np, smpl24_value[0].cpu().numpy()),
                score, label, root_value, body_value, translation_value,
                body25_value, smpl24_value, output_value,
            ))

        # Keep the last credible pose as a candidate when noisy or occluded
        # observations would make an analytical correction worse.
        evaluate(previous_root_np, base_body_np.copy(), "prior_hold")

        # In the hybrid variant the neural root is not accepted blindly.  It is
        # one additional 180-degree ambiguity hypothesis and must still win the
        # same facing/residual/temporal comparison as analytical candidates.
        if prior_root is not None:
            prior_root_np = prior_root.detach().cpu().numpy().reshape(3).astype(np.float32)
            evaluate(prior_root_np, base_body_np.copy(), "og_prior")

        for candidate_index, root_np in enumerate(roots):
            body_np = base_body_np.copy()
            # Minimal global swing corrections preserve the prior's roll around
            # each observed bone while forcing its direction to match the joints.
            for joint, child, target_start, target_end in ARM_CHAINS:
                joints_np, global_rotations = _forward_kinematics(
                    rest, smpl_layer.parents, root_np, body_np, device)
                current_vector = joints_np[child] - joints_np[joint]
                target_vector = target_np[target_end] - target_np[target_start]
                delta = _alignment(current_vector, target_vector)
                desired_global = delta.as_matrix() @ global_rotations[joint]
                parent = int(smpl_layer.parents[joint])
                desired_local = global_rotations[parent].T @ desired_global
                body_np[joint - 1] = Rotation.from_matrix(desired_local).as_rotvec().astype(np.float32)
            body_np[list(FORWARD_LOCK)] = 0.0
            evaluate(root_np, body_np, f"corrected_root_{candidate_index}")

        # Prefer a geometrically consistent facing direction, then minimize
        # fitting residual and temporal root change within that valid set.
        facing_valid = [candidate for candidate in evaluated if not candidate[0]]
        pool = facing_valid if facing_valid else evaluated
        (_, _, _, root, body, translation, pred_body25,
         pred_smpl24, output) = min(pool, key=lambda item: item[1])
        pred_vertices = output.vertices + translation[:, None]

    return JointIkResult(
        root_orient=root,
        body_pose=body,
        translation=translation,
        pred_body25=pred_body25,
        pred_smpl24=pred_smpl24,
        pred_vertices=pred_vertices,
    )
