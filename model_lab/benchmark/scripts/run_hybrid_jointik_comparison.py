#!/usr/bin/env python3
"""Compare OG, production fitting, Direct Joint IK and Hybrid Joint IK + OG."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import run_three_model_suite as common


def load_hybrid_module(repo_root: Path):
    path = repo_root / "model_lab/models/05_hybrid_jointik_og_0917/fitter.py"
    spec = importlib.util.spec_from_file_location("hybrid_jointik_og_0917", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


METHOD_INFO = {
    "paper_neural_baseline": {
        "label": "Paper neural baseline", "kind": "og",
    },
    "production_upper_body_50step": {
        "label": "Production upper-body 50-step", "kind": "fit",
        "iterations": 50, "learning_rate": 0.02, "matmul_precision": "highest",
    },
    "direct_joint_ik": {
        "label": "Direct SMPL-skeleton Joint IK", "kind": "joint_ik",
    },
    "hybrid_jointik_og": {
        "label": "Joint IK + OG rotation prior", "kind": "hybrid",
        "og_passes": 1,
    },
}


def og_prior(runtime, target, beta, root, body):
    torch = runtime.torch
    with torch.no_grad():
        start = runtime.net.human_model.layer["neutral"](
            betas=beta, global_orient=root, body_pose=body)
        start_joints = torch.einsum(
            "bvc,jv->bjc", start.vertices, runtime.net.openpose_regressor)
        start_normal, rotation, translation = runtime.normalize_kp(
            start_joints, None, runtime.net.kp_index, R=None, T=None)
        target_normal, _, _ = runtime.normalize_kp(
            target, None, runtime.net.kp_index, R=rotation, T=translation)
        network_input = torch.stack([start_normal, target_normal], 1).permute(0, 3, 1, 2)
        _, _, _, candidate_body, candidate_root = runtime.net.predict(
            network_input, root, body, beta)
    return candidate_root.detach(), candidate_body.detach()


def run_joint_ik(runtime, targets: np.ndarray, beta_np: np.ndarray, seed,
                 hybrid_module, *, use_og: bool) -> dict[str, object]:
    import torch
    from smpl_0901.service import (
        body_facing_mismatch_deg, pose_rotation_diagnostics, unsafe_fit_reasons,
    )

    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    beta = torch.tensor(beta_np, dtype=torch.float32, device=runtime.device).reshape(1, 10)
    accepted_root, accepted_body, accepted_translation = [value.clone() for value in seed]
    predictions, candidates, vertices = [], [], []
    accepted_flags, reasons, timings = [], [], []

    # Warm the optional neural prior and the SMPL/FK path without changing state.
    warm_target = torch.tensor(targets[:1], dtype=torch.float32, device=runtime.device)
    prior_root = prior_body = None
    if use_og:
        prior_root, prior_body = og_prior(
            runtime, warm_target, beta, accepted_root, accepted_body)
    hybrid_module.solve_joint_ik(
        runtime.layer, runtime.regressor, warm_target, beta,
        accepted_root, accepted_body, accepted_translation,
        prior_root=prior_root, prior_body=prior_body)
    torch.cuda.synchronize(runtime.device)

    for target_np in targets:
        target = torch.tensor(target_np[None], dtype=torch.float32, device=runtime.device)
        previous_root_np = accepted_root[0, 0].detach().cpu().numpy()
        previous_body_np = accepted_body[0].detach().cpu().numpy()
        torch.cuda.synchronize(runtime.device)
        started = time.perf_counter()
        prior_root = prior_body = None
        if use_og:
            prior_root, prior_body = og_prior(
                runtime, target, beta, accepted_root, accepted_body)
        fit = hybrid_module.solve_joint_ik(
            runtime.layer, runtime.regressor, target, beta,
            accepted_root, accepted_body, accepted_translation,
            prior_root=prior_root, prior_body=prior_body)
        candidate_np = fit.pred_body25[0].detach().cpu().numpy()
        residual = float(common.aligned_error(
            candidate_np[None], target_np[None], common.UPPER11)[0])
        diagnostic = pose_rotation_diagnostics(
            fit.root_orient[0].cpu().numpy(), fit.body_pose[0].cpu().numpy(),
            runtime.rest_joints, previous_root_np, previous_body_np)
        facing = body_facing_mismatch_deg(
            target_np, fit.pred_smpl24[0].detach().cpu().numpy())
        unsafe = unsafe_fit_reasons(
            residual, diagnostic, max_residual_mm=100.0, max_twist_deg=100.0,
            max_delta_deg=90.0, facing_mismatch_deg=facing,
            max_facing_mismatch_deg=90.0)
        accepted = not unsafe
        if accepted:
            accepted_root = fit.root_orient.detach().reshape(1, 1, 3)
            accepted_body = fit.body_pose.detach().reshape(1, 23, 3)
            accepted_translation = fit.translation.detach().reshape(1, 3)
            output_vertices = fit.pred_vertices[0]
            output_joints = fit.pred_body25[0]
        else:
            held, held_body25, _ = common.reconstruct(
                runtime, accepted_root, accepted_body, accepted_translation, beta)
            output_vertices = held.vertices[0] + accepted_translation[0]
            output_joints = held_body25[0]
        torch.cuda.synchronize(runtime.device)
        timings.append((time.perf_counter() - started) * 1000.0)
        pelvis = output_joints[8]
        predictions.append((output_joints - pelvis).detach().cpu().numpy().astype(np.float32))
        candidates.append(
            (fit.pred_body25[0] - fit.pred_body25[0, 8]).detach().cpu().numpy().astype(np.float32))
        vertices.append((output_vertices - pelvis).detach().cpu().numpy().astype(np.float32))
        accepted_flags.append(accepted)
        reasons.append(unsafe)

    return {
        "pred": np.stack(predictions), "candidate": np.stack(candidates),
        "vertices": np.stack(vertices), "accepted": np.asarray(accepted_flags, bool),
        "reasons": reasons, "total_ms": np.asarray(timings, np.float64),
    }


def add_mesh_metrics(metrics: dict[str, object], result: dict[str, object],
                     ground_truth_vertices: np.ndarray | None) -> None:
    if ground_truth_vertices is None:
        return
    error_mm = np.linalg.norm(
        np.asarray(result["vertices"]) - ground_truth_vertices, axis=-1).mean(axis=1) * 1000.0
    metrics["pelvis_aligned_mpve_mm"] = common.statistics(error_mm)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--smpl-dir", type=Path, required=True)
    parser.add_argument("--og-source", type=Path, required=True)
    parser.add_argument("--og-checkpoint", type=Path, required=True)
    parser.add_argument("--og-model-dir", type=Path, required=True)
    parser.add_argument("--rig-b-fit", type=Path, required=True)
    parser.add_argument("--amass", type=Path, required=True)
    parser.add_argument("--h3wb", type=Path, required=True)
    parser.add_argument("--calibration-frames", type=int, default=20)
    parser.add_argument("--rig-b-frames", type=int, default=30)
    parser.add_argument("--h3wb-frames", type=int, default=280)
    parser.add_argument("--amass-frames", type=int, default=0)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    arrays_dir = args.output_dir / "arrays"
    arrays_dir.mkdir()

    repo_root = Path(__file__).resolve().parents[3]
    hybrid_module = load_hybrid_module(repo_root)
    before = common.gpu_snapshot()
    runtime = common.Runtime(
        args.smpl_dir, args.og_source, args.og_checkpoint, args.og_model_dir)
    datasets = common.prepare_datasets(runtime, args)
    report = {
        "schema": "smpl-model-lab/hybrid-jointik-comparison-v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "experimental; does not replace production bridge",
        "timing_scope": "batch=1 core including prior/IK, reconstruction and gate; excludes calibration, common seed, I/O, UDP, Dashboard and Unity",
        "models": METHOD_INFO,
        "gpu_before": before,
        "og_checkpoint_sha256": common.sha256(args.og_checkpoint),
        "datasets": {},
    }
    production = common.Method(
        "production_upper_body_50step", "Production upper-body 50-step",
        "fit", 50, 0.02, "highest")

    for dataset_key, dataset in datasets.items():
        targets = dataset["targets"]
        print(f"\n=== {dataset_key}: {len(targets)} frames ===", flush=True)
        seed = common.make_seed(
            runtime, dataset["seed_target"],
            runtime.torch.tensor(dataset["beta"], device=runtime.device))
        payload = {
            "target_body25": targets, "frame_ids": dataset["frame_ids"],
            "fixed_betas": dataset["beta"], "faces": runtime.faces,
        }
        if dataset["ground_truth_vertices"] is not None:
            payload["ground_truth_vertices"] = dataset["ground_truth_vertices"]
        runners = (
            ("paper_neural_baseline", lambda: common.run_og(
                runtime, targets, dataset["beta"], seed)),
            ("production_upper_body_50step", lambda: common.run_fitter(
                runtime, targets, dataset["beta"], seed, production)),
            ("direct_joint_ik", lambda: run_joint_ik(
                runtime, targets, dataset["beta"], seed, hybrid_module, use_og=False)),
            ("hybrid_jointik_og", lambda: run_joint_ik(
                runtime, targets, dataset["beta"], seed, hybrid_module, use_og=True)),
        )
        dataset_metrics = {}
        for method_key, runner in runners:
            print(f"{dataset_key}: {method_key}", flush=True)
            result = runner()
            metric = common.method_metrics(result, targets)
            add_mesh_metrics(metric, result, dataset["ground_truth_vertices"])
            dataset_metrics[method_key] = metric
            for name in ("pred", "candidate", "vertices", "accepted", "total_ms"):
                payload[f"{method_key}_{name}"] = result[name]
            print(json.dumps(metric, ensure_ascii=False), flush=True)
        np.savez_compressed(arrays_dir / f"{dataset_key}.npz", **payload)
        report["datasets"][dataset_key] = {
            "source": dataset["source"], "source_fps": dataset["source_fps"],
            "frames": int(len(targets)), "note": dataset["note"],
            "metrics": dataset_metrics,
        }

    report["gpu_after"] = common.gpu_snapshot()
    (args.output_dir / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["datasets"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
