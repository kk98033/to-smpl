#!/usr/bin/env python3
"""Run the fixed three-dataset / three-model SMPL tracking benchmark.

The benchmark is deliberately outside the production service.  It compares:
paper neural baseline, the deployed 50-step fitter, and the 0916 40-step TF32
candidate.  Calibration, file I/O and visualisation are excluded from timing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


BODY15 = tuple(range(15))
UPPER11 = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12)
LOWER_POSE = (0, 1, 3, 4, 6, 7, 9, 10)
SPINE_POSE = (2, 5, 8)
FORWARD_LOCK = (11, 14, 19, 20)


@dataclass(frozen=True)
class Method:
    key: str
    label: str
    kind: str
    iterations: int = 0
    learning_rate: float = 0.0
    matmul_precision: str = "highest"


METHODS = (
    Method("paper_neural_baseline", "論文神經網路基準", "og"),
    Method("production_upper_body_50step", "正式版上半身 50-step", "fit", 50, 0.02, "highest"),
    Method("tuned_40step_tf32_0916", "0916 40-step TF32", "fit", 40, 0.03, "high"),
)


def statistics(values: np.ndarray) -> dict[str, float]:
    x = np.asarray(values, dtype=np.float64)
    return {name: float(value) for name, value in {
        "mean": np.mean(x), "p50": np.percentile(x, 50),
        "p95": np.percentile(x, 95), "min": np.min(x), "max": np.max(x),
    }.items()}


def gpu_snapshot() -> dict[str, object]:
    query = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw",
         "--format=csv,noheader,nounits"], check=True, text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip().split(",")
    processes = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"],
        check=True, text=True, stdout=subprocess.PIPE,
    ).stdout.strip().splitlines()
    return {
        "name": query[0].strip(), "utilization_percent": float(query[1]),
        "temperature_c": float(query[2]), "power_w": query[3].strip(),
        "compute_processes": [line.strip() for line in processes if line.strip()],
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def longest_accepted_run(path: Path) -> list[dict[str, object]]:
    best: list[dict[str, object]] = []
    current: list[dict[str, object]] = []
    previous = None
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            contiguous = (
                previous is not None
                and int(record["frame"]) == int(previous["frame"]) + 1
                and 0 < int(record["timestamp_ns"]) - int(previous["timestamp_ns"]) < 2_000_000_000
            )
            if record.get("schema") == "smpl-0901.fit/v1" and record.get("accepted") is True:
                current = current + [record] if current and contiguous else [record]
            else:
                current = []
            if len(current) > len(best):
                best = current.copy()
            previous = record
    return best


def aligned_error(pred: np.ndarray, target: np.ndarray, indices) -> np.ndarray:
    p = pred - pred[:, [8]]
    t = target - target[:, [8]]
    return np.linalg.norm(p[:, indices] - t[:, indices], axis=-1).mean(axis=1) * 1000.0


def longest_false_run(values: np.ndarray) -> int:
    longest = current = 0
    for value in values:
        current = 0 if bool(value) else current + 1
        longest = max(longest, current)
    return longest


class Runtime:
    def __init__(self, smpl_dir: Path, og_source: Path, checkpoint: Path, og_model_dir: Path):
        import torch
        import yaml
        from easydict import EasyDict as edict
        from smpl_0901.model import load_smpl_body25

        for alias, value in {"bool": bool, "int": int, "float": float, "complex": complex,
                             "object": object, "unicode": str, "str": str}.items():
            if alias not in np.__dict__:
                setattr(np, alias, value)
        sys.path.insert(0, str(og_source))
        from common.keypoint_geo import normalize_kp
        from module.net_body25 import NetBody25

        self.torch = torch
        self.device = torch.device("cuda")
        self.layer, self.regressor = load_smpl_body25(smpl_dir, self.device)
        self.rest_joints = (self.layer.J_regressor @ self.layer.v_template).detach().cpu().numpy()
        self.faces = np.asarray(self.layer.faces, dtype=np.int32)
        config = edict(yaml.safe_load((og_source / "config/net.yaml").read_text(encoding="utf-8")))
        config.model_params.human_model.smpl_dir = str(og_model_dir)
        self.net = NetBody25(config.model_params).to(self.device)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        self.net.load_state_dict(state["model"])
        self.net.eval()
        for key in self.net.human_model.layer:
            self.net.human_model.layer[key] = self.net.human_model.layer[key].to(self.device)
        self.normalize_kp = normalize_kp

    def smpl(self, root, body, beta):
        return self.layer(betas=beta, global_orient=root, body_pose=body)

    def body25(self, output):
        return self.torch.einsum("bvc,jv->bjc", output.vertices, self.regressor)


def reconstruct(runtime: Runtime, root, body, translation, beta):
    output = runtime.smpl(root.view(1, 1, 3), body.view(1, 23, 3), beta.view(1, 10))
    body25 = runtime.body25(output) + translation.view(1, 1, 3)
    smpl24 = output.joints[:, :24] + translation.view(1, 1, 3)
    return output, body25, smpl24


def make_seed(runtime: Runtime, target_np: np.ndarray, beta):
    import torch
    from smpl_0901.fixed_betas_fitter import fit_fixed_betas_soft_target
    from smpl_0901.frame0_initializer import analytical_root_seed

    target = torch.tensor(target_np[None], dtype=torch.float32, device=runtime.device)
    root = torch.tensor(analytical_root_seed(target_np)[None], dtype=torch.float32, device=runtime.device)
    fit = fit_fixed_betas_soft_target(
        runtime.layer, runtime.regressor, target, beta, root,
        iterations=100, learning_rate=0.02, joint_indices=UPPER11,
        endpoint_weight=0.5, torso_normal_weight=0.05,
        spine_stability_weight=0.02, spine_pose_indices=SPINE_POSE,
        body_facing_weight=0.01, temporal_smooth_weight=0.0,
        use_huber=False, frozen_pose_indices=LOWER_POSE,
        zero_pose_indices=FORWARD_LOCK,
    )
    return (fit.root_orient.detach().reshape(1, 1, 3),
            fit.body_pose.detach().reshape(1, 23, 3),
            fit.translation.detach().reshape(1, 3))


def run_fitter(runtime: Runtime, targets: np.ndarray, beta_np: np.ndarray,
               seed, method: Method) -> dict[str, object]:
    import torch
    from smpl_0901.fixed_betas_fitter import fit_fixed_betas_soft_target
    from smpl_0901.service import body_facing_mismatch_deg, pose_rotation_diagnostics, unsafe_fit_reasons

    torch.set_float32_matmul_precision(method.matmul_precision)
    torch.backends.cuda.matmul.allow_tf32 = method.matmul_precision != "highest"
    torch.backends.cudnn.allow_tf32 = method.matmul_precision != "highest"
    beta = torch.tensor(beta_np, dtype=torch.float32, device=runtime.device).reshape(1, 10)
    accepted_root, accepted_body, accepted_translation = [x.clone() for x in seed]
    applied, candidates, vertices, accepted_flags, reasons, timings = [], [], [], [], [], []

    # Warm-up without changing tracker state.
    warm_target = torch.tensor(targets[:1], dtype=torch.float32, device=runtime.device)
    fit_fixed_betas_soft_target(
        runtime.layer, runtime.regressor, warm_target, beta[0], accepted_root[:, 0],
        init_body=accepted_body.reshape(1, 69), init_translation=accepted_translation,
        iterations=2, learning_rate=method.learning_rate, joint_indices=UPPER11,
        endpoint_weight=0.5, torso_normal_weight=0.05,
        spine_stability_weight=0.02, spine_pose_indices=SPINE_POSE,
        body_facing_weight=0.01, temporal_smooth_weight=0.01,
        prev_body_pose=accepted_body.reshape(1, 69), use_huber=False,
        frozen_pose_indices=LOWER_POSE, zero_pose_indices=FORWARD_LOCK,
    )

    for target_np in targets:
        target = torch.tensor(target_np[None], dtype=torch.float32, device=runtime.device)
        previous_root_np = accepted_root[0, 0].detach().cpu().numpy()
        previous_body_np = accepted_body[0].detach().cpu().numpy()
        torch.cuda.synchronize(runtime.device)
        started = time.perf_counter()
        fit = fit_fixed_betas_soft_target(
            runtime.layer, runtime.regressor, target, beta[0], accepted_root[:, 0],
            init_body=accepted_body.reshape(1, 69), init_translation=accepted_translation,
            iterations=method.iterations, learning_rate=method.learning_rate,
            joint_indices=UPPER11, endpoint_weight=0.5, torso_normal_weight=0.05,
            spine_stability_weight=0.02, spine_pose_indices=SPINE_POSE,
            body_facing_weight=0.01, temporal_smooth_weight=0.01,
            prev_body_pose=accepted_body.reshape(1, 69), use_huber=False,
            frozen_pose_indices=LOWER_POSE, zero_pose_indices=FORWARD_LOCK,
        )
        candidate_root = fit.root_orient.detach().reshape(1, 1, 3)
        candidate_body = fit.body_pose.detach().reshape(1, 23, 3)
        candidate_translation = fit.translation.detach().reshape(1, 3)
        candidate_np = fit.pred_body25[0].detach().cpu().numpy()
        residual = float(aligned_error(candidate_np[None], target_np[None], UPPER11)[0])
        diagnostic = pose_rotation_diagnostics(
            candidate_root[0, 0].cpu().numpy(), candidate_body[0].cpu().numpy(),
            runtime.rest_joints, previous_root_np, previous_body_np,
        )
        facing = body_facing_mismatch_deg(
            target_np, fit.pred_smpl24[0].detach().cpu().numpy())
        unsafe = unsafe_fit_reasons(
            residual, diagnostic, max_residual_mm=100.0, max_twist_deg=100.0,
            max_delta_deg=90.0, facing_mismatch_deg=facing,
            max_facing_mismatch_deg=90.0,
        )
        accepted = not unsafe
        if accepted:
            accepted_root = candidate_root
            accepted_body = candidate_body
            accepted_translation = candidate_translation
            output = fit.pred_vertices[0]
            joints = fit.pred_body25[0]
        else:
            held, held_body25, _ = reconstruct(
                runtime, accepted_root, accepted_body, accepted_translation, beta)
            output = held.vertices[0] + accepted_translation[0]
            joints = held_body25[0]
        torch.cuda.synchronize(runtime.device)
        timings.append((time.perf_counter() - started) * 1000.0)
        pelvis = joints[8]
        applied.append((joints - pelvis).detach().cpu().numpy().astype(np.float32))
        candidates.append((fit.pred_body25[0] - fit.pred_body25[0, 8]).detach().cpu().numpy().astype(np.float32))
        vertices.append((output - pelvis).detach().cpu().numpy().astype(np.float32))
        accepted_flags.append(accepted)
        reasons.append(unsafe)
    return {
        "pred": np.stack(applied), "candidate": np.stack(candidates),
        "vertices": np.stack(vertices), "accepted": np.asarray(accepted_flags, bool),
        "reasons": reasons, "total_ms": np.asarray(timings, np.float64),
    }


def run_og(runtime: Runtime, targets: np.ndarray, beta_np: np.ndarray, seed) -> dict[str, object]:
    import torch

    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    beta = torch.tensor(beta_np, dtype=torch.float32, device=runtime.device).reshape(1, 10)
    root, body, translation = [x.clone() for x in seed]
    predictions, vertices, timings = [], [], []

    def step(target_np, measure: bool):
        nonlocal root, body, translation
        target = torch.tensor(target_np[None], dtype=torch.float32, device=runtime.device)
        if measure:
            torch.cuda.synchronize(runtime.device)
            started = time.perf_counter()
        with torch.no_grad():
            start = runtime.net.human_model.layer["neutral"](
                betas=beta, global_orient=root, body_pose=body)
            start_joints = torch.einsum("bvc,jv->bjc", start.vertices, runtime.net.openpose_regressor)
            start_normal, rotation, trans_norm = runtime.normalize_kp(
                start_joints, None, runtime.net.kp_index, R=None, T=None)
            target_normal, _, _ = runtime.normalize_kp(
                target, None, runtime.net.kp_index, R=rotation, T=trans_norm)
            network_input = torch.stack([start_normal, target_normal], 1).permute(0, 3, 1, 2)
            _, _, _, body, root = runtime.net.predict(network_input, root, body, beta)
            output = runtime.smpl(root, body, beta)
            body25 = runtime.body25(output) + translation[:, None]
            # Keep root translation aligned to the observed pelvis, as in the bridge.
            translation = translation + target[:, 8] - body25[:, 8]
            body25 = runtime.body25(output) + translation[:, None]
            mesh = output.vertices + translation[:, None]
        if measure:
            torch.cuda.synchronize(runtime.device)
            timings.append((time.perf_counter() - started) * 1000.0)
            pelvis = body25[0, 8]
            predictions.append((body25[0] - pelvis).cpu().numpy().astype(np.float32))
            vertices.append((mesh[0] - pelvis).cpu().numpy().astype(np.float32))

    step(targets[0], False)
    for target_np in targets:
        step(target_np, True)
    flags = np.ones(len(targets), dtype=bool)
    pred = np.stack(predictions)
    return {"pred": pred, "candidate": pred.copy(), "vertices": np.stack(vertices),
            "accepted": flags, "reasons": [[] for _ in targets],
            "total_ms": np.asarray(timings, np.float64)}


def method_metrics(result: dict[str, object], targets: np.ndarray) -> dict[str, object]:
    accepted = result["accepted"]
    latency = result["total_ms"]
    body = aligned_error(result["pred"], targets, BODY15)
    upper = aligned_error(result["pred"], targets, UPPER11)
    candidate = aligned_error(result["candidate"], targets, UPPER11)
    reason_names = sorted({reason for row in result["reasons"] for reason in row})
    return {
        "frames": int(len(targets)),
        "average_fps": float(1000.0 / np.mean(latency)),
        "latency_ms": statistics(latency),
        "applied_body15_residual_mm": statistics(body),
        "applied_upper11_residual_mm": statistics(upper),
        "candidate_upper11_residual_mm": statistics(candidate),
        "acceptance_rate": float(np.mean(accepted)),
        "held_frames": int(np.sum(~accepted)),
        "longest_consecutive_hold_frames": longest_false_run(accepted),
        "rejection_reasons": {reason: sum(reason in row for row in result["reasons"])
                              for reason in reason_names},
    }


def load_amass(runtime: Runtime, path: Path):
    import torch
    data = np.load(path)
    pose = data["poses"].astype(np.float32)
    trans = data["trans"].astype(np.float32)
    beta = data["betas"][:10].astype(np.float32)
    n = len(pose)
    with torch.no_grad():
        output = runtime.layer(
            betas=torch.tensor(np.repeat(beta[None], n, axis=0), device=runtime.device),
            global_orient=torch.tensor(pose[:, None, :3], device=runtime.device),
            body_pose=torch.tensor(pose[:, 3:72].reshape(n, 23, 3), device=runtime.device),
        )
        body25 = runtime.body25(output) + torch.tensor(trans, device=runtime.device)[:, None]
        pelvis = body25[:, [8]]
        target = (body25 - pelvis).cpu().numpy().astype(np.float32)
        vertices = (output.vertices + torch.tensor(trans, device=runtime.device)[:, None] - pelvis)
    return target, beta, vertices.cpu().numpy().astype(np.float32), float(data["mocap_framerate"])


def load_h3wb(path: Path) -> np.ndarray:
    data = np.load(path, allow_pickle=True)
    if "global_3d" in data.files:
        source = data["global_3d"].astype(np.float32)
    elif "train_data" in data.files:
        train_data = data["train_data"].item()
        subject = sorted(train_data)[0]
        action = sorted(train_data[subject])[0]
        source = np.asarray(train_data[subject][action]["global_3d"], dtype=np.float32)
    else:
        raise KeyError(f"unsupported H3WB archive keys: {data.files}")
    source = source[..., [0, 2, 1]]
    source[..., 2] *= -1.0
    source *= 0.001
    result = np.zeros((len(source), 25, 3), dtype=np.float32)
    result[:, 0] = source[:, 0]
    result[:, 1] = (source[:, 5] + source[:, 6]) * 0.5
    mapping = {2: 6, 3: 8, 4: 10, 5: 5, 6: 7, 7: 9,
               9: 12, 10: 14, 11: 16, 12: 11, 13: 13, 14: 15,
               15: 2, 16: 1, 17: 4, 18: 3,
               19: 17, 20: 18, 21: 19, 22: 20, 23: 21, 24: 22}
    result[:, 8] = (source[:, 11] + source[:, 12]) * 0.5
    for destination, origin in mapping.items():
        result[:, destination] = source[:, origin]
    result -= result[:, [8]]
    if not np.isfinite(result).all():
        raise ValueError("H3WB input contains non-finite coordinates")
    return result


def prepare_datasets(runtime: Runtime, args):
    import torch
    from smpl_0901.fixed_betas_fitter import estimate_fixed_betas

    datasets = {}
    run = longest_accepted_run(args.rig_b_fit)
    needed = args.calibration_frames + args.rig_b_frames
    if len(run) < needed:
        raise RuntimeError(f"Rig B requires {needed} accepted contiguous frames, found {len(run)}")
    records = run[:needed]
    all_targets = np.stack([np.asarray(row["target_body25"], np.float32) for row in records])
    calibration = torch.tensor(all_targets[:args.calibration_frames], device=runtime.device)
    beta = estimate_fixed_betas(runtime.layer, runtime.regressor, calibration,
                                iterations=100, joint_indices=UPPER11, beta_limit=3.0)
    datasets["rig_b_recording"] = {
        "targets": all_targets[args.calibration_frames:],
        "seed_target": all_targets[args.calibration_frames - 1],
        "beta": beta.cpu().numpy(),
        "frame_ids": np.asarray([int(row["frame"]) for row in records[args.calibration_frames:]]),
        "source_fps": 30.0, "ground_truth_vertices": None,
        "source": str(args.rig_b_fit.resolve()),
        "note": "longest accepted contiguous run; first calibration segment estimates fixed betas",
    }

    amass_targets, amass_beta, amass_vertices, amass_fps = load_amass(runtime, args.amass)
    amass_end = len(amass_targets) if args.amass_frames <= 0 else min(
        len(amass_targets), 1 + args.amass_frames)
    datasets["amass_clean"] = {
        "targets": amass_targets[1:amass_end], "seed_target": amass_targets[0],
        "beta": amass_beta, "frame_ids": np.arange(1, amass_end),
        "source_fps": amass_fps, "ground_truth_vertices": amass_vertices[1:amass_end],
        "source": str(args.amass.resolve()),
        "note": "known SMPL parameters converted to Body25; frame 0 is common tracker seed",
    }

    h3_targets = load_h3wb(args.h3wb)
    h3_calibration = torch.tensor(h3_targets[:args.calibration_frames], device=runtime.device)
    h3_beta = estimate_fixed_betas(runtime.layer, runtime.regressor, h3_calibration,
                                   iterations=100, joint_indices=UPPER11, beta_limit=3.0)
    h3_end = min(len(h3_targets), args.calibration_frames + args.h3wb_frames)
    datasets["h3wb"] = {
        "targets": h3_targets[args.calibration_frames:h3_end],
        "seed_target": h3_targets[args.calibration_frames - 1],
        "beta": h3_beta.cpu().numpy(),
        "frame_ids": np.arange(args.calibration_frames, h3_end),
        "source_fps": 50.0, "ground_truth_vertices": None,
        "source": str(args.h3wb.resolve()),
        "note": "H3WB global_3d converted from millimetres using proper-axis map (x,z,-y)",
    }
    return datasets


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
    parser.add_argument("--amass-frames", type=int, default=0,
                        help="0 uses every frame after the common seed")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    arrays_dir = args.output_dir / "arrays"
    arrays_dir.mkdir()

    before = gpu_snapshot()
    runtime = Runtime(args.smpl_dir, args.og_source, args.og_checkpoint, args.og_model_dir)
    datasets = prepare_datasets(runtime, args)
    report = {
        "schema": "smpl-model-lab/three-model-suite-v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "timing_scope": "batch=1 steady tracking core; includes fit/predict, reconstruction and safety gate; excludes calibration, first seed, file I/O, rendering, UDP and Unity",
        "common_protocol": {
            "three_datasets_required": True,
            "common_100_iteration_seed_excluded_from_timing": True,
            "current_gate_thresholds": {"residual_mm": 100, "twist_deg": 100,
                                        "delta_deg": 90, "facing_deg": 90},
            "gpu_contention_warning": "Other GPU compute processes are not terminated; compare methods within this run, not against historical standalone FPS.",
        },
        "models": {method.key: method.__dict__ for method in METHODS},
        "gpu_before": before,
        "og_checkpoint_sha256": sha256(args.og_checkpoint),
        "datasets": {},
    }

    for dataset_key, dataset in datasets.items():
        print(f"\n=== {dataset_key}: {len(dataset['targets'])} frames ===", flush=True)
        seed = make_seed(runtime, dataset["seed_target"],
                         runtime.torch.tensor(dataset["beta"], device=runtime.device))
        payload = {
            "target_body25": dataset["targets"], "frame_ids": dataset["frame_ids"],
            "fixed_betas": dataset["beta"], "faces": runtime.faces,
        }
        if dataset["ground_truth_vertices"] is not None:
            payload["ground_truth_vertices"] = dataset["ground_truth_vertices"]
        dataset_metrics = {}
        for method in METHODS:
            print(f"{dataset_key}: {method.key}", flush=True)
            if method.kind == "og":
                result = run_og(runtime, dataset["targets"], dataset["beta"], seed)
            else:
                result = run_fitter(runtime, dataset["targets"], dataset["beta"], seed, method)
            dataset_metrics[method.key] = method_metrics(result, dataset["targets"])
            for name in ("pred", "candidate", "vertices", "accepted", "total_ms"):
                payload[f"{method.key}_{name}"] = result[name]
            print(json.dumps(dataset_metrics[method.key], ensure_ascii=False), flush=True)
        np.savez_compressed(arrays_dir / f"{dataset_key}.npz", **payload)
        report["datasets"][dataset_key] = {
            "source": dataset["source"], "source_fps": dataset["source_fps"],
            "frames": int(len(dataset["targets"])), "note": dataset["note"],
            "metrics": dataset_metrics,
        }

    report["gpu_after"] = gpu_snapshot()
    (args.output_dir / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["datasets"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
