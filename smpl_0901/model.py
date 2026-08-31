"""Minimal SMPL + Body25 loader used by the 0901 fitting strategy."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch


def load_smpl_body25(model_root: str | Path, device: torch.device):
    """Load neutral SMPL and the exact Body25 vertex regressor used in 0901."""
    import smplx

    root = Path(model_root)
    model_path = root / "smpl" / "SMPL_NEUTRAL.pkl"
    regressor_path = root / "J_regressor_body25.npy"
    if not model_path.is_file():
        raise FileNotFoundError(
            f"Missing licensed SMPL model: {model_path}. See models/README.md."
        )
    if not regressor_path.is_file():
        raise FileNotFoundError(f"Missing Body25 regressor: {regressor_path}")

    layer = smplx.create(
        str(root),
        "smpl",
        gender="NEUTRAL",
        ext="pkl",
        create_body_pose=False,
        create_betas=False,
        create_global_orient=False,
        create_transl=False,
    ).to(device)
    regressor = torch.tensor(
        np.load(regressor_path), dtype=torch.float32, device=device
    )
    if tuple(regressor.shape) != (25, 6890):
        raise ValueError(
            f"J_regressor_body25 must have shape (25,6890), got {tuple(regressor.shape)}"
        )
    return layer, regressor
