#!/usr/bin/env python3
"""Render OG, production, v3, v4 and final v5 on common frames."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import render_three_model_suite as renderer


renderer.METHODS = (
    ("paper_neural_baseline", "Paper neural baseline", "#4D8EDB"),
    ("production_upper_body_50step", "Production 50-step", "#42A06F"),
    ("hybrid_v3_confidence_limb_gate", "Hybrid v3 quality", "#009E9A"),
    ("hybrid_v4_fastpath", "Hybrid v4 fast", "#D58A35"),
    ("hybrid_v5_adaptive_batched", "Hybrid v5 final", "#D05A47"),
)
renderer.SUMMARY_FILENAME = "five_method_v5_summary.png"
renderer.CANDIDATE_METHODS = (
    ("hybrid_v5_adaptive_batched", "Hybrid v5 final", "#D05A47"),
)


if __name__ == "__main__":
    raise SystemExit(renderer.main())
