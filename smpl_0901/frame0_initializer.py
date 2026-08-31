"""Reusable Frame 0 seeds and batched SMPL fitting primitives.

This module contains the reusable 07/21 implementation. Method labels in the
experiment runner distinguish archived-style baselines from new candidates;
the archived 07/07 scripts themselves remain unchanged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import torch
from scipy.spatial.transform import Rotation


@dataclass(frozen=True)
class BatchedFitResult:
    root_orient: torch.Tensor
    body_pose: torch.Tensor
    translation: torch.Tensor
    pred_body25: torch.Tensor
    elapsed_seconds: float
    iterations: int


def analytical_root_seed(target_body25: np.ndarray) -> np.ndarray:
    """Estimate root orientation from shoulders and hips.

    Accepts either ``(25, 3)`` or ``(N, 25, 3)`` and returns axis-angle roots.
    """

    joints = np.asarray(target_body25, dtype=np.float32)
    single = joints.ndim == 2
    if single:
        joints = joints[None]
    if joints.ndim != 3 or joints.shape[1] < 13 or joints.shape[2] != 3:
        raise ValueError(f"Expected (N, >=13, 3), got {joints.shape}")

    roots = []
    for frame in joints:
        right_shoulder, left_shoulder = frame[2], frame[5]
        right_hip, left_hip = frame[9], frame[12]
        mid_shoulder = (right_shoulder + left_shoulder) * 0.5
        mid_hip = (right_hip + left_hip) * 0.5

        y_axis = mid_shoulder - mid_hip
        x_axis = left_hip - right_hip
        y_norm = np.linalg.norm(y_axis)
        x_norm = np.linalg.norm(x_axis)
        if y_norm < 1e-8 or x_norm < 1e-8:
            roots.append(np.zeros(3, dtype=np.float32))
            continue
        y_axis /= y_norm
        x_axis /= x_norm
        z_axis = np.cross(x_axis, y_axis)
        z_norm = np.linalg.norm(z_axis)
        if z_norm < 1e-8:
            roots.append(np.zeros(3, dtype=np.float32))
            continue
        z_axis /= z_norm
        x_axis = np.cross(y_axis, z_axis)
        x_axis /= max(np.linalg.norm(x_axis), 1e-8)
        rotation = np.stack((x_axis, y_axis, z_axis), axis=1)
        roots.append(Rotation.from_matrix(rotation).as_rotvec().astype(np.float32))

    result = np.stack(roots)
    return result[0] if single else result


def build_root_candidates(target_body25: np.ndarray) -> tuple[np.ndarray, tuple[str, ...]]:
    """Create analytical, world/local 180-yaw, and neutral root seeds."""

    analytical = np.asarray(analytical_root_seed(target_body25), dtype=np.float32)
    if analytical.ndim == 1:
        analytical = analytical[None]
    front_matrix = Rotation.from_rotvec(analytical).as_matrix()
    flip_y = Rotation.from_euler("y", 180.0, degrees=True).as_matrix()
    world_flip = np.einsum("ij,njk->nik", flip_y, front_matrix)
    local_flip = np.einsum("nij,jk->nik", front_matrix, flip_y)

    roots = np.stack(
        (
            analytical,
            Rotation.from_matrix(world_flip).as_rotvec().astype(np.float32),
            Rotation.from_matrix(local_flip).as_rotvec().astype(np.float32),
            np.zeros_like(analytical),
        ),
        axis=1,
    )
    return roots, ("analytical", "world_yaw_180", "local_yaw_180", "neutral")


def fit_smpl_batch(
    smpl_layer,
    body25_regressor: torch.Tensor,
    target_body25: torch.Tensor,
    init_root: torch.Tensor,
    *,
    iterations: int,
    learning_rate: float = 0.02,
    joint_indices=tuple(range(15)),
    init_body: torch.Tensor | None = None,
    init_translation: torch.Tensor | None = None,
    pose_prior_weight: float = 0.001,
) -> BatchedFitResult:
    """Fit independent observations in one GPU batch with fixed zero betas."""

    if iterations < 0:
        raise ValueError("iterations must be non-negative")
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
    betas = torch.zeros((batch_size, 10), device=device)
    optimizer = torch.optim.Adam((root, body, translation), lr=learning_rate)
    selected = list(joint_indices)

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
        pred = torch.einsum("bvc,jv->bjc", smpl.vertices, body25_regressor)
        pred = pred + translation.unsqueeze(1)
        residual = pred[:, selected] - target_body25[:, selected]
        per_item_joint_loss = residual.square().sum(dim=-1).mean(dim=-1)
        per_item_prior = body.square().mean(dim=-1)
        loss = (per_item_joint_loss + pose_prior_weight * per_item_prior).mean()
        loss.backward()
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
        pred = torch.einsum("bvc,jv->bjc", smpl.vertices, body25_regressor)
        pred = pred + translation.unsqueeze(1)

    return BatchedFitResult(
        root_orient=root.detach(),
        body_pose=body.detach(),
        translation=translation.detach(),
        pred_body25=pred.detach(),
        elapsed_seconds=elapsed,
        iterations=iterations,
    )
