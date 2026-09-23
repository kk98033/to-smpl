#!/usr/bin/env python3
"""Render three-view figures, comparison charts and MP4s from suite arrays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import imageio.v2 as imageio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np


METHODS = (
    ("paper_neural_baseline", "Paper neural baseline", "#4D8EDB"),
    ("production_upper_body_50step", "Production 50-step", "#42A06F"),
    ("tuned_40step_tf32_0916", "0916 40-step TF32", "#D58A35"),
)
SUMMARY_FILENAME = "three_model_summary.png"
CANDIDATE_METHODS = (
    ("hybrid_v2_adaptive", "Hybrid v2 adaptive", "#D05A47"),
)
DATASETS = {
    "rig_b_recording": ("Rig B recorded replay", 1, 6),
    "amass_clean": ("AMASS clean SMPL control", 2, 12),
    "h3wb": ("H3WB whole-body joints", 3, 12),
}
EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 4), (1, 5), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (10, 11), (8, 12), (12, 13), (13, 14),
    (0, 15), (15, 17), (0, 16), (16, 18), (14, 19), (19, 20),
    (14, 21), (11, 22), (22, 23), (11, 24),
)
UPPER11 = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12)


def basis(target: np.ndarray) -> np.ndarray:
    vertical = target[1] - target[8]
    vertical /= max(float(np.linalg.norm(vertical)), 1e-8)
    lateral = target[5] - target[2]
    lateral -= np.dot(lateral, vertical) * vertical
    lateral /= max(float(np.linalg.norm(lateral)), 1e-8)
    forward = np.cross(lateral, vertical)
    forward /= max(float(np.linalg.norm(forward)), 1e-8)
    return np.stack((lateral, forward, vertical), axis=1)


def canonical(points: np.ndarray, target: np.ndarray) -> np.ndarray:
    centered = points - points[[8]] if len(points) == 25 else points
    return centered @ basis(target)


def error(pred: np.ndarray, target: np.ndarray) -> float:
    pred = pred - pred[[8]]
    target = target - target[[8]]
    return float(np.linalg.norm(pred[list(UPPER11)] - target[list(UPPER11)], axis=1).mean() * 1000.0)


def add_mesh(ax, vertices: np.ndarray, faces: np.ndarray, color: str, alpha: float = 0.94) -> None:
    surface = Poly3DCollection(vertices[faces], linewidths=0.0, alpha=alpha, rasterized=True)
    surface.set_facecolor(color)
    surface.set_edgecolor("none")
    ax.add_collection3d(surface)


def add_skeleton(ax, points: np.ndarray, alpha: float = 0.55) -> None:
    for start, end in EDGES:
        line = points[[start, end]]
        ax.plot(line[:, 0], line[:, 1], line[:, 2], color="#ECEFF4", lw=1.25, alpha=alpha)
    ax.scatter(points[:, 0], points[:, 1], points[:, 2], s=5, c="#ECEFF4", alpha=alpha)


def style(ax, azimuth: float, radius: float = 1.15) -> None:
    ax.view_init(elev=8, azim=azimuth)
    ax.set_xlim(-radius, radius)
    ax.set_ylim(-radius, radius)
    ax.set_zlim(-0.2, 2.1)
    ax.set_box_aspect((2, 2, 2.3))
    ax.set_axis_off()
    ax.set_facecolor("#11161C")


def average_index(data) -> int:
    target = data["target_body25"]
    rows = []
    for index in range(len(target)):
        rows.append(np.mean([error(data[f"{key}_pred"][index], target[index])
                             for key, _, _ in METHODS]))
    values = np.asarray(rows)
    return int(np.argmin(np.abs(values - values.mean())))


def three_views(path: Path, dataset_name: str, data, index: int) -> None:
    target = data["target_body25"][index]
    target_c = canonical(target, target)
    rows = list(METHODS)
    if "ground_truth_vertices" in data.files:
        rows = [("ground_truth", "Ground-truth SMPL", "#B8BDC6")] + rows
    views = (("Front", -76), ("Right", 14), ("Back", 104))
    fig = plt.figure(figsize=(12, 3.05 * len(rows)), facecolor="white")
    fig.suptitle(f"{dataset_name} — average case, index {index}", fontsize=14,
                 fontweight="bold", y=0.995)
    for row, (key, label, color) in enumerate(rows):
        if key == "ground_truth":
            vertices = data["ground_truth_vertices"][index]
            joints = target
            metric = 0.0
        else:
            vertices = data[f"{key}_vertices"][index]
            joints = data[f"{key}_pred"][index]
            metric = error(joints, target)
        vertices_c = canonical(vertices, target)
        for column, (view, azimuth) in enumerate(views):
            ax = fig.add_subplot(len(rows), 3, row * 3 + column + 1, projection="3d")
            add_mesh(ax, vertices_c, data["faces"], color)
            add_skeleton(ax, target_c)
            style(ax, azimuth)
            suffix = f" | Upper11 {metric:.1f} mm" if column == 0 and key != "ground_truth" else ""
            ax.set_title(f"{label} | {view}{suffix}", fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(path, dpi=180, facecolor="white")
    plt.close(fig)


def canvas_rgb(fig) -> np.ndarray:
    fig.canvas.draw()
    return np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()


def render_video(path: Path, dataset_name: str, data, stride: int, fps: int) -> None:
    target_all = data["target_body25"]
    rows = list(METHODS)
    if "ground_truth_vertices" in data.files:
        rows = [("ground_truth", "Ground truth", "#B8BDC6")] + rows
    with imageio.get_writer(path, fps=fps, codec="libx264", quality=8,
                            macro_block_size=16) as writer:
        for index in range(0, len(target_all), stride):
            target = target_all[index]
            target_c = canonical(target, target)
            fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor="#0B0F14")
            frame_id = int(data["frame_ids"][index])
            fig.suptitle(f"{dataset_name} | source frame {frame_id}", color="white",
                         fontsize=15, fontweight="bold", y=0.96)
            for panel, (key, label, color) in enumerate(rows):
                ax = fig.add_subplot(1, len(rows), panel + 1, projection="3d")
                if key == "ground_truth":
                    vertices, joints, metric, status = data["ground_truth_vertices"][index], target, 0.0, ""
                else:
                    vertices = data[f"{key}_vertices"][index]
                    joints = data[f"{key}_pred"][index]
                    metric = error(joints, target)
                    accepted = bool(data[f"{key}_accepted"][index])
                    status = " | ACCEPT" if accepted else " | HOLD"
                add_mesh(ax, canonical(vertices, target), data["faces"], color)
                add_skeleton(ax, target_c, alpha=0.35)
                style(ax, -76)
                metric_text = "reference" if key == "ground_truth" else f"Upper11 {metric:.1f} mm"
                ax.set_title(f"{label}{status}\n{metric_text}", color="white", fontsize=9)
            fig.text(0.5, 0.025, "White skeleton: input Body25; playback FPS is not inference FPS",
                     ha="center", color="#CED4DC", fontsize=9)
            fig.subplots_adjust(left=0.01, right=0.99, bottom=0.06, top=0.90, wspace=0.0)
            writer.append_data(canvas_rgb(fig))
            plt.close(fig)


def render_candidate_applied_video(path: Path, dataset_name: str, data,
                                   method_key: str, label: str, color: str,
                                   stride: int, fps: int) -> None:
    """Show the generated candidate separately from safety-gate playback."""
    target_all = data["target_body25"]
    with imageio.get_writer(path, fps=fps, codec="libx264", quality=8,
                            macro_block_size=16) as writer:
        for index in range(0, len(target_all), stride):
            target = target_all[index]
            target_c = canonical(target, target)
            accepted = bool(data[f"{method_key}_accepted"][index])
            panels = (
                ("Candidate before gate", data[f"{method_key}_candidate_vertices"][index],
                 data[f"{method_key}_candidate"][index]),
                ("Applied after gate", data[f"{method_key}_vertices"][index],
                 data[f"{method_key}_pred"][index]),
            )
            fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor="#0B0F14")
            frame_id = int(data["frame_ids"][index])
            state = "ACCEPT" if accepted else "HOLD PREVIOUS"
            fig.suptitle(
                f"{dataset_name} | {label} | frame {frame_id} | {state}",
                color="white", fontsize=15, fontweight="bold", y=0.96)
            for panel_index, (title, vertices, joints) in enumerate(panels):
                ax = fig.add_subplot(1, 2, panel_index + 1, projection="3d")
                add_mesh(ax, canonical(vertices, target), data["faces"], color)
                add_skeleton(ax, target_c, alpha=0.45)
                style(ax, -76)
                ax.set_title(
                    f"{title}\nUpper11 {error(joints, target):.1f} mm",
                    color="white", fontsize=11)
            fig.text(
                0.5, 0.025,
                "White skeleton: input Body25 | HOLD means output intentionally keeps the last safe pose",
                ha="center", color="#CED4DC", fontsize=9)
            fig.subplots_adjust(left=0.02, right=0.98, bottom=0.06, top=0.90, wspace=0.0)
            writer.append_data(canvas_rgb(fig))
            plt.close(fig)


def comparison_chart(path: Path, metrics: dict) -> None:
    labels = [label for _, label, _ in METHODS]
    colors = [color for _, _, color in METHODS]
    datasets = list(DATASETS)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    width = 0.8 / len(METHODS)
    x = np.arange(len(datasets))
    for method_index, (key, _, _) in enumerate(METHODS):
        fps = [metrics["datasets"][dataset]["metrics"][key]["average_fps"] for dataset in datasets]
        residual = [metrics["datasets"][dataset]["metrics"][key]["applied_upper11_residual_mm"]["p50"]
                    for dataset in datasets]
        offset = (method_index - (len(METHODS) - 1) / 2.0) * width
        axes[0].bar(x + offset, fps, width, label=labels[method_index], color=colors[method_index])
        axes[1].bar(x + offset, residual, width, label=labels[method_index], color=colors[method_index])
    names = [DATASETS[key][0].replace(" recorded replay", "").replace(" clean SMPL control", "")
             for key in datasets]
    for ax, title, ylabel in ((axes[0], "Average throughput", "FPS (higher is better)"),
                              (axes[1], "Upper11 fitting residual p50", "mm (lower is better)")):
        ax.set_xticks(x, names)
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=0.25)
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    visual_dir = run_dir / "visuals"
    visual_dir.mkdir(exist_ok=True)
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    manifest = {"schema": "smpl-model-lab/visual-manifest-v1", "datasets": {}}
    for key, (name, stride, fps) in DATASETS.items():
        data = np.load(run_dir / "arrays" / f"{key}.npz")
        index = average_index(data)
        image_name = f"{key}_average_three_views.png"
        video_name = f"{key}_mesh_comparison.mp4"
        print(f"render {key}: average={index}, video stride={stride}", flush=True)
        three_views(visual_dir / image_name, name, data, index)
        render_video(visual_dir / video_name, name, data, stride, fps)
        manifest["datasets"][key] = {
            "average_array_index": index,
            "average_source_frame": int(data["frame_ids"][index]),
            "image": image_name, "video": video_name,
            "video_stride": stride, "video_fps": fps,
        }
        for method_key, method_label, method_color in CANDIDATE_METHODS:
            candidate_key = f"{method_key}_candidate_vertices"
            if candidate_key not in data.files:
                continue
            candidate_video = f"{key}_{method_key}_candidate_vs_applied.mp4"
            render_candidate_applied_video(
                visual_dir / candidate_video, name, data,
                method_key, method_label, method_color, stride, fps)
            manifest["datasets"][key].setdefault(
                "candidate_vs_applied_videos", {})[method_key] = candidate_video
    comparison_chart(visual_dir / SUMMARY_FILENAME, metrics)
    manifest["note"] = "Video playback rate is for review only and is not model throughput."
    (visual_dir / "visual_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
