"""Production orchestration for the validated v5 adaptive-fast SMPL tracker."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from . import adaptive_batched_ik as v5
from . import adaptive_gate as gate_ops
from . import adaptive_ik as ik
from .fixed_betas_fitter import (
    FixedBetasFitResult,
    compute_torso_normal,
    fit_fixed_betas_soft_target,
)


@dataclass(frozen=True)
class AdaptiveMetadata:
    selected_root: str
    neural_prior_used: bool
    motion_coherence: float
    motion_speed_mps: float
    refinement_steps: int
    region_updates: dict[str, bool]
    region_reasons: dict[str, tuple[str, ...]]
    region_residual_mm: dict[str, float]
    region_confidence: dict[str, float]


def motion_coherence(history: list[tuple[int, np.ndarray]], indices=ik.UPPER11):
    if len(history) < 2:
        return 0.0, 0.0
    recent = history[-5:]
    points = np.stack([item[1] for item in recent]).astype(np.float64)
    points -= points[:, [8]]
    points = points[:, list(indices)]
    distance = np.linalg.norm(np.diff(points, axis=0), axis=2)
    path = distance.sum(axis=0)
    net = np.linalg.norm(points[-1] - points[0], axis=1)
    coherence = float(np.mean(net / (path + 1e-8)))
    seconds = max((recent[-1][0] - recent[0][0]) * 1e-9, 1e-3)
    return coherence, float(np.mean(path) / seconds)


class AdaptiveFastTracker:
    """Causal v5 tracker; state advances only through the regional gate."""

    def __init__(self, smpl_layer, regressor, fixed_betas, neural_prior, *,
                 og_stride: int = 4, coherence_threshold: float = 0.55,
                 speed_threshold: float = 0.3,
                 medium_steps: int = 1, high_steps: int = 2):
        self.smpl_layer = smpl_layer
        self.regressor = regressor
        self.fixed_betas = fixed_betas
        self.prior = neural_prior
        self.og_stride = max(int(og_stride), 1)
        self.coherence_threshold = float(coherence_threshold)
        self.speed_threshold = float(speed_threshold)
        self.medium_steps = max(int(medium_steps), 0)
        self.high_steps = max(int(high_steps), self.medium_steps)
        self.cache = v5.build_static_cache(
            ik, smpl_layer, regressor, fixed_betas.reshape(1, 10)
        )
        self.quality = None
        self.history: list[tuple[int, np.ndarray]] = []
        self.frame_index = 0
        self.facing_sign = 1.0

    def initialize(self, target_np, timestamp_ns, root, body, translation, pred_smpl24):
        self.quality = gate_ops.GeometryQualityEstimator(target_np, 30.0)
        self.history = [(int(timestamp_ns), np.asarray(target_np, np.float32).copy())]
        facing = ik._facing_angle(target_np, pred_smpl24, 1.0)
        self.facing_sign = 1.0 if facing <= 90.0 else -1.0
        self.frame_index = 1

    def step(self, target_np, confidence, timestamp_ns, previous_root,
             previous_body, previous_translation, previous_prediction):
        import torch
        from .service import pose_rotation_diagnostics

        if self.quality is None:
            raise RuntimeError("adaptive tracker must be initialized from a quality seed")
        self.history.append((int(timestamp_ns), np.asarray(target_np, np.float32).copy()))
        self.history = self.history[-5:]
        coherence, speed = motion_coherence(self.history)
        coherent = (
            coherence >= self.coherence_threshold and speed >= self.speed_threshold
        )

        # Geometry remains the primary confidence source. Upstream confidence,
        # when present, can only reduce trust and is never required.
        delta_ns = self.history[-1][0] - self.history[-2][0]
        effective_fps = float(np.clip(1e9 / max(delta_ns, 1), 1.0, 120.0))
        weights_np = self.quality.update(target_np, source_fps=effective_fps)
        weights_np *= np.asarray(confidence, dtype=np.float32)
        weights_np[8] = 1.0
        safe_target_np = gate_ops.stabilized_target(
            target_np, previous_prediction, weights_np
        )
        target = torch.tensor(
            safe_target_np[None], dtype=torch.float32, device=previous_root.device
        )
        weights = torch.tensor(
            weights_np[None], dtype=torch.float32, device=previous_root.device
        )

        torch.cuda.synchronize(previous_root.device)
        started = time.perf_counter()
        use_prior = coherent or self.frame_index % self.og_stride == 0
        if use_prior:
            prior_root, prior_body = self.prior.predict(
                target, self.fixed_betas, previous_root, previous_body
            )
        else:
            prior_root = previous_root.reshape(1, 3)
            prior_body = previous_body.reshape(1, 23, 3)
        candidate = v5.solve_joint_ik_v5(
            ik, self.cache, self.smpl_layer, self.regressor, target,
            self.fixed_betas.reshape(1, 10), previous_root, previous_body,
            previous_translation, prior_root=prior_root, prior_body=prior_body,
            facing_sign=self.facing_sign,
        )
        candidate_np = candidate.pred_body25[0].detach().cpu().numpy()
        initial_residual = gate_ops.weighted_residual_mm(
            candidate_np, target_np, weights_np, ik.UPPER11
        )
        medium_steps = 2 if coherent else self.medium_steps
        high_steps = 4 if coherent else self.high_steps
        steps = 0 if initial_residual <= 55.0 else (
            medium_steps if initial_residual <= 75.0 else high_steps
        )
        if steps:
            refined = fit_fixed_betas_soft_target(
                self.smpl_layer, self.regressor, target, self.fixed_betas,
                candidate.root_orient, init_body=candidate.body_pose.reshape(1, 69),
                init_translation=candidate.translation, iterations=steps,
                learning_rate=0.02, joint_indices=ik.UPPER11,
                endpoint_weight=0.5, torso_normal_weight=0.05,
                spine_stability_weight=0.02, spine_pose_indices=ik.SPINE_POSE,
                body_facing_weight=0.01, temporal_smooth_weight=0.01,
                prev_body_pose=previous_body.reshape(1, 69), use_huber=False,
                joint_weights=weights, frozen_pose_indices=ik.LOWER_BODY_POSE,
                zero_pose_indices=ik.FORWARD_LOCK,
            )
            root = refined.root_orient.reshape(1, 3)
            body = refined.body_pose.reshape(1, 23, 3)
            pred_body25 = refined.pred_body25
        else:
            root = candidate.root_orient.reshape(1, 3)
            body = candidate.body_pose.reshape(1, 23, 3)
            pred_body25 = candidate.pred_body25

        previous_root_np = previous_root.detach().cpu().numpy().reshape(3)
        previous_body_np = previous_body.detach().cpu().numpy().reshape(23, 3)
        candidate_np = pred_body25[0].detach().cpu().numpy()
        diagnostic = pose_rotation_diagnostics(
            root[0].detach().cpu().numpy(), body[0].detach().cpu().numpy(),
            self.cache.rest_np, previous_root_np, previous_body_np,
        )
        gated = gate_ops.regional_gate(
            root[0].detach().cpu().numpy(), body[0].detach().cpu().numpy(),
            previous_root_np, previous_body_np, candidate_np, target_np,
            weights_np, diagnostic,
        )
        applied_root = torch.tensor(
            gated.root[None], dtype=torch.float32, device=previous_root.device
        )
        applied_body = torch.tensor(
            gated.body[None], dtype=torch.float32, device=previous_root.device
        )
        with torch.no_grad():
            output = self.smpl_layer(
                betas=self.fixed_betas.reshape(1, 10),
                global_orient=applied_root.unsqueeze(1), body_pose=applied_body,
            )
            unaligned = torch.einsum(
                "bvc,jv->bjc", output.vertices, self.regressor
            )
            translation = target[:, 8] - unaligned[:, 8]
            body25 = unaligned + translation[:, None]
            smpl24 = output.joints[:, :24] + translation[:, None]
            vertices = output.vertices + translation[:, None]
            selected = list(ik.UPPER11)
            residual = torch.linalg.norm(
                body25[:, selected] - target[:, selected], dim=-1
            ).mean(dim=-1) * 1000.0
            target_normal = compute_torso_normal(target)
            pred_normal = compute_torso_normal(body25)
            cosine = (target_normal * pred_normal).sum(-1).clamp(-1.0, 1.0)
            torso_deg = torch.rad2deg(torch.acos(cosine))
        torch.cuda.synchronize(previous_root.device)
        elapsed = time.perf_counter() - started
        self.frame_index += 1
        result = FixedBetasFitResult(
            root_orient=applied_root, body_pose=applied_body,
            translation=translation, pred_body25=body25, pred_smpl24=smpl24,
            pred_vertices=vertices, fixed_betas=self.fixed_betas,
            residual_mm=residual, torso_orientation_deg=torso_deg,
            elapsed_seconds=elapsed, iterations=steps,
        )
        metadata = AdaptiveMetadata(
            selected_root=candidate.selected_root,
            neural_prior_used=use_prior, motion_coherence=coherence,
            motion_speed_mps=speed, refinement_steps=steps,
            region_updates=gated.update_region, region_reasons=gated.reasons,
            region_residual_mm=gated.residual_mm,
            region_confidence=gated.confidence,
        )
        return result, metadata
