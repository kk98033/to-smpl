#!/usr/bin/env python3
"""Merge one method-only run into an existing run without rerunning GPU work."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


DATASETS = ("rig_b_recording", "amass_clean", "h3wb")
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_dir", type=Path)
    parser.add_argument("v2_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--method-key", default="hybrid_v2_adaptive")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    arrays_dir = args.output_dir / "arrays"
    arrays_dir.mkdir()

    baseline_metrics = json.loads(
        (args.baseline_dir / "metrics.json").read_text(encoding="utf-8"))
    v2_metrics = json.loads(
        (args.v2_dir / "metrics.json").read_text(encoding="utf-8"))
    merged_metrics = deepcopy(baseline_metrics)
    merged_metrics.update({
        "schema": "smpl-model-lab/merged-comparison-v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "status": "experimental; production bridge remains unchanged",
        "merge_sources": {
            "baseline": str(args.baseline_dir.resolve()),
            args.method_key: str(args.v2_dir.resolve()),
        },
        "timing_note": (
            "Each method keeps the timing from its source run. Compare accuracy and "
            "acceptance directly; compare FPS only when GPU contention was equivalent."),
    })
    merged_metrics["models"][args.method_key] = deepcopy(
        v2_metrics["models"][args.method_key])
    merged_metrics[f"gpu_{args.method_key}_before"] = v2_metrics.get("gpu_before")
    merged_metrics[f"gpu_{args.method_key}_after"] = v2_metrics.get("gpu_after")

    for dataset in DATASETS:
        with np.load(args.baseline_dir / "arrays" / f"{dataset}.npz") as base, \
                np.load(args.v2_dir / "arrays" / f"{dataset}.npz") as v2:
            for key in ("target_body25", "frame_ids", "faces"):
                if not np.array_equal(base[key], v2[key]):
                    raise ValueError(f"{dataset}: incompatible {key}")
            payload = {key: base[key] for key in base.files}
            prefix = f"{args.method_key}_"
            payload.update({key: v2[key] for key in v2.files
                            if key.startswith(prefix)})
            np.savez_compressed(arrays_dir / f"{dataset}.npz", **payload)
        merged_metrics["datasets"][dataset]["metrics"][args.method_key] = (
            deepcopy(v2_metrics["datasets"][dataset]["metrics"][args.method_key]))

    (args.output_dir / "metrics.json").write_text(
        json.dumps(merged_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
