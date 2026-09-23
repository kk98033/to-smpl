#!/usr/bin/env python3
"""Benchmark Hybrid v3 quality weighting and regional safety gate."""

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
import run_hybrid_v2_comparison as v2


METHOD_KEY = "hybrid_v3_confidence_limb_gate"
REFINEMENT_POLICIES = {
    "standard": (2, 4),
    "lite": (1, 2),
    "none": (0, 0),
}


def load_model(repo_root: Path):
    path = repo_root / "model_lab/models/07_hybrid_v3_confidence_limb_gate_0918/fitter.py"
    spec = importlib.util.spec_from_file_location("hybrid_v3_confidence_limb_gate_0918", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_v5(repo_root: Path):
    path = repo_root / "model_lab/models/09_hybrid_v5_adaptive_gpu_0919/fitter.py"
    spec = importlib.util.spec_from_file_location("hybrid_v5_adaptive_gpu_0919", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def temporal_acceleration_mm(points: np.ndarray) -> dict[str, float]:
    if len(points) < 3:
        return common.statistics(np.zeros(1, dtype=np.float32))
    acceleration = np.linalg.norm(np.diff(points, n=2, axis=0), axis=2).mean(axis=1) * 1000.0
    return common.statistics(acceleration)


def motion_coherence(history: list[np.ndarray], source_fps: float,
                     indices=common.UPPER11) -> tuple[float, float]:
    """Return four-frame direction coherence and mean pelvis-aligned speed."""
    if len(history) < 2:
        return 0.0, 0.0
    points = np.stack(history[-5:]).astype(np.float64)
    points = points - points[:, [8]]
    points = points[:, list(indices)]
    distance = np.linalg.norm(np.diff(points, axis=0), axis=2)
    path = distance.sum(axis=0)
    net = np.linalg.norm(points[-1] - points[0], axis=1)
    coherence = float(np.mean(net / (path + 1e-8)))
    seconds = (len(points) - 1) / max(float(source_fps), 1.0)
    speed = float(np.mean(path) / max(seconds, 1e-8))
    return coherence, speed


def run_v3(runtime, targets: np.ndarray, beta_np: np.ndarray, seed, source_fps: float,
           v2_module, v3_module, v5_module, *, refinement_policy: str = "standard",
           og_stride: int = 1, solver_version: str = "v2",
           schedule: str = "fixed", motion_coherence_threshold: float = 0.75,
           motion_speed_threshold: float = 0.3) -> dict[str, object]:
    import torch
    from smpl_0901.fixed_betas_fitter import fit_fixed_betas_soft_target
    from smpl_0901.service import pose_rotation_diagnostics

    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    beta = torch.tensor(beta_np, dtype=torch.float32, device=runtime.device).reshape(1, 10)
    accepted_root, accepted_body, accepted_translation = [value.clone() for value in seed]
    _, seed_body25, seed_smpl24 = common.reconstruct(
        runtime, accepted_root, accepted_body, accepted_translation, beta)
    previous_prediction = seed_body25[0].detach().cpu().numpy()
    quality = v3_module.GeometryQualityEstimator(targets[0], source_fps)
    seed_facing = v2_module._facing_angle(
        targets[0], seed_smpl24[0].detach().cpu().numpy(), 1.0)
    facing_sign = 1.0 if seed_facing <= 90.0 else -1.0
    static_cache = (
        v5_module.build_static_cache(v2_module, runtime.layer, runtime.regressor, beta)
        if solver_version == "v5" else None
    )

    def solve(target, prior_root, prior_body):
        if solver_version == "v5":
            return v5_module.solve_joint_ik_v5(
                v2_module, static_cache, runtime.layer, runtime.regressor,
                target, beta, accepted_root, accepted_body, accepted_translation,
                prior_root=prior_root, prior_body=prior_body, facing_sign=facing_sign)
        return v2_module.solve_joint_ik_v2(
            runtime.layer, runtime.regressor, target, beta,
            accepted_root, accepted_body, accepted_translation,
            prior_root=prior_root, prior_body=prior_body, facing_sign=facing_sign)

    predictions, candidates, applied_vertices, candidate_vertices = [], [], [], []
    accepted_flags, reasons, timings, steps_all, roots = [], [], [], [], []
    quality_all, region_updates, region_residuals = [], [], []
    motion_flags, motion_coherences, motion_speeds = [], [], []
    target_history: list[np.ndarray] = []
    region_order = ("torso", "right_arm", "left_arm")

    # Warm all computational paths without mutating tracker/quality state.
    warm_target = torch.tensor(targets[:1], dtype=torch.float32, device=runtime.device)
    warm_root, warm_body = v1.og_prior(
        runtime, warm_target, beta, accepted_root, accepted_body)
    warm = solve(warm_target, warm_root, warm_body)
    fit_fixed_betas_soft_target(
        runtime.layer, runtime.regressor, warm_target, beta[0], warm.root_orient,
        init_body=warm.body_pose.reshape(1, 69), init_translation=warm.translation,
        iterations=2, learning_rate=0.02, joint_indices=common.UPPER11,
        endpoint_weight=0.5, torso_normal_weight=0.05,
        spine_stability_weight=0.02, spine_pose_indices=common.SPINE_POSE,
        body_facing_weight=0.01, temporal_smooth_weight=0.01,
        prev_body_pose=accepted_body.reshape(1, 69), use_huber=False,
        joint_weights=torch.ones((1, 25), device=runtime.device),
        frozen_pose_indices=common.LOWER_POSE, zero_pose_indices=common.FORWARD_LOCK)
    torch.cuda.synchronize(runtime.device)

    medium_steps, high_steps = REFINEMENT_POLICIES[refinement_policy]
    og_evaluated = []
    for frame_index, target_np in enumerate(targets):
        target_history.append(np.asarray(target_np, dtype=np.float32))
        coherence, motion_speed = motion_coherence(target_history, source_fps)
        coherent_motion = (
            schedule == "adaptive"
            and coherence >= motion_coherence_threshold
            and motion_speed >= motion_speed_threshold
        )
        previous_root_np = accepted_root[0, 0].detach().cpu().numpy()
        previous_body_np = accepted_body[0].detach().cpu().numpy()
        weights_np = quality.update(target_np)
        safe_target_np = v3_module.stabilized_target(
            target_np, previous_prediction, weights_np)
        target = torch.tensor(safe_target_np[None], dtype=torch.float32, device=runtime.device)
        weights = torch.tensor(weights_np[None], dtype=torch.float32, device=runtime.device)

        torch.cuda.synchronize(runtime.device)
        started = time.perf_counter()
        evaluate_og = coherent_motion or frame_index % og_stride == 0
        if evaluate_og:
            prior_root, prior_body = v1.og_prior(
                runtime, target, beta, accepted_root, accepted_body)
        else:
            # Between neural-prior keyframes, analytical IK starts from the
            # last accepted local rotations instead of a stale neural pose.
            prior_root = accepted_root[:, 0]
            prior_body = accepted_body
        candidate = solve(target, prior_root, prior_body)
        candidate_np = candidate.pred_body25[0].detach().cpu().numpy()
        initial_residual = v3_module.weighted_residual_mm(
            candidate_np, target_np, weights_np, common.UPPER11)
        active_medium, active_high = (
            REFINEMENT_POLICIES["standard"] if coherent_motion
            else (medium_steps, high_steps)
        )
        steps = 0 if initial_residual <= 55.0 else (
            active_medium if initial_residual <= 75.0 else active_high)
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
                joint_weights=weights, frozen_pose_indices=common.LOWER_POSE,
                zero_pose_indices=common.FORWARD_LOCK)
            root = refined.root_orient.reshape(1, 3)
            body = refined.body_pose.reshape(1, 23, 3)
            pred_body25 = refined.pred_body25
            pred_vertices = refined.pred_vertices
        else:
            root = candidate.root_orient.reshape(1, 3)
            body = candidate.body_pose.reshape(1, 23, 3)
            pred_body25 = candidate.pred_body25
            pred_vertices = candidate.pred_vertices

        candidate_np = pred_body25[0].detach().cpu().numpy()
        diagnostic = pose_rotation_diagnostics(
            root[0].detach().cpu().numpy(), body[0].detach().cpu().numpy(),
            runtime.rest_joints, previous_root_np, previous_body_np)
        gate = v3_module.regional_gate(
            root[0].detach().cpu().numpy(), body[0].detach().cpu().numpy(),
            previous_root_np, previous_body_np, candidate_np, target_np,
            weights_np, diagnostic)

        applied_root = torch.tensor(
            gate.root[None, None], dtype=torch.float32, device=runtime.device)
        applied_body = torch.tensor(
            gate.body[None], dtype=torch.float32, device=runtime.device)
        output = runtime.smpl(applied_root, applied_body, beta)
        unaligned = runtime.body25(output)
        applied_translation = (
            torch.tensor(target_np[None, 8], dtype=torch.float32, device=runtime.device)
            - unaligned[:, 8])
        output_joints = unaligned + applied_translation[:, None]
        output_vertices = output.vertices + applied_translation[:, None]

        accepted_root = applied_root.detach()
        accepted_body = applied_body.detach()
        accepted_translation = applied_translation.detach()
        previous_prediction = output_joints[0].detach().cpu().numpy()
        frame_updated = any(gate.update_region.values())
        frame_reasons = [
            f"{region}:{reason}" for region in region_order
            for reason in gate.reasons[region]
        ]
        torch.cuda.synchronize(runtime.device)
        timings.append((time.perf_counter() - started) * 1000.0)

        applied_pelvis = output_joints[0, 8]
        candidate_pelvis = pred_body25[0, 8]
        predictions.append(
            (output_joints[0] - applied_pelvis).detach().cpu().numpy().astype(np.float32))
        candidates.append(
            (pred_body25[0] - candidate_pelvis).detach().cpu().numpy().astype(np.float32))
        applied_vertices.append(
            (output_vertices[0] - applied_pelvis).detach().cpu().numpy().astype(np.float32))
        candidate_vertices.append(
            (pred_vertices[0] - candidate_pelvis).detach().cpu().numpy().astype(np.float32))
        accepted_flags.append(frame_updated)
        reasons.append(frame_reasons)
        steps_all.append(steps)
        roots.append(candidate.selected_root)
        og_evaluated.append(evaluate_og)
        motion_flags.append(coherent_motion)
        motion_coherences.append(coherence)
        motion_speeds.append(motion_speed)
        quality_all.append(weights_np)
        region_updates.append([gate.update_region[name] for name in region_order])
        region_residuals.append([gate.residual_mm[name] for name in region_order])

    return {
        "pred": np.stack(predictions), "candidate": np.stack(candidates),
        "vertices": np.stack(applied_vertices),
        "candidate_vertices": np.stack(candidate_vertices),
        "accepted": np.asarray(accepted_flags, bool), "reasons": reasons,
        "total_ms": np.asarray(timings, np.float64),
        "refinement_steps": np.asarray(steps_all, np.int8),
        "selected_roots": np.asarray(roots),
        "joint_quality": np.stack(quality_all).astype(np.float32),
        "region_updates": np.asarray(region_updates, bool),
        "region_residual_mm": np.asarray(region_residuals, np.float32),
        "region_order": np.asarray(region_order), "facing_sign": facing_sign,
        "og_evaluated": np.asarray(og_evaluated, bool),
        "refinement_policy": refinement_policy, "og_stride": int(og_stride),
        "solver_version": solver_version,
        "schedule": schedule,
        "motion_flags": np.asarray(motion_flags, bool),
        "motion_coherence": np.asarray(motion_coherences, np.float32),
        "motion_speed_mps": np.asarray(motion_speeds, np.float32),
    }


def add_v3_metrics(metric: dict[str, object], result: dict[str, object]) -> None:
    steps, counts = np.unique(result["refinement_steps"], return_counts=True)
    metric["adaptive_refinement_frames"] = {
        str(int(step)): int(count) for step, count in zip(steps, counts)}
    roots, counts = np.unique(result["selected_roots"], return_counts=True)
    metric["selected_root_hypotheses"] = {
        str(root): int(count) for root, count in zip(roots, counts)}
    metric["mean_joint_quality"] = float(np.mean(result["joint_quality"][:, list(common.UPPER11)]))
    metric["region_update_rate"] = {
        str(name): float(np.mean(result["region_updates"][:, index]))
        for index, name in enumerate(result["region_order"])}
    metric["region_residual_mm"] = {
        str(name): common.statistics(result["region_residual_mm"][:, index])
        for index, name in enumerate(result["region_order"])}
    metric["applied_temporal_acceleration_mm"] = temporal_acceleration_mm(result["pred"])
    metric["facing_sign"] = float(result["facing_sign"])
    metric["refinement_policy"] = str(result["refinement_policy"])
    metric["og_stride"] = int(result["og_stride"])
    metric["og_evaluation_rate"] = float(np.mean(result["og_evaluated"]))
    metric["solver_version"] = str(result["solver_version"])
    metric["schedule"] = str(result["schedule"])
    metric["coherent_motion_rate"] = float(np.mean(result["motion_flags"]))
    metric["motion_coherence"] = common.statistics(result["motion_coherence"])
    metric["motion_speed_mps"] = common.statistics(result["motion_speed_mps"])


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
    parser.add_argument("--amass-frames", type=int, default=0)
    parser.add_argument("--h3wb-frames", type=int, default=280)
    parser.add_argument(
        "--refinement-policy", choices=tuple(REFINEMENT_POLICIES), default="standard")
    parser.add_argument("--og-stride", type=int, default=1)
    parser.add_argument("--solver-version", choices=("v2", "v5"), default="v2")
    parser.add_argument("--schedule", choices=("fixed", "adaptive"), default="fixed")
    parser.add_argument("--motion-coherence-threshold", type=float, default=0.75)
    parser.add_argument("--motion-speed-threshold", type=float, default=0.3)
    parser.add_argument("--compile-smpl", action="store_true")
    parser.add_argument("--method-key", default=METHOD_KEY)
    parser.add_argument("--method-label", default="Hybrid v3 confidence + regional gate")
    args = parser.parse_args()
    if args.og_stride < 1:
        parser.error("--og-stride must be at least 1")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    arrays_dir = args.output_dir / "arrays"
    arrays_dir.mkdir()

    repo_root = Path(__file__).resolve().parents[3]
    v2_module = v2.load_v2(repo_root)
    v3_module = load_model(repo_root)
    v5_module = load_v5(repo_root)
    before = common.gpu_snapshot()
    runtime = common.Runtime(
        args.smpl_dir, args.og_source, args.og_checkpoint, args.og_model_dir)
    if args.compile_smpl:
        runtime.layer.compile(mode="reduce-overhead")
    datasets = common.prepare_datasets(runtime, args)
    medium_steps, high_steps = REFINEMENT_POLICIES[args.refinement_policy]
    method_info = {
        args.method_key: {
            "label": args.method_label,
            "kind": "hybrid_v3_fastpath" if args.method_key != METHOD_KEY else "hybrid_v3",
            "refinement_policy": args.refinement_policy,
            "refinement": {
                "weighted_residual_le_55mm": 0,
                "le_75mm": medium_steps,
                "otherwise": high_steps,
            },
            "og_stride": args.og_stride,
            "solver_version": args.solver_version,
            "schedule": args.schedule,
            "motion_coherence_threshold": args.motion_coherence_threshold,
            "motion_speed_threshold_mps": args.motion_speed_threshold,
            "compile_smpl": bool(args.compile_smpl),
            "confidence": "not required; causal 3-D geometric quality fallback",
        }
    }
    report = {
        "schema": "smpl-model-lab/hybrid-v3-comparison-v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "experimental; production bridge remains unchanged",
        "quality_source": "causal geometry fallback; historical recordings lack detector confidence",
        "timing_scope": "batch=1 OG + IK + weighted adaptive refinement + regional gate + final SMPL forward; excludes calibration, seed, I/O, UDP, Dashboard and Unity",
        "models": method_info, "gpu_before": before,
        "og_checkpoint_sha256": common.sha256(args.og_checkpoint), "datasets": {},
    }
    for dataset_key, dataset in datasets.items():
        targets = dataset["targets"]
        print(f"\n=== {dataset_key}: {len(targets)} frames ===", flush=True)
        seed = common.make_seed(
            runtime, dataset["seed_target"],
            runtime.torch.tensor(dataset["beta"], device=runtime.device))
        result = run_v3(
            runtime, targets, dataset["beta"], seed, dataset["source_fps"],
            v2_module, v3_module, v5_module,
            refinement_policy=args.refinement_policy,
            og_stride=args.og_stride, solver_version=args.solver_version,
            schedule=args.schedule,
            motion_coherence_threshold=args.motion_coherence_threshold,
            motion_speed_threshold=args.motion_speed_threshold)
        metric = common.method_metrics(result, targets)
        v1.add_mesh_metrics(metric, result, dataset["ground_truth_vertices"])
        add_v3_metrics(metric, result)
        print(json.dumps(metric, ensure_ascii=False), flush=True)
        payload = {
            "target_body25": targets, "frame_ids": dataset["frame_ids"],
            "fixed_betas": dataset["beta"], "faces": runtime.faces,
        }
        if dataset["ground_truth_vertices"] is not None:
            payload["ground_truth_vertices"] = dataset["ground_truth_vertices"]
        for name in ("pred", "candidate", "vertices", "candidate_vertices", "accepted",
                     "total_ms", "refinement_steps", "selected_roots", "joint_quality",
                     "region_updates", "region_residual_mm", "region_order", "og_evaluated"):
            payload[f"{args.method_key}_{name}"] = result[name]
        for name in ("motion_flags", "motion_coherence", "motion_speed_mps"):
            payload[f"{args.method_key}_{name}"] = result[name]
        np.savez_compressed(arrays_dir / f"{dataset_key}.npz", **payload)
        report["datasets"][dataset_key] = {
            "source": dataset["source"], "source_fps": dataset["source_fps"],
            "frames": int(len(targets)), "note": dataset["note"],
            "metrics": {args.method_key: metric},
        }
    report["gpu_after"] = common.gpu_snapshot()
    (args.output_dir / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
