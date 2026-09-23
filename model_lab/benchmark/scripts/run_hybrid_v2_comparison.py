#!/usr/bin/env python3
"""Five-method comparison including Hybrid v2 adaptive refinement."""

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
import run_hybrid_jointik_comparison as v1


METHOD_INFO = {
    **v1.METHOD_INFO,
    "hybrid_v2_adaptive": {
        "label": "Hybrid v2 swing-twist + adaptive 0/3/5-step",
        "kind": "hybrid_v2",
        "refinement": {"residual_le_45mm": 0, "le_70mm": 3, "otherwise": 5},
    },
}


def load_v2(repo_root: Path):
    path = repo_root / "model_lab/models/06_hybrid_jointik_adaptive_0917/fitter.py"
    spec = importlib.util.spec_from_file_location("hybrid_jointik_adaptive_0917", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_v2(runtime, targets: np.ndarray, beta_np: np.ndarray, seed, module) -> dict[str, object]:
    import torch
    from smpl_0901.fixed_betas_fitter import fit_fixed_betas_soft_target
    from smpl_0901.service import pose_rotation_diagnostics, unsafe_fit_reasons

    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    beta = torch.tensor(beta_np, dtype=torch.float32, device=runtime.device).reshape(1, 10)
    accepted_root, accepted_body, accepted_translation = [value.clone() for value in seed]
    predictions, candidate_joints = [], []
    applied_vertices, candidate_vertices = [], []
    accepted_flags, reasons, timings, refinement_steps, roots = [], [], [], [], []

    # Calibrate the ambiguous torso/feet sign once from the trusted 100-step
    # seed, then keep it fixed for the complete stream.
    _, _, seed_smpl24 = common.reconstruct(
        runtime, accepted_root, accepted_body, accepted_translation, beta)
    seed_facing = module._facing_angle(
        targets[0], seed_smpl24[0].detach().cpu().numpy(), 1.0)
    facing_sign = 1.0 if seed_facing <= 90.0 else -1.0

    # Warm every path without changing the accepted tracker state.
    warm_target = torch.tensor(targets[:1], dtype=torch.float32, device=runtime.device)
    warm_root, warm_body = v1.og_prior(
        runtime, warm_target, beta, accepted_root, accepted_body)
    warm = module.solve_joint_ik_v2(
        runtime.layer, runtime.regressor, warm_target, beta,
        accepted_root, accepted_body, accepted_translation,
        prior_root=warm_root, prior_body=warm_body, facing_sign=facing_sign)
    fit_fixed_betas_soft_target(
        runtime.layer, runtime.regressor, warm_target, beta[0], warm.root_orient,
        init_body=warm.body_pose.reshape(1, 69), init_translation=warm.translation,
        iterations=2, learning_rate=0.02, joint_indices=common.UPPER11,
        endpoint_weight=0.5, torso_normal_weight=0.05,
        spine_stability_weight=0.02, spine_pose_indices=common.SPINE_POSE,
        body_facing_weight=0.01, temporal_smooth_weight=0.01,
        prev_body_pose=accepted_body.reshape(1, 69), use_huber=False,
        frozen_pose_indices=common.LOWER_POSE, zero_pose_indices=common.FORWARD_LOCK)
    torch.cuda.synchronize(runtime.device)

    for target_np in targets:
        target = torch.tensor(target_np[None], dtype=torch.float32, device=runtime.device)
        previous_root_np = accepted_root[0, 0].detach().cpu().numpy()
        previous_body_np = accepted_body[0].detach().cpu().numpy()
        torch.cuda.synchronize(runtime.device)
        started = time.perf_counter()

        prior_root, prior_body = v1.og_prior(
            runtime, target, beta, accepted_root, accepted_body)
        candidate = module.solve_joint_ik_v2(
            runtime.layer, runtime.regressor, target, beta,
            accepted_root, accepted_body, accepted_translation,
            prior_root=prior_root, prior_body=prior_body, facing_sign=facing_sign)
        initial_residual = float(common.aligned_error(
            candidate.pred_body25[0].detach().cpu().numpy()[None],
            target_np[None], common.UPPER11)[0])
        steps = 0 if initial_residual <= 45.0 else (3 if initial_residual <= 70.0 else 5)
        if steps:
            refined = fit_fixed_betas_soft_target(
                runtime.layer, runtime.regressor, target, beta[0], candidate.root_orient,
                init_body=candidate.body_pose.reshape(1, 69),
                init_translation=candidate.translation,
                iterations=steps, learning_rate=0.02, joint_indices=common.UPPER11,
                endpoint_weight=0.5, torso_normal_weight=0.05,
                spine_stability_weight=0.02, spine_pose_indices=common.SPINE_POSE,
                body_facing_weight=0.01, temporal_smooth_weight=0.01,
                prev_body_pose=accepted_body.reshape(1, 69), use_huber=False,
                frozen_pose_indices=common.LOWER_POSE,
                zero_pose_indices=common.FORWARD_LOCK)
            root = refined.root_orient.reshape(1, 3)
            body = refined.body_pose.reshape(1, 23, 3)
            translation = refined.translation.reshape(1, 3)
            pred_body25 = refined.pred_body25
            pred_smpl24 = refined.pred_smpl24
            pred_vertices = refined.pred_vertices
        else:
            root = candidate.root_orient.reshape(1, 3)
            body = candidate.body_pose.reshape(1, 23, 3)
            translation = candidate.translation.reshape(1, 3)
            pred_body25 = candidate.pred_body25
            pred_smpl24 = candidate.pred_smpl24
            pred_vertices = candidate.pred_vertices

        candidate_np = pred_body25[0].detach().cpu().numpy()
        residual = float(common.aligned_error(
            candidate_np[None], target_np[None], common.UPPER11)[0])
        diagnostic = pose_rotation_diagnostics(
            root[0].cpu().numpy(), body[0].cpu().numpy(), runtime.rest_joints,
            previous_root_np, previous_body_np)
        facing = module._facing_angle(
            target_np, pred_smpl24[0].detach().cpu().numpy(), facing_sign)
        unsafe = unsafe_fit_reasons(
            residual, diagnostic, max_residual_mm=100.0, max_twist_deg=100.0,
            max_delta_deg=90.0, facing_mismatch_deg=facing,
            # In the upper-body profile the legs are deliberately held at the
            # last accepted pose. A valid punch or torso turn can therefore
            # exceed 90 degrees relative to the held feet. Keep facing as a
            # candidate diagnostic, but do not use it as a hard rejection gate;
            # residual, twist and temporal-root limits still protect playback.
            max_facing_mismatch_deg=180.0)
        accepted = not unsafe
        if accepted:
            accepted_root = root.detach().reshape(1, 1, 3)
            accepted_body = body.detach().reshape(1, 23, 3)
            accepted_translation = translation.detach().reshape(1, 3)
            output_vertices = pred_vertices[0]
            output_joints = pred_body25[0]
        else:
            held, held_body25, _ = common.reconstruct(
                runtime, accepted_root, accepted_body, accepted_translation, beta)
            output_vertices = held.vertices[0] + accepted_translation[0]
            output_joints = held_body25[0]
        torch.cuda.synchronize(runtime.device)
        timings.append((time.perf_counter() - started) * 1000.0)

        applied_pelvis = output_joints[8]
        candidate_pelvis = pred_body25[0, 8]
        predictions.append(
            (output_joints - applied_pelvis).detach().cpu().numpy().astype(np.float32))
        candidate_joints.append(
            (pred_body25[0] - candidate_pelvis).detach().cpu().numpy().astype(np.float32))
        applied_vertices.append(
            (output_vertices - applied_pelvis).detach().cpu().numpy().astype(np.float32))
        candidate_vertices.append(
            (pred_vertices[0] - candidate_pelvis).detach().cpu().numpy().astype(np.float32))
        accepted_flags.append(accepted)
        reasons.append(unsafe)
        refinement_steps.append(steps)
        roots.append(candidate.selected_root)

    return {
        "pred": np.stack(predictions),
        "candidate": np.stack(candidate_joints),
        "vertices": np.stack(applied_vertices),
        "candidate_vertices": np.stack(candidate_vertices),
        "accepted": np.asarray(accepted_flags, bool),
        "reasons": reasons,
        "total_ms": np.asarray(timings, np.float64),
        "refinement_steps": np.asarray(refinement_steps, np.int8),
        "selected_roots": np.asarray(roots),
        "facing_sign": facing_sign,
    }


def add_v2_metrics(metrics: dict[str, object], result: dict[str, object]) -> None:
    values, counts = np.unique(result["refinement_steps"], return_counts=True)
    metrics["adaptive_refinement_frames"] = {
        str(int(value)): int(count) for value, count in zip(values, counts)}
    roots, root_counts = np.unique(result["selected_roots"], return_counts=True)
    metrics["selected_root_hypotheses"] = {
        str(value): int(count) for value, count in zip(roots, root_counts)}
    metrics["stream_facing_sign"] = float(result["facing_sign"])


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
    parser.add_argument(
        "--methods", default="all",
        help="comma-separated method keys, or 'all' (use v2-only during contention)")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    arrays_dir = args.output_dir / "arrays"
    arrays_dir.mkdir()

    repo_root = Path(__file__).resolve().parents[3]
    v1_module = v1.load_hybrid_module(repo_root)
    v2_module = load_v2(repo_root)
    before = common.gpu_snapshot()
    runtime = common.Runtime(
        args.smpl_dir, args.og_source, args.og_checkpoint, args.og_model_dir)
    datasets = common.prepare_datasets(runtime, args)
    report = {
        "schema": "smpl-model-lab/hybrid-v2-comparison-v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "experimental; production bridge remains unchanged",
        "timing_scope": "batch=1 core including OG, IK, adaptive refinement, reconstruction and gate; excludes calibration, seed, I/O, UDP, Dashboard and Unity",
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
            ("direct_joint_ik", lambda: v1.run_joint_ik(
                runtime, targets, dataset["beta"], seed, v1_module, use_og=False)),
            ("hybrid_jointik_og", lambda: v1.run_joint_ik(
                runtime, targets, dataset["beta"], seed, v1_module, use_og=True)),
            ("hybrid_v2_adaptive", lambda: run_v2(
                runtime, targets, dataset["beta"], seed, v2_module)),
        )
        selected_methods = set(METHOD_INFO) if args.methods == "all" else {
            value.strip() for value in args.methods.split(",") if value.strip()}
        unknown = selected_methods - set(METHOD_INFO)
        if unknown:
            raise ValueError(f"unknown methods: {sorted(unknown)}")
        dataset_metrics = {}
        for method_key, runner in runners:
            if method_key not in selected_methods:
                continue
            print(f"{dataset_key}: {method_key}", flush=True)
            result = runner()
            metric = common.method_metrics(result, targets)
            v1.add_mesh_metrics(metric, result, dataset["ground_truth_vertices"])
            if method_key == "hybrid_v2_adaptive":
                add_v2_metrics(metric, result)
            dataset_metrics[method_key] = metric
            for name in ("pred", "candidate", "vertices", "accepted", "total_ms"):
                payload[f"{method_key}_{name}"] = result[name]
            if "candidate_vertices" in result:
                payload[f"{method_key}_candidate_vertices"] = result["candidate_vertices"]
            if "refinement_steps" in result:
                payload[f"{method_key}_refinement_steps"] = result["refinement_steps"]
                payload[f"{method_key}_selected_roots"] = result["selected_roots"]
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
