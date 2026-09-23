#!/usr/bin/env python3
"""Render the four-method Hybrid Joint IK experiment."""

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
    ("hybrid_jointik_og", "Joint IK + OG prior", "#D58A35"),
)
renderer.SUMMARY_FILENAME = "four_method_summary.png"


if __name__ == "__main__":
    raise SystemExit(renderer.main())
