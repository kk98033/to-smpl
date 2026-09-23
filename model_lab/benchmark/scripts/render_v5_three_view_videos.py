#!/usr/bin/env python3
"""Render synchronized front/side/back comparisons for paper, production and v5."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import imageio.v2 as imageio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import render_three_model_suite as base


METHODS = (
    ("paper_neural_baseline", "Paper baseline", "#4D8EDB"),
    ("production_upper_body_50step", "Production field 50-step", "#42A06F"),
    ("hybrid_v5_adaptive_batched", "V5 adaptive batched", "#D05A47"),
)

DATASETS = {
    "rig_b_recording": ("Rig B recorded field replay", 1, 6),
    "amass_clean": ("AMASS clean SMPL control", 2, 12),
    "h3wb": ("H3WB whole-body joints", 3, 12),
}

# The canonical body frame used by the existing verified figures.
VIEWS = (
    ("FRONT", -76.0),
    ("SIDE", 14.0),
    ("BACK", 104.0),
)


def _metric(metrics: dict, dataset_key: str, method_key: str) -> tuple[float, float]:
    row = metrics["datasets"][dataset_key]["metrics"][method_key]
    return (
        float(row["average_fps"]),
        float(row["applied_upper11_residual_mm"]["p50"]),
    )


def _render_frame(
    dataset_key: str,
    dataset_label: str,
    data,
    metrics: dict,
    index: int,
) -> np.ndarray:
    target = data["target_body25"][index]
    target_c = base.canonical(target, target)
    frame_id = int(data["frame_ids"][index])

    fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor="#0B0F14")
    fig.suptitle(
        f"{dataset_label} | source frame {frame_id} | synchronized three-view comparison",
        color="white",
        fontsize=12.5,
        fontweight="bold",
        y=0.992,
    )

    for column, (method_key, method_label, color) in enumerate(METHODS):
        throughput_fps, residual_p50 = _metric(metrics, dataset_key, method_key)
        vertices = base.canonical(data[f"{method_key}_vertices"][index], target)
        joints = data[f"{method_key}_pred"][index]
        frame_residual = base.error(joints, target)
        accepted = bool(data[f"{method_key}_accepted"][index])
        state = "ACCEPT" if accepted else "HOLD"
        fig.text(
            (column + 0.5) / len(METHODS),
            0.942,
            f"{method_label}\n{throughput_fps:.2f} FPS | Upper11 p50 {residual_p50:.2f} mm",
            ha="center",
            va="center",
            color="white",
            fontsize=8.2,
            fontweight="bold",
        )

        for row, (view_label, azimuth) in enumerate(VIEWS):
            panel = row * len(METHODS) + column + 1
            ax = fig.add_subplot(len(VIEWS), len(METHODS), panel, projection="3d")
            base.add_mesh(ax, vertices, data["faces"], color, alpha=0.96)
            base.add_skeleton(ax, target_c, alpha=0.42)
            base.style(ax, azimuth, radius=1.12)

            title = f"{view_label} | frame {frame_residual:.1f} mm | {state}"
            ax.set_title(title, color="white", fontsize=7.5, pad=0)

    fig.text(
        0.5,
        0.017,
        "White skeleton: input Body25 | Error: pelvis-aligned Upper11 joint fitting residual "
        "(not ground-truth MPJPE) | Video playback FPS is not inference throughput",
        ha="center",
        color="#CED4DC",
        fontsize=7.5,
    )
    fig.subplots_adjust(left=0.015, right=0.985, bottom=0.045, top=0.895, wspace=0.0, hspace=0.02)
    return base.canvas_rgb(fig), fig


def render_video(
    path: Path,
    dataset_key: str,
    dataset_label: str,
    data,
    metrics: dict,
    stride: int,
    playback_fps: int,
) -> int:
    rendered = 0
    with imageio.get_writer(
        path,
        fps=playback_fps,
        codec="libx264",
        quality=8,
        macro_block_size=16,
    ) as writer:
        for index in range(0, len(data["target_body25"]), stride):
            frame, fig = _render_frame(dataset_key, dataset_label, data, metrics, index)
            writer.append_data(frame)
            plt.close(fig)
            rendered += 1
            if rendered % 20 == 0:
                print(f"  {dataset_key}: {rendered} frames", flush=True)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Default: <run_dir>/visuals/three_view_method_comparison",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=tuple(DATASETS),
        default=list(DATASETS),
        help="Datasets to render (default: all)",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else run_dir / "visuals" / "three_view_method_comparison"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

    manifest_path = output_dir / "manifest.json"
    manifest = {
        "schema": "smpl-model-lab/three-view-method-video-v1",
        "run": str(run_dir),
        "layout": {"columns": [item[1] for item in METHODS], "rows": [item[0] for item in VIEWS]},
        "error_metric": "pelvis-aligned Upper11 joint fitting residual; not ground-truth MPJPE",
        "datasets": {},
    }
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("schema") == manifest["schema"]:
            manifest["datasets"].update(previous.get("datasets", {}))

    for dataset_key in args.datasets:
        dataset_label, stride, playback_fps = DATASETS[dataset_key]
        print(f"render {dataset_key}: stride={stride}, playback={playback_fps} FPS", flush=True)
        data = np.load(run_dir / "arrays" / f"{dataset_key}.npz", allow_pickle=False)
        filename = f"{dataset_key}_paper_vs_production_vs_v5_three_views.mp4"
        frame_count = render_video(
            output_dir / filename,
            dataset_key,
            dataset_label,
            data,
            metrics,
            stride,
            playback_fps,
        )
        manifest["datasets"][dataset_key] = {
            "video": filename,
            "rendered_frames": frame_count,
            "source_frames": int(len(data["target_body25"])),
            "stride": stride,
            "playback_fps": playback_fps,
            "methods": {
                key: {
                    "label": label,
                    "average_fps": _metric(metrics, dataset_key, key)[0],
                    "upper11_residual_p50_mm": _metric(metrics, dataset_key, key)[1],
                }
                for key, label, _ in METHODS
            },
        }

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
