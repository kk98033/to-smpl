#!/usr/bin/env python3
"""Render the six-method Hybrid v3 experiment."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import render_three_model_suite as renderer


renderer.METHODS = (
    ("paper_neural_baseline", "Paper neural baseline", "#4D8EDB"),
    ("production_upper_body_50step", "Production 50-step", "#42A06F"),
    ("direct_joint_ik", "Direct Joint IK", "#8D6CAB"),
    ("hybrid_jointik_og", "Hybrid v1", "#D58A35"),
    ("hybrid_v2_adaptive", "Hybrid v2 adaptive", "#D05A47"),
    ("hybrid_v3_confidence_limb_gate", "Hybrid v3 regional", "#009E9A"),
)
renderer.SUMMARY_FILENAME = "six_method_summary.png"
renderer.CANDIDATE_METHODS = (
    ("hybrid_v3_confidence_limb_gate", "Hybrid v3 regional", "#009E9A"),
)


if __name__ == "__main__":
    raise SystemExit(renderer.main())
