"""Live browser dashboard for inspecting the actual fitted SMPL surface."""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Any

import numpy as np


COCO17_EDGES = (
    (0, 1), (0, 2), (1, 3), (2, 4),
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
    (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
)

SMPL24_PARENTS = (
    -1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8,
    9, 9, 9, 12, 13, 14, 16, 17, 18, 19, 20, 21,
)
SMPL24_EDGES = tuple(
    (parent, child)
    for child, parent in enumerate(SMPL24_PARENTS)
    if parent >= 0
)


def read_last_json_record(path: Path) -> dict[str, Any] | None:
    """Read the last complete non-empty JSONL record without loading the file."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - (1 << 20)))
        lines = stream.read().splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            return json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            # The bridge may be between write() and flush(); try the prior line.
            continue
    return None


def _points(record: dict[str, Any], key: str, count: int) -> np.ndarray:
    values = record.get(key) or []
    output = np.full((count, 3), np.nan, dtype=np.float32)
    for index, row in enumerate(values[:count]):
        if row is not None and len(row) == 3:
            output[index] = np.asarray(row, dtype=np.float32)
    return output


def _line_coordinates(points: np.ndarray, edges: tuple[tuple[int, int], ...]):
    x: list[float | None] = []
    y: list[float | None] = []
    z: list[float | None] = []
    for source, target in edges:
        if source >= len(points) or target >= len(points):
            continue
        a, b = points[source], points[target]
        if not np.isfinite(a).all() or not np.isfinite(b).all():
            continue
        x.extend((float(a[0]), float(b[0]), None))
        y.extend((float(a[1]), float(b[1]), None))
        z.extend((float(a[2]), float(b[2]), None))
    return x, y, z


class SmplMeshGenerator:
    """Regenerate vertices using the exact SMPL layer used by the bridge."""

    def __init__(self, model_root: Path, device: str):
        import torch

        from .model import load_smpl_body25

        self.torch = torch
        self.device = torch.device(device)
        self.layer, _ = load_smpl_body25(model_root, self.device)
        self.layer.eval()
        self.faces = np.asarray(self.layer.faces, dtype=np.int32)
        self.lock = threading.Lock()

    def vertices(self, record: dict[str, Any]) -> np.ndarray:
        parameters = record.get("smpl_parameters")
        if not isinstance(parameters, dict):
            raise ValueError(
                "diagnostic record has no smpl_parameters; restart the updated bridge"
            )
        torch = self.torch
        betas = torch.as_tensor(
            parameters["betas"], dtype=torch.float32, device=self.device
        ).reshape(1, 10)
        root = torch.as_tensor(
            parameters["root_orient"], dtype=torch.float32, device=self.device
        ).reshape(1, 1, 3)
        body = torch.as_tensor(
            parameters["body_pose"], dtype=torch.float32, device=self.device
        ).reshape(1, 23, 3)
        translation = torch.as_tensor(
            parameters["translation"], dtype=torch.float32, device=self.device
        ).reshape(1, 1, 3)
        with self.lock, torch.inference_mode():
            output = self.layer(
                betas=betas,
                global_orient=root,
                body_pose=body,
            )
            return (output.vertices + translation)[0].detach().cpu().numpy()


class FrameCache:
    def __init__(self, path: Path, mesh: SmplMeshGenerator):
        self.path = path
        self.mesh = mesh
        self.frame_id: int | None = None
        self.record: dict[str, Any] | None = None
        self.vertices: np.ndarray | None = None
        self.error = "waiting for first fit record"

    def refresh(self) -> None:
        record = read_last_json_record(self.path)
        if record is None:
            if not self.path.exists():
                self.error = f"fit JSONL not found: {self.path}"
            return
        frame_id = int(record.get("frame", -1))
        if self.frame_id == frame_id and self.vertices is not None:
            return
        try:
            vertices = self.mesh.vertices(record)
        except Exception as exception:  # displayed in dashboard, server stays alive
            self.error = str(exception)
            return
        self.record = record
        self.vertices = vertices
        self.frame_id = frame_id
        self.error = ""


def create_mesh_figure(cache: FrameCache):
    import plotly.graph_objects as go

    record = cache.record
    vertices = cache.vertices
    figure = go.Figure()
    if record is None or vertices is None:
        figure.add_annotation(
            text=cache.error,
            showarrow=False,
            font={"color": "#ff6b6b", "size": 16},
        )
    else:
        faces = cache.mesh.faces
        figure.add_trace(go.Mesh3d(
            name="Actual fitted SMPL mesh",
            x=vertices[:, 0], y=vertices[:, 1], z=vertices[:, 2],
            i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
            color="#d9a441", opacity=0.72, flatshading=False,
            lighting={
                "ambient": 0.55, "diffuse": 0.75,
                "specular": 0.25, "roughness": 0.75,
            },
            lightposition={"x": 2, "y": 4, "z": 3},
            hoverinfo="skip",
        ))

        raw = _points(record, "target_factory59", 59)[:17]
        raw_x, raw_y, raw_z = _line_coordinates(raw, COCO17_EDGES)
        figure.add_trace(go.Scatter3d(
            name="Raw Body17",
            x=raw_x, y=raw_y, z=raw_z,
            mode="lines", line={"color": "#31d6df", "width": 6},
            hoverinfo="skip",
        ))
        figure.add_trace(go.Scatter3d(
            name="Raw joints",
            x=raw[:, 0], y=raw[:, 1], z=raw[:, 2],
            mode="markers", marker={"color": "#7ef9ff", "size": 4},
            hovertemplate="raw %{pointNumber}<extra></extra>",
        ))

        fitted = _points(record, "fitted_smpl24", 24)
        fit_x, fit_y, fit_z = _line_coordinates(fitted, SMPL24_EDGES)
        figure.add_trace(go.Scatter3d(
            name="SMPL24 kinematic joints",
            x=fit_x, y=fit_y, z=fit_z,
            mode="lines", line={"color": "#ff9f1c", "width": 5},
            hoverinfo="skip",
        ))

    figure.update_layout(
        template="plotly_dark",
        paper_bgcolor="#080d14",
        plot_bgcolor="#080d14",
        margin={"l": 0, "r": 0, "t": 8, "b": 0},
        legend={"orientation": "h", "y": 1.02, "x": 0.01},
        uirevision="keep-user-camera",
        scene={
            "aspectmode": "data",
            "xaxis": {"title": "X", "showbackground": True, "backgroundcolor": "#0e1722"},
            "yaxis": {"title": "Y (up)", "showbackground": True, "backgroundcolor": "#0e1722"},
            "zaxis": {"title": "Z", "showbackground": True, "backgroundcolor": "#0e1722"},
            "camera": {"up": {"x": 0, "y": 1, "z": 0}, "eye": {"x": 1.6, "y": 0.7, "z": 1.8}},
        },
    )
    return figure


def create_app(cache: FrameCache, interval_ms: int):
    from dash import Dash, Input, Output, dcc, html

    app = Dash(__name__)
    app.title = "SMPL 0901 Mesh Diagnostic"
    app.layout = html.Div(
        style={"background": "#080d14", "color": "#dbe7f3", "minHeight": "100vh", "padding": "14px"},
        children=[
            html.H2("SMPL 0901 — actual mesh diagnostic", style={"margin": "0 0 6px"}),
            html.Div(
                "同一 frame：RSV1 原始 Body17／SMPL24 關節／由 betas + root_orient + body_pose 真正生成的 6890 頂點 mesh",
                style={"color": "#91a4b7", "marginBottom": "8px"},
            ),
            html.Div(id="fit-status", style={"fontFamily": "monospace", "marginBottom": "6px"}),
            dcc.Graph(id="smpl-mesh-view", style={"height": "82vh"}, config={"displaylogo": False}),
            dcc.Interval(id="refresh", interval=max(100, interval_ms), n_intervals=0),
        ],
    )

    @app.callback(
        Output("smpl-mesh-view", "figure"),
        Output("fit-status", "children"),
        Input("refresh", "n_intervals"),
    )
    def update(_tick: int):
        cache.refresh()
        if cache.record is None:
            status = cache.error
        else:
            record = cache.record
            status = (
                f"frame={record.get('frame')}  profile={record.get('fit_profile')}  "
                f"MPJPE={record.get('fit_residual_mm', float('nan')):.1f} mm  "
                f"worst={record.get('worst_joint_residual_mm', float('nan')):.1f} mm  "
                f"torso={record.get('torso_orientation_deg', float('nan')):.1f} deg"
            )
            if cache.error:
                status += f"  ERROR: {cache.error}"
        return create_mesh_figure(cache), status

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-jsonl", type=Path, default=Path("artifacts/live/smpl_fit.jsonl"))
    parser.add_argument("--smpl-dir", type=Path, default=Path("models"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mesh = SmplMeshGenerator(args.smpl_dir, args.device)
    cache = FrameCache(args.fit_jsonl, mesh)
    app = create_app(cache, args.interval_ms)
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
