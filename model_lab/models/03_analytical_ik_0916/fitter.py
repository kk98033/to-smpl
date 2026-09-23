"""Analytical upper-limb seed followed by short exact SMPL refinement."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
import torch
from scipy.spatial.transform import Rotation
from smplx.lbs import batch_rigid_transform, batch_rodrigues, blend_shapes, vertices2joints

from smpl_0901.fixed_betas_fitter import FixedBetasFitResult, fit_fixed_betas_soft_target
from smpl_0901.frame0_initializer import analytical_root_seed


UPPER11 = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12)
LOWER_BODY_POSE = (0, 1, 3, 4, 6, 7, 9, 10)
SPINE_POSE = (2, 5, 8)
FORWARD_LOCK = (11, 14, 19, 20)


@dataclass
class AnalyticalFitResult:
    fit: FixedBetasFitResult
    seed_elapsed_seconds: float
    fine_iterations: int


def _alignment(from_vector: np.ndarray, to_vector: np.ndarray) -> Rotation:
    source = np.asarray(from_vector, dtype=np.float64)
    target = np.asarray(to_vector, dtype=np.float64)
    source /= max(float(np.linalg.norm(source)), 1e-9)
    target /= max(float(np.linalg.norm(target)), 1e-9)
    cross = np.cross(source, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if sine < 1e-8:
        if cosine > 0:
            return Rotation.identity()
        helper = np.array([1.0, 0.0, 0.0])
        if abs(source[0]) > 0.8:
            helper = np.array([0.0, 1.0, 0.0])
        axis = np.cross(source, helper)
        axis /= np.linalg.norm(axis)
        return Rotation.from_rotvec(axis * np.pi)
    axis = cross / sine
    return Rotation.from_rotvec(axis * np.arctan2(sine, cosine))


def _forward_kinematics(rest_joints: torch.Tensor, parents: torch.Tensor,
                        root_np: np.ndarray, body_np: np.ndarray, device):
    pose = np.concatenate((root_np.reshape(1, 3), body_np.reshape(23, 3)), axis=0)
    pose_tensor = torch.tensor(pose, dtype=torch.float32, device=device)
    rotations = batch_rodrigues(pose_tensor).view(1, 24, 3, 3)
    joints, transforms = batch_rigid_transform(rotations, rest_joints, parents)
    return joints[0].detach().cpu().numpy(), transforms[0, :, :3, :3].detach().cpu().numpy()


def analytical_upper_body_seed(
    smpl_layer,
    target_body25: np.ndarray,
    fixed_betas: torch.Tensor,
    previous_body: torch.Tensor | None,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Construct root, shoulder and elbow rotations directly from Body25 vectors."""
    device = fixed_betas.device
    target = np.asarray(target_body25, dtype=np.float32)
    root_np = analytical_root_seed(target).astype(np.float32)
    if previous_body is None:
        body_np = np.zeros((23, 3), dtype=np.float32)
    else:
        body_np = previous_body.detach().cpu().numpy().reshape(23, 3).astype(np.float32).copy()
    body_np[list(FORWARD_LOCK)] = 0.0
    with torch.no_grad():
        beta = fixed_betas.reshape(1, 10)
        shaped = smpl_layer.v_template.unsqueeze(0) + blend_shapes(beta, smpl_layer.shapedirs)
        rest = vertices2joints(smpl_layer.J_regressor, shaped)

    # (SMPL joint, child joint, Body25 source, Body25 target)
    chains = (
        (16, 18, 5, 6),  # left shoulder -> left elbow
        (17, 19, 2, 3),  # right shoulder -> right elbow
        (18, 20, 6, 7),  # left elbow -> left wrist
        (19, 21, 3, 4),  # right elbow -> right wrist
    )
    for joint, child, target_start, target_end in chains:
        joints_np, global_rotations = _forward_kinematics(
            rest, smpl_layer.parents, root_np, body_np, device)
        current_vector = joints_np[child] - joints_np[joint]
        target_vector = target[target_end] - target[target_start]
        delta = _alignment(current_vector, target_vector)
        desired_global = delta.as_matrix() @ global_rotations[joint]
        parent = int(smpl_layer.parents[joint])
        local = global_rotations[parent].T @ desired_global
        body_np[joint - 1] = Rotation.from_matrix(local).as_rotvec().astype(np.float32)
    body_np[list(FORWARD_LOCK)] = 0.0
    return (
        torch.tensor(root_np[None], dtype=torch.float32, device=device),
        torch.tensor(body_np.reshape(1, 69), dtype=torch.float32, device=device),
    )


def fit_analytical_refined(
    smpl_layer,
    body25_regressor: torch.Tensor,
    target_body25: torch.Tensor,
    fixed_betas: torch.Tensor,
    *,
    previous_body: torch.Tensor | None = None,
    previous_translation: torch.Tensor | None = None,
    fine_iterations: int = 15,
) -> AnalyticalFitResult:
    started = perf_counter()
    root, body = analytical_upper_body_seed(
        smpl_layer, target_body25[0].detach().cpu().numpy(), fixed_betas, previous_body)
    if target_body25.device.type == "cuda":
        torch.cuda.synchronize(target_body25.device)
    seed_elapsed = perf_counter() - started
    result = fit_fixed_betas_soft_target(
        smpl_layer,
        body25_regressor,
        target_body25,
        fixed_betas,
        root,
        init_body=body,
        init_translation=previous_translation,
        iterations=fine_iterations,
        joint_indices=UPPER11,
        endpoint_weight=0.5,
        torso_normal_weight=0.05,
        spine_stability_weight=0.02,
        spine_pose_indices=SPINE_POSE,
        body_facing_weight=0.01,
        temporal_smooth_weight=0.01,
        prev_body_pose=previous_body,
        use_huber=False,
        frozen_pose_indices=LOWER_BODY_POSE,
        zero_pose_indices=FORWARD_LOCK,
    )
    return AnalyticalFitResult(
        fit=result,
        seed_elapsed_seconds=seed_elapsed,
        fine_iterations=fine_iterations,
    )
