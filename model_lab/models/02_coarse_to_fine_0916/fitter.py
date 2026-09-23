"""Joints-first coarse fitting followed by a short exact SMPL refinement."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Sequence

import torch
from smplx.lbs import batch_rigid_transform, batch_rodrigues, blend_shapes, vertices2joints

from smpl_0901.fixed_betas_fitter import (
    FixedBetasFitResult,
    compute_torso_normal,
    fit_fixed_betas_soft_target,
    zero_pose_components_,
)


LOWER_BODY_POSE = (0, 1, 3, 4, 6, 7, 9, 10)
SPINE_POSE = (2, 5, 8)
FORWARD_LOCK = (11, 14, 19, 20)
UPPER11 = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12)


@dataclass
class CoarseToFineResult:
    fit: FixedBetasFitResult
    coarse_iterations_used: int
    coarse_elapsed_seconds: float
    fine_iterations: int


class FixedShapeKinematicBody25:
    """Differentiable Body25 approximation without constructing posed vertices."""

    def __init__(self, smpl_layer, body25_regressor: torch.Tensor, fixed_betas: torch.Tensor):
        device = fixed_betas.device
        betas = fixed_betas.reshape(1, 10)
        with torch.no_grad():
            shaped = smpl_layer.v_template.unsqueeze(0) + blend_shapes(betas, smpl_layer.shapedirs)
            self.rest_joints = vertices2joints(smpl_layer.J_regressor, shaped).detach()
            zero_root = torch.zeros((1, 1, 3), dtype=betas.dtype, device=device)
            zero_body = torch.zeros((1, 23, 3), dtype=betas.dtype, device=device)
            rest_output = smpl_layer(betas=betas, global_orient=zero_root, body_pose=zero_body)
            rest_body25 = torch.einsum("bvc,jv->bjc", rest_output.vertices, body25_regressor)
            self.nose_head_offset = (rest_body25[:, 0] - self.rest_joints[:, 15]).detach()
        self.parents = smpl_layer.parents.detach()

    def __call__(self, root: torch.Tensor, body: torch.Tensor, translation: torch.Tensor):
        batch = root.shape[0]
        full_pose = torch.cat((root.unsqueeze(1), body.view(batch, 23, 3)), dim=1)
        rotations = batch_rodrigues(full_pose.reshape(-1, 3)).view(batch, 24, 3, 3)
        rest = self.rest_joints.expand(batch, -1, -1)
        joints, transforms = batch_rigid_transform(rotations, rest, self.parents)
        pred = torch.zeros((batch, 25, 3), dtype=root.dtype, device=root.device)
        # Body25/OpenPose mapping from the SMPL24 kinematic tree.
        pred[:, 0] = joints[:, 15] + torch.einsum(
            "bij,bj->bi", transforms[:, 15, :3, :3], self.nose_head_offset.expand(batch, -1))
        pred[:, 1] = joints[:, 12]
        pred[:, 2] = joints[:, 17]
        pred[:, 3] = joints[:, 19]
        pred[:, 4] = joints[:, 21]
        pred[:, 5] = joints[:, 16]
        pred[:, 6] = joints[:, 18]
        pred[:, 7] = joints[:, 20]
        pred[:, 8] = joints[:, 0]
        pred[:, 9] = joints[:, 2]
        pred[:, 10] = joints[:, 5]
        pred[:, 11] = joints[:, 8]
        pred[:, 12] = joints[:, 1]
        pred[:, 13] = joints[:, 4]
        pred[:, 14] = joints[:, 7]
        pred[:, 15:19] = pred[:, 0:1]
        pred[:, 19:22] = joints[:, 10:11]
        pred[:, 22:25] = joints[:, 11:12]
        return pred + translation.unsqueeze(1), joints + translation.unsqueeze(1)


def fit_coarse_to_fine(
    smpl_layer,
    body25_regressor: torch.Tensor,
    target_body25: torch.Tensor,
    fixed_betas: torch.Tensor,
    init_root: torch.Tensor,
    *,
    init_body: torch.Tensor | None = None,
    init_translation: torch.Tensor | None = None,
    prev_body_pose: torch.Tensor | None = None,
    coarse_iterations: int = 35,
    fine_iterations: int = 8,
    learning_rate: float = 0.02,
    early_stop_residual_mm: float = 28.0,
    plateau_patience: int = 3,
    check_interval: int = 5,
    joint_indices: Sequence[int] = UPPER11,
) -> CoarseToFineResult:
    """Fit a lightweight kinematic skeleton, then correct it with exact Body25."""
    device = target_body25.device
    batch = target_body25.shape[0]
    fixed = fixed_betas.reshape(-1, 10)[0].to(device).detach()
    kinematic = FixedShapeKinematicBody25(smpl_layer, body25_regressor, fixed)
    root = init_root.reshape(batch, 3).clone().detach().requires_grad_(True)
    if init_body is None:
        body = torch.zeros((batch, 69), dtype=target_body25.dtype, device=device, requires_grad=True)
    else:
        body = init_body.reshape(batch, 69).clone().detach().requires_grad_(True)
    if init_translation is None:
        translation = torch.zeros((batch, 3), dtype=target_body25.dtype, device=device, requires_grad=True)
    else:
        translation = init_translation.reshape(batch, 3).clone().detach().requires_grad_(True)
    zero_pose_components_(body, FORWARD_LOCK)
    optimizer = torch.optim.Adam((root, body, translation), lr=learning_rate)
    selected = list(joint_indices)
    endpoints = [index for index in (4, 7) if index in selected]
    target_normal = compute_torso_normal(target_body25).detach()
    best = float("inf")
    stalled = 0
    used = 0
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    started = perf_counter()
    for iteration in range(coarse_iterations):
        optimizer.zero_grad(set_to_none=True)
        pred, smpl24 = kinematic(root, body, translation)
        diff = pred[:, selected] - target_body25[:, selected]
        joint_loss = diff.square().sum(dim=-1).mean()
        endpoint_loss = (
            (pred[:, endpoints] - target_body25[:, endpoints]).square().sum(dim=-1).mean()
            if endpoints else torch.zeros((), device=device)
        )
        pred_normal = compute_torso_normal(pred)
        torso_loss = (1.0 - (pred_normal * target_normal).sum(dim=-1)).mean()
        spine_loss = body.view(batch, 23, 3)[:, list(SPINE_POSE)].square().mean()
        temporal_loss = (
            (body - prev_body_pose.reshape(batch, 69).to(device).detach()).square().mean()
            if prev_body_pose is not None else torch.zeros((), device=device)
        )
        prior_loss = body.square().mean()
        loss = (
            joint_loss + 0.5 * endpoint_loss + 0.05 * torso_loss
            + 0.001 * prior_loss + 0.02 * spine_loss + 0.01 * temporal_loss
        )
        loss.backward()
        if body.grad is not None:
            for pose_index in LOWER_BODY_POSE:
                body.grad[:, pose_index * 3:pose_index * 3 + 3] = 0.0
        optimizer.step()
        zero_pose_components_(body, FORWARD_LOCK)
        used = iteration + 1
        if used % check_interval == 0 or used == coarse_iterations:
            with torch.no_grad():
                residual = torch.linalg.norm(
                    pred[:, selected] - target_body25[:, selected], dim=-1).mean() * 1000.0
                value = float(residual.item())
            if value <= early_stop_residual_mm:
                break
            if best - value < 0.5:
                stalled += 1
            else:
                stalled = 0
            best = min(best, value)
            if stalled >= plateau_patience:
                break
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    coarse_elapsed = perf_counter() - started

    exact = fit_fixed_betas_soft_target(
        smpl_layer,
        body25_regressor,
        target_body25,
        fixed,
        root.detach(),
        init_body=body.detach(),
        init_translation=translation.detach(),
        iterations=fine_iterations,
        learning_rate=learning_rate,
        joint_indices=joint_indices,
        endpoint_weight=0.5,
        torso_normal_weight=0.05,
        spine_stability_weight=0.02,
        spine_pose_indices=SPINE_POSE,
        body_facing_weight=0.01,
        temporal_smooth_weight=0.01,
        prev_body_pose=prev_body_pose,
        use_huber=False,
        frozen_pose_indices=LOWER_BODY_POSE,
        zero_pose_indices=FORWARD_LOCK,
    )
    return CoarseToFineResult(
        fit=exact,
        coarse_iterations_used=used,
        coarse_elapsed_seconds=coarse_elapsed,
        fine_iterations=fine_iterations,
    )
