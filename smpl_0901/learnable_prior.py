"""Runtime wrapper for the Learnable-SMPLify Body25 neural pose prior."""

from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path
import numpy as np


class LearnableSmplifyPrior:
    """Load the paper network and predict one root/body update at a time."""

    def __init__(self, source_dir: Path, checkpoint: Path, smpl_dir: Path, device) -> None:
        import torch
        import yaml
        from easydict import EasyDict as edict

        source_dir = Path(source_dir).resolve()
        checkpoint = Path(checkpoint).resolve()
        smpl_dir = Path(smpl_dir).resolve()
        required = (
            source_dir / "module" / "net_body25.py",
            source_dir / "config" / "net.yaml",
            checkpoint,
            smpl_dir / "smpl" / "SMPL_NEUTRAL.pkl",
            smpl_dir / "J_regressor_body25.npy",
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError(
                "adaptive-fast requires Learnable-SMPLify assets; missing: "
                + ", ".join(missing)
            )

        family = Path(tempfile.mkdtemp(prefix="smpl-prior-family-"))
        model_subdir = family / "smpl"
        model_subdir.mkdir()
        neutral = smpl_dir / "smpl" / "SMPL_NEUTRAL.pkl"
        regressor = smpl_dir / "J_regressor_body25.npy"
        for name in ("SMPL_NEUTRAL.pkl", "SMPL_MALE.pkl", "SMPL_FEMALE.pkl"):
            os.symlink(neutral, model_subdir / name)
        os.symlink(regressor, model_subdir / "J_regressor_body25.npy")

        for alias, value in {
            "bool": bool, "int": int, "float": float, "complex": complex,
            "object": object, "unicode": str, "str": str,
        }.items():
            if alias not in np.__dict__:
                setattr(np, alias, value)
        source_text = str(source_dir)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        from common.keypoint_geo import normalize_kp
        from module.net_body25 import NetBody25

        config = edict(yaml.safe_load(
            (source_dir / "config" / "net.yaml").read_text(encoding="utf-8")
        ))
        config.model_params.human_model.smpl_dir = str(family)
        self.torch = torch
        self.normalize_kp = normalize_kp
        self.net = NetBody25(config.model_params).to(device)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        self.net.load_state_dict(state["model"])
        self.net.eval()
        for key, layer in self.net.human_model.layer.items():
            self.net.human_model.layer[key] = layer.to(device)

    def predict(self, target, betas, root, body):
        """Return neural-prior (root, body) tensors without mutating state."""
        torch = self.torch
        root = root.reshape(1, 1, 3)
        body = body.reshape(1, 23, 3)
        betas = betas.reshape(1, 10)
        with torch.no_grad():
            start = self.net.human_model.layer["neutral"](
                betas=betas, global_orient=root, body_pose=body
            )
            start_joints = torch.einsum(
                "bvc,jv->bjc", start.vertices, self.net.openpose_regressor
            )
            start_normal, rotation, translation = self.normalize_kp(
                start_joints, None, self.net.kp_index, R=None, T=None
            )
            target_normal, _, _ = self.normalize_kp(
                target, None, self.net.kp_index, R=rotation, T=translation
            )
            network_input = torch.stack(
                [start_normal, target_normal], 1
            ).permute(0, 3, 1, 2)
            _, _, _, candidate_body, candidate_root = self.net.predict(
                network_input, root, body, betas
            )
        return candidate_root.detach(), candidate_body.detach()
