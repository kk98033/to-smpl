"""Low-risk 40-step TF32 adapter around the production SMPL fitter."""

from __future__ import annotations

import torch

from smpl_0901.fixed_betas_fitter import FixedBetasFitResult, fit_fixed_betas_soft_target


UPPER11 = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12)
LOWER_BODY_POSE = (0, 1, 3, 4, 6, 7, 9, 10)
SPINE_POSE = (2, 5, 8)
FORWARD_LOCK = (11, 14, 19, 20)


def fit_tuned_40step(
    smpl_layer,
    body25_regressor: torch.Tensor,
    target_body25: torch.Tensor,
    fixed_betas: torch.Tensor,
    init_root: torch.Tensor,
    *,
    init_body: torch.Tensor | None,
    init_translation: torch.Tensor | None,
    previous_body: torch.Tensor | None,
) -> FixedBetasFitResult:
    """Apply the 0916 candidate without changing the production loss profile."""
    torch.set_float32_matmul_precision("high")
    if target_body25.device.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    return fit_fixed_betas_soft_target(
        smpl_layer,
        body25_regressor,
        target_body25,
        fixed_betas,
        init_root,
        init_body=init_body,
        init_translation=init_translation,
        iterations=40,
        learning_rate=0.03,
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
