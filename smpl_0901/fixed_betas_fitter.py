"""Fixed Betas + Kinematically Constrained Soft Target Fitting.

This module implements Direction 3 of the 0818 meeting roadmap:
1. Estimate or calibrate a subject's 10-D SMPL shape (`betas`) from initial
   reliable frames and lock/freeze `betas` permanently.
2. Optimize per-frame 66-D rotations (`pose[0:66]`) with:
   - Fixed bone length constraints (via frozen `betas`).
   - Weighted Soft Joint Target loss (prioritizing endpoint accuracy on wrists and ankles).
   - Torso normal / orientation constraint (preventing front/back flips).
   - Pose prior and temporal smoothness regularization.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import torch
import torch.nn as nn
from scipy.spatial.transform import Rotation


@dataclass(frozen=True)
class FixedBetasFitResult:
    root_orient: torch.Tensor       # (B, 3)
    body_pose: torch.Tensor         # (B, 69) or (B, 23, 3)
    translation: torch.Tensor       # (B, 3)
    pred_body25: torch.Tensor       # (B, 25, 3)
    pred_smpl24: torch.Tensor       # (B, 24, 3), native SMPL kinematic joints
    fixed_betas: torch.Tensor       # (10,) or (B, 10)
    residual_mm: torch.Tensor       # (B,) selected weighted MPJPE in mm
    torso_orientation_deg: torch.Tensor # (B,) torso error in deg
    elapsed_seconds: float
    iterations: int


def compute_torso_normal(joints_3d: torch.Tensor) -> torch.Tensor:
    """Compute normalized torso normal vector from 3D joints.

    Normal = normalize((left_shoulder - right_shoulder) x (neck/mid_shoulder - mid_hip)).
    Assumes standard Body25 indexing: R_Shoulder=2, L_Shoulder=5, MidHip/Pelvis=8 or (9,12)/2.
    """
    # joints_3d: (B, >=13, 3)
    r_shoulder = joints_3d[:, 2]
    l_shoulder = joints_3d[:, 5]
    if joints_3d.shape[1] > 8:
        mid_hip = joints_3d[:, 8]
    else:
        mid_hip = (joints_3d[:, 9] + joints_3d[:, 12]) * 0.5
    mid_shoulder = (r_shoulder + l_shoulder) * 0.5

    x_axis = l_shoulder - r_shoulder
    y_axis = mid_shoulder - mid_hip

    x_norm = torch.linalg.norm(x_axis, dim=-1, keepdim=True).clamp(min=1e-8)
    y_norm = torch.linalg.norm(y_axis, dim=-1, keepdim=True).clamp(min=1e-8)
    x_axis = x_axis / x_norm
    y_axis = y_axis / y_norm

    z_axis = torch.cross(x_axis, y_axis, dim=-1)
    z_norm = torch.linalg.norm(z_axis, dim=-1, keepdim=True).clamp(min=1e-8)
    return z_axis / z_norm


def estimate_fixed_betas(
    smpl_layer: nn.Module,
    body25_regressor: torch.Tensor,
    calibration_body25: torch.Tensor,
    init_root: torch.Tensor | None = None,
    *,
    iterations: int = 150,
    learning_rate: float = 0.03,
    joint_indices: Sequence[int] = tuple(range(15)),
    pose_prior_weight: float = 0.001,
    beta_prior_weight: float = 0.001,
    beta_limit: float = 3.0,
) -> torch.Tensor:
    """Estimate a single shared 10-D beta vector across calibration frames.

    Args:
        smpl_layer: SMPL model layer.
        body25_regressor: (25, V) vertex-to-joint regressor tensor.
        calibration_body25: (N, 25, 3) tensor of reliable calibration keypoints.
        init_root: (N, 3) initial root orientations. If None, uses analytical seed.
    Returns:
        fixed_betas: (10,) tensor of estimated subject body shape.
    """
    device = calibration_body25.device
    num_frames = calibration_body25.shape[0]
    if num_frames == 0:
        return torch.zeros(10, device=device)

    if init_root is None:
        from .frame0_initializer import analytical_root_seed
        root_np = analytical_root_seed(calibration_body25.detach().cpu().numpy())
        root = torch.tensor(root_np, dtype=torch.float32, device=device).requires_grad_(True)
    else:
        root = init_root.clone().detach().to(device).requires_grad_(True)

    body = torch.zeros((num_frames, 23 * 3), device=device, requires_grad=True)
    translation = torch.zeros((num_frames, 3), device=device, requires_grad=True)
    # A single shared beta vector across all calibration frames
    shared_betas = torch.zeros((1, 10), device=device, requires_grad=True)

    optimizer = torch.optim.Adam(
        [
            {"params": [shared_betas], "lr": learning_rate * 1.5},
            {"params": [root, body, translation], "lr": learning_rate},
        ]
    )
    selected = list(joint_indices)

    for _ in range(iterations):
        optimizer.zero_grad()
        betas_expanded = shared_betas.expand(num_frames, 10)
        smpl = smpl_layer(
            betas=betas_expanded,
            global_orient=root.unsqueeze(1),
            body_pose=body.view(num_frames, 23, 3),
        )
        pred = torch.einsum("bvc,jv->bjc", smpl.vertices, body25_regressor) + translation.unsqueeze(1)
        residual = pred[:, selected] - calibration_body25[:, selected]
        joint_loss = residual.square().sum(dim=-1).mean()
        pose_prior = body.square().mean()
        beta_prior = shared_betas.square().mean()
        loss = joint_loss + pose_prior_weight * pose_prior + beta_prior_weight * beta_prior
        loss.backward()
        optimizer.step()
        # Extreme shape coefficients usually mean that noisy/occluded joints
        # are being absorbed as body shape. Keep calibration in a useful range.
        if beta_limit > 0:
            with torch.no_grad():
                shared_betas.clamp_(-beta_limit, beta_limit)

    return shared_betas.squeeze(0).detach()


def fit_fixed_betas_soft_target(
    smpl_layer: nn.Module,
    body25_regressor: torch.Tensor,
    target_body25: torch.Tensor,
    fixed_betas: torch.Tensor,
    init_root: torch.Tensor,
    *,
    init_body: torch.Tensor | None = None,
    init_translation: torch.Tensor | None = None,
    iterations: int = 100,
    learning_rate: float = 0.02,
    joint_indices: Sequence[int] = tuple(range(15)),
    endpoint_weight: float = 0.5,
    torso_normal_weight: float = 0.02,
    pose_prior_weight: float = 0.001,
    temporal_smooth_weight: float = 0.01,
    prev_body_pose: torch.Tensor | None = None,
    use_huber: bool = False,
    huber_delta: float = 0.05,
    joint_weights: torch.Tensor | None = None,
    frozen_pose_indices: Sequence[int] = (),
) -> FixedBetasFitResult:
    """Fit per-frame rotations with frozen betas and soft endpoint / torso constraints.

    Args:
        smpl_layer: SMPL model layer.
        body25_regressor: (25, V) vertex-to-joint regressor tensor.
        target_body25: (B, 25, 3) observation keypoints.
        fixed_betas: (10,) or (B, 10) frozen shape coefficients.
        init_root: (B, 3) initial root orientations.
    """
    device = target_body25.device
    batch_size = target_body25.shape[0]

    root = init_root.clone().detach().to(device).requires_grad_(True)
    if init_body is None:
        body = torch.zeros((batch_size, 23 * 3), device=device, requires_grad=True)
    else:
        body = init_body.clone().detach().to(device).requires_grad_(True)
    if init_translation is None:
        translation = torch.zeros((batch_size, 3), device=device, requires_grad=True)
    else:
        translation = init_translation.clone().detach().to(device).requires_grad_(True)

    if fixed_betas.ndim == 1:
        betas = fixed_betas.unsqueeze(0).expand(batch_size, 10).to(device).detach()
    else:
        betas = fixed_betas.to(device).detach()

    optimizer = torch.optim.Adam((root, body, translation), lr=learning_rate)
    selected = list(joint_indices)
    if joint_weights is None:
        selected_weights = torch.ones(
            (batch_size, len(selected)), dtype=target_body25.dtype, device=device
        )
    else:
        weights = joint_weights.to(device=device, dtype=target_body25.dtype)
        if weights.ndim == 1:
            weights = weights.unsqueeze(0).expand(batch_size, -1)
        if tuple(weights.shape) != (batch_size, target_body25.shape[1]):
            raise ValueError(
                "joint_weights must have shape (B, J) or (J,), got "
                f"{tuple(weights.shape)}"
            )
        selected_weights = weights[:, selected].clamp(0.0, 1.0)
    weight_denominator = selected_weights.sum().clamp(min=1.0)

    # Endpoint indices (in Body25: 4=R_Wrist, 7=L_Wrist, 11=R_Ankle, 14=L_Ankle)
    endpoints = [j for j in (4, 7, 11, 14) if j in selected]
    endpoint_positions = [selected.index(j) for j in endpoints]

    target_torso_normal = compute_torso_normal(target_body25).detach()

    if device.type == "cuda":
        torch.cuda.synchronize(device)
    start = time.perf_counter()

    for _ in range(iterations):
        optimizer.zero_grad()
        smpl = smpl_layer(
            betas=betas,
            global_orient=root.unsqueeze(1),
            body_pose=body.view(batch_size, 23, 3),
        )
        pred = torch.einsum("bvc,jv->bjc", smpl.vertices, body25_regressor) + translation.unsqueeze(1)

        diff = pred[:, selected] - target_body25[:, selected]
        if use_huber:
            dist = torch.linalg.norm(diff, dim=-1)
            per_joint_loss = torch.where(
                dist < huber_delta,
                0.5 * dist.square(),
                huber_delta * (dist - 0.5 * huber_delta),
            )
        else:
            per_joint_loss = diff.square().sum(dim=-1)
        joint_loss = (per_joint_loss * selected_weights).sum() / weight_denominator

        # Weighted endpoint loss (wrists and ankles)
        if endpoints and endpoint_weight > 0:
            end_diff = pred[:, endpoints] - target_body25[:, endpoints]
            endpoint_weights = selected_weights[:, endpoint_positions]
            endpoint_loss = (
                end_diff.square().sum(dim=-1) * endpoint_weights
            ).sum() / endpoint_weights.sum().clamp(min=1.0)
        else:
            endpoint_loss = torch.tensor(0.0, device=device)

        # Torso normal orientation loss
        if torso_normal_weight > 0:
            pred_torso_normal = compute_torso_normal(pred)
            torso_loss = (1.0 - (pred_torso_normal * target_torso_normal).sum(dim=-1)).mean()
        else:
            torso_loss = torch.tensor(0.0, device=device)

        # Pose prior
        prior_loss = body.square().mean()

        # Temporal smoothness loss
        if prev_body_pose is not None and temporal_smooth_weight > 0:
            prev = prev_body_pose.to(device).detach()
            temporal_loss = (body - prev).square().mean()
        else:
            temporal_loss = torch.tensor(0.0, device=device)

        loss = (
            joint_loss
            + endpoint_weight * endpoint_loss
            + torso_normal_weight * torso_loss
            + pose_prior_weight * prior_loss
            + temporal_smooth_weight * temporal_loss
        )
        loss.backward()
        if frozen_pose_indices and body.grad is not None:
            for pose_index in frozen_pose_indices:
                start = int(pose_index) * 3
                body.grad[:, start:start + 3] = 0.0
        optimizer.step()

    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - start

    with torch.no_grad():
        smpl = smpl_layer(
            betas=betas,
            global_orient=root.unsqueeze(1),
            body_pose=body.view(batch_size, 23, 3),
        )
        pred = torch.einsum("bvc,jv->bjc", smpl.vertices, body25_regressor) + translation.unsqueeze(1)
        pred_smpl24 = smpl.joints[:, :24] + translation.unsqueeze(1)
        pred_torso_normal = compute_torso_normal(pred)

        # Weighted MPJPE for the active fit profile (mm)
        diff_mm = torch.linalg.norm(
            pred[:, selected] - target_body25[:, selected], dim=-1
        ) * 1000.0
        residual_mm = (diff_mm * selected_weights).sum(dim=-1) / (
            selected_weights.sum(dim=-1).clamp(min=1.0)
        )

        # Torso orientation error in degrees
        cos_sim = (pred_torso_normal * target_torso_normal).sum(dim=-1).clamp(-1.0, 1.0)
        torso_deg = torch.acos(cos_sim) * (180.0 / np.pi)

    return FixedBetasFitResult(
        root_orient=root.detach(),
        body_pose=body.detach(),
        translation=translation.detach(),
        pred_body25=pred.detach(),
        pred_smpl24=pred_smpl24.detach(),
        fixed_betas=betas.detach(),
        residual_mm=residual_mm.detach(),
        torso_orientation_deg=torso_deg.detach(),
        elapsed_seconds=elapsed,
        iterations=iterations,
    )
