#!/usr/bin/env python3
"""Render the exact Hand21 Unity input and a rig-independent ROM preview."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import imageio.v2 as imageio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from smpl_0901.protocol_v2 import wrist_local_hand


FINGERS = (
    ("thumb", 1, "#F59E0B"),
    ("index", 5, "#38BDF8"),
    ("middle", 9, "#34D399"),
    ("ring", 13, "#A78BFA"),
    ("pinky", 17, "#FB7185"),
)
PALM_EDGES = ((0, 1), (0, 5), (0, 9), (0, 13), (0, 17), (1, 5), (5, 9), (9, 13), (13, 17))


def clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def unity_rom_angles(direction: np.ndarray, finger_name: str, segment: int) -> tuple[float, float]:
    """Port the angle limits used by Smpl0901RawHandRetargeter.cs."""
    direction = direction / max(float(np.linalg.norm(direction)), 1e-8)
    x, y, z = map(float, direction)
    y = max(0.0001, y)
    flex = math.degrees(math.atan2(-z, y))
    abduction = math.degrees(math.atan2(x, y))
    if finger_name != "thumb":
        if segment == 0:
            flex = clamp(flex, -15.0, 90.0)
            abduction = clamp(abduction, -20.0, 20.0)
            return clamp(flex, 0.0, 85.0), clamp(abduction, -15.0, 15.0)
        max_flex = 110.0 if segment == 1 else 85.0
        flex = clamp(flex, 0.0, max_flex)
        return clamp(flex, 0.0, 100.0 if segment == 1 else 85.0), 0.0
    max_flex = (55.0, 70.0, 90.0)[segment]
    flex = clamp(flex, -10.0, max_flex)
    abduction = clamp(abduction, -35.0, 35.0)
    return clamp(flex, -5.0, (50.0, 65.0, 80.0)[segment]), clamp(abduction, -25.0, 25.0)


def rom_preview(local: np.ndarray, bases: dict[str, np.ndarray], lengths: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, list[float]]]:
    result = np.zeros((21, 3), dtype=np.float32)
    flexions: dict[str, list[float]] = {}
    for name, root, _ in FINGERS:
        result[root] = bases[name]
        cumulative_flex = 0.0
        flexions[name] = []
        for segment in range(3):
            direction = local[root + segment + 1] - local[root + segment]
            flex, abduction = unity_rom_angles(direction, name, segment)
            flexions[name].append(flex)
            cumulative_flex += flex
            f = math.radians(cumulative_flex)
            a = math.radians(abduction if segment == 0 else 0.0)
            step = np.asarray(
                [math.sin(a) * math.cos(f), math.cos(a) * math.cos(f), -math.sin(f)],
                dtype=np.float32,
            )
            result[root + segment + 1] = result[root + segment] + step * lengths[name][segment]
    return result, flexions


def draw_hand(ax, points: np.ndarray, title: str, flexions: dict[str, list[float]] | None = None) -> None:
    for start, end in PALM_EDGES:
        line = points[[start, end]]
        ax.plot(line[:, 0], line[:, 1], line[:, 2], color="#94A3B8", lw=1.2, alpha=0.7)
    for name, root, color in FINGERS:
        chain = points[root:root + 4]
        ax.plot(chain[:, 0], chain[:, 1], chain[:, 2], color=color, lw=3.0)
        ax.scatter(chain[:, 0], chain[:, 1], chain[:, 2], color=color, s=18)
    ax.scatter([0], [0], [0], color="white", s=38, edgecolors="#0B0F14")
    ax.view_init(elev=18, azim=-82)
    ax.set_xlim(-0.16, 0.16)
    ax.set_ylim(-0.04, 0.24)
    ax.set_zlim(-0.12, 0.12)
    ax.set_box_aspect((1, 1, 0.8))
    ax.set_axis_off()
    ax.set_facecolor("#101820")
    suffix = ""
    if flexions:
        labels = []
        for name in ("thumb", "index", "middle", "ring", "pinky"):
            labels.append(f"{name[0].upper()} {np.mean(flexions[name]):.0f}°")
        suffix = "\nmean flex: " + "  ".join(labels)
    ax.set_title(title + suffix, color="white", fontsize=9, pad=1)


def load_frames(path: Path, start_frame: int, count: int) -> list[dict]:
    frames: list[dict] = []
    wanted = set(range(start_frame, start_frame + count))
    for line in path.open(encoding="utf-8"):
        try:
            record = json.loads(line)
            frame = int(record["frame"])
            points = np.asarray(record["target_factory59"], dtype=np.float32)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        if frame not in wanted or points.shape != (59, 3) or not np.isfinite(points).all():
            continue
        if any(item["frame"] == frame for item in frames):
            continue
        left, _, left_ok = wrist_local_hand(points[17:38], side="left")
        right, _, right_ok = wrist_local_hand(points[38:59], side="right")
        if left_ok and right_ok:
            frames.append({
                "frame": frame,
                "timestamp_ns": int(record.get("timestamp_ns", 0)),
                "accepted": bool(record.get("accepted", True)),
                "left": left,
                "right": right,
            })
        if len(frames) == count:
            break
    frames.sort(key=lambda item: item["frame"])
    if [item["frame"] for item in frames] != list(range(start_frame, start_frame + count)):
        raise RuntimeError(f"Could not load consecutive frames {start_frame}..{start_frame + count - 1}")
    return frames


def reference_geometry(frames: list[dict], side: str) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    stacked = np.stack([item[side] for item in frames])
    bases: dict[str, np.ndarray] = {}
    lengths: dict[str, np.ndarray] = {}
    for name, root, _ in FINGERS:
        bases[name] = np.median(stacked[:, root], axis=0)
        segment_lengths = np.linalg.norm(stacked[:, root + 1:root + 4] - stacked[:, root:root + 3], axis=2)
        lengths[name] = np.clip(np.median(segment_lengths, axis=0), 0.012, 0.065)
    return bases, lengths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_jsonl", type=Path)
    parser.add_argument("output_mp4", type=Path)
    parser.add_argument("--start-frame", type=int, default=2601)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--fps", type=int, default=6)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    frames = load_frames(args.input_jsonl, args.start_frame, args.frames)
    left_bases, left_lengths = reference_geometry(frames, "left")
    right_bases, right_lengths = reference_geometry(frames, "right")
    args.output_mp4.parent.mkdir(parents=True, exist_ok=True)

    with imageio.get_writer(args.output_mp4, fps=args.fps, codec="libx264", quality=8, macro_block_size=16) as writer:
        for item in frames * max(1, args.repeat):
            left_preview, left_flex = rom_preview(item["left"], left_bases, left_lengths)
            right_preview, right_flex = rom_preview(item["right"], right_bases, right_lengths)
            fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor="#0B0F14")
            state = "BODY ACCEPT" if item["accepted"] else "BODY HOLD"
            fig.suptitle(
                f"Rig B current hand path | frame {item['frame']} | {state}",
                color="white", fontsize=14, fontweight="bold", y=0.975,
            )
            panels = (
                (item["left"], "LEFT — exact Hand21 wrist-local input", None),
                (item["right"], "RIGHT — exact Hand21 wrist-local input", None),
                (left_preview, "LEFT — Unity ROM command preview", left_flex),
                (right_preview, "RIGHT — Unity ROM command preview", right_flex),
            )
            for panel, (points, title, flexions) in enumerate(panels, start=1):
                draw_hand(fig.add_subplot(2, 2, panel, projection="3d"), points, title, flexions)
            fig.text(
                0.5, 0.018,
                "Top: exact SMV2 Hand21 data used by Unity | Bottom: rig-independent preview of the same ROM limits; not SMPL-X mesh",
                ha="center", color="#CBD5E1", fontsize=9,
            )
            fig.subplots_adjust(left=0.02, right=0.98, bottom=0.055, top=0.91, wspace=0.02, hspace=0.02)
            fig.canvas.draw()
            writer.append_data(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
            plt.close(fig)

    manifest = {
        "schema": "smpl-model-lab/hand-closeup-v1",
        "source": str(args.input_jsonl.resolve()),
        "video": args.output_mp4.name,
        "start_frame": args.start_frame,
        "end_frame": args.start_frame + args.frames - 1,
        "rendered_frames": args.frames * max(1, args.repeat),
        "unique_source_frames": args.frames,
        "repeat": max(1, args.repeat),
        "playback_fps": args.fps,
        "top_row": "exact wrist-local Hand21 sent in SMV2",
        "bottom_row": "rig-independent preview of Unity ROM angle limits",
        "limitation": "This is not a capture of the skinned Unity hand mesh and is not native SMPL-X output.",
    }
    (args.output_mp4.parent / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
