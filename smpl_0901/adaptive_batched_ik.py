"""Hybrid v5 building blocks: cached static SMPL data and two-level arm IK.

This production module reuses the validated v2 rotation math while removing
repeated work that is invariant for fixed betas.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from scipy.spatial.transform import Rotation


@dataclass(frozen=True)
class StaticIkCache:
    rest: torch.Tensor
    rest_np: np.ndarray
    neutral_body25: np.ndarray


def build_static_cache(v2, smpl_layer, body25_regressor: torch.Tensor,
                       fixed_betas: torch.Tensor) -> StaticIkCache:
    """Precompute values that only depend on locked shape betas."""
    device = fixed_betas.device
    with torch.no_grad():
        rest = v2._rest_joints(smpl_layer, fixed_betas)
        neutral = smpl_layer(
            betas=fixed_betas.reshape(1, 10),
            global_orient=torch.zeros((1, 1, 3), device=device),
            body_pose=torch.zeros((1, 23, 3), device=device),
        )
        neutral_body25 = torch.einsum(
            "bvc,jv->bjc", neutral.vertices, body25_regressor)[0]
    return StaticIkCache(
        rest=rest,
        rest_np=rest[0].detach().cpu().numpy(),
        neutral_body25=neutral_body25.detach().cpu().numpy(),
    )


def _solve_arm_levels(v2, cache: StaticIkCache, smpl_layer,
                      root_np: np.ndarray, body_np: np.ndarray, target_np: np.ndarray,
                      device) -> None:
    """Solve independent left/right joints together at each kinematic depth."""
    # Shoulders do not depend on each other; neither do elbows.  Recomputing FK
    # once after both shoulders is therefore equivalent to the old sequence of
    # four FK calls, but requires only two calls per root hypothesis.
    levels = (v2.ARM_CHAINS[:2], v2.ARM_CHAINS[2:])
    for chains in levels:
        _, global_rotations = v2._forward_kinematics(
            cache.rest, smpl_layer.parents, root_np, body_np, device)
        for joint, child, target_start, target_end, twist_limit in chains:
            parent = int(smpl_layer.parents[joint])
            parent_global = global_rotations[parent]
            rest_vector = cache.rest_np[child] - cache.rest_np[joint]
            target_vector = target_np[target_end] - target_np[target_start]
            swing = v2._alignment(parent_global @ rest_vector, target_vector)
            prior_twist = v2._twist(
                Rotation.from_rotvec(body_np[joint - 1]), rest_vector, twist_limit)
            desired_global = swing.as_matrix() @ parent_global @ prior_twist.as_matrix()
            desired_local = parent_global.T @ desired_global
            body_np[joint - 1] = Rotation.from_matrix(
                desired_local).as_rotvec().astype(np.float32)


def solve_joint_ik_v5(
    v2,
    cache: StaticIkCache,
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
):
    """Numerically equivalent v2 candidate search with cached invariant data."""
    del previous_translation
    device = target_body25.device
    target_np = target_body25[0].detach().cpu().numpy()
    base = previous_body if prior_body is None else prior_body
    base_body_np = base.detach().cpu().numpy().reshape(23, 3).astype(np.float32).copy()
    previous_body_np = previous_body.detach().cpu().numpy().reshape(23, 3).astype(np.float32)
    previous_root_np = previous_root.detach().cpu().numpy().reshape(3).astype(np.float32)

    base_body_np[list(v2.LOWER_BODY_POSE)] = previous_body_np[list(v2.LOWER_BODY_POSE)]
    v2._distribute_spine(base_body_np)
    for index in v2.COLLAR_POSE:
        base_body_np[index] = v2._clamp_rotvec(base_body_np[index], 35.0)
    base_body_np[list(v2.FORWARD_LOCK)] = 0.0

    with torch.no_grad():
        betas = fixed_betas.reshape(1, 10)
        standard_roots, _ = v2.build_root_candidates(target_np)
        root_options = [("analytical", standard_roots.reshape(-1, 3)[0])]
        root_options.extend((
            ("torso_nose_kabsch", v2._kabsch_root(cache.neutral_body25, target_np)),
            ("previous", previous_root_np),
        ))
        if prior_root is not None:
            root_options.append((
                "og_prior", prior_root.detach().cpu().numpy().reshape(3).astype(np.float32)))

        previous_rotation = Rotation.from_rotvec(previous_root_np)
        pose_candidates = []
        for label, root_np in root_options:
            body_np = base_body_np.copy()
            _solve_arm_levels(
                v2, cache, smpl_layer, root_np, body_np, target_np, device)
            body_np[list(v2.FORWARD_LOCK)] = 0.0
            root_value = torch.tensor(root_np[None], dtype=torch.float32, device=device)
            body_value = torch.tensor(body_np[None], dtype=torch.float32, device=device)
            root_delta = float(
                (previous_rotation.inv() * Rotation.from_rotvec(root_np)).magnitude())
            pose_candidates.append((label, root_value, body_value, root_delta))

        # All hypotheses have the same shape and betas.  One batched LBS call
        # avoids three or four independent Python/CUDA launch sequences.
        roots_batch = torch.cat([item[1] for item in pose_candidates], dim=0)
        bodies_batch = torch.cat([item[2] for item in pose_candidates], dim=0)
        count = len(pose_candidates)
        output = smpl_layer(
            betas=betas.expand(count, -1),
            global_orient=roots_batch.unsqueeze(1), body_pose=bodies_batch)
        unaligned = torch.einsum("bvc,jv->bjc", output.vertices, body25_regressor)
        target_batch = target_body25.expand(count, -1, -1)
        translations = target_batch[:, 8] - unaligned[:, 8]
        body25_batch = unaligned + translations[:, None]
        smpl24_batch = output.joints[:, :24] + translations[:, None]
        residuals = torch.linalg.norm(
            body25_batch[:, list(v2.UPPER11)]
            - target_batch[:, list(v2.UPPER11)], dim=-1
        ).mean(dim=-1).cpu().numpy()
        smpl24_np = smpl24_batch.cpu().numpy()

        evaluated = []
        diagnostics = []
        for index, (label, root_value, body_value, root_delta) in enumerate(pose_candidates):
            residual = float(residuals[index])
            facing = v2._facing_angle(target_np, smpl24_np[index], facing_sign)
            score = residual + 0.005 * root_delta + 0.02 * min(facing / 90.0, 2.0)
            evaluated.append((score, root_delta, label, root_value, body_value,
                              translations[index:index + 1],
                              body25_batch[index:index + 1],
                              smpl24_batch[index:index + 1],
                              output.vertices[index:index + 1]))
            diagnostics.append((label, float(residual * 1000.0), facing))

        facing_valid = [item for item in evaluated if v2._facing_angle(
            target_np, item[7][0].cpu().numpy(), facing_sign) <= 90.0]
        facing_pool = facing_valid if facing_valid else evaluated
        temporal_valid = [item for item in facing_pool if item[1] <= np.pi / 2.0]
        pool = temporal_valid if temporal_valid else facing_pool
        (_, _, selected, root, body, translation, pred_body25,
        pred_smpl24, selected_vertices) = min(pool, key=lambda item: item[0])
        vertices = selected_vertices + translation[:, None]

    return v2.JointIkV2Result(
        root_orient=root,
        body_pose=body,
        translation=translation,
        pred_body25=pred_body25,
        pred_smpl24=pred_smpl24,
        pred_vertices=vertices,
        selected_root=selected,
        candidate_scores=tuple(diagnostics),
    )
