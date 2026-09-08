"""Live factory-59 joints -> 0901 SMPL -> Unity Protocol V2 bridge.

The input is one JSON object per datagram/line.  Accepted joint fields are:

* ``keypoints_3d`` or dt-pose v1 ``joints``: a [59, 3] array in factory order (body17, LH21, RH21)
* ``keypoint_3d``: a mapping keyed by COCO-WholeBody ids
  (0..16, 91..111, 112..132)

Sources may be JSONL, the legacy metadata+frames JSON, NPZ, stdin, Unix
datagrams, or UDP datagrams. This service deliberately sits after the
teammate's 3-D predictor. It does not receive the CUDA image IPC streams;
those belong to dt-pose's upstream transport/inference service.
"""

from __future__ import annotations

import argparse
import inspect
import json
import socket
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from scipy.spatial.transform import Rotation

# Python 3.11+ removed inspect.getargspec, which chumpy 0.70 still imports.
if not hasattr(inspect, "getargspec"):
    inspect.getargspec = inspect.getfullargspec  # type: ignore[attr-defined]

# chumpy (used by the bundled SMPL code) still references removed numpy aliases.
for _name, _value in {
    "bool": bool, "int": int, "float": float, "complex": complex,
    "object": object, "unicode": str, "str": str,
}.items():
    if _name not in np.__dict__:
        setattr(np, _name, _value)

PACKAGE_DIR = Path(__file__).resolve().parent
RELEASE_ROOT = PACKAGE_DIR.parent

FACTORY_IDS = tuple(range(17)) + tuple(range(91, 133))

# Body25 0..14 covers nose, neck, arms, pelvis, hips, knees and ankles. In the
# factory footage the lower body is often occluded, so the upper-body profile
# keeps MidHip plus both hips (8, 9, 12), but excludes knees and ankles. Lower SMPL pose slots are frozen at their
# previous value instead of chasing hallucinated knees and ankles.
FIT_PROFILES = {
    "full": tuple(range(15)),
    "upper-body": tuple(range(10)) + (12,),
}
LOWER_BODY_SMPL_POSE_INDICES = (0, 1, 3, 4, 6, 7, 9, 10)


@dataclass(frozen=True)
class JointFrame:
    frame_id: int
    timestamp: float
    joints: np.ndarray  # [59,3], meters, SMPL axes
    confidence: np.ndarray  # [59]
    raw_joints: np.ndarray  # [59,3], original input unit and coordinate frame
    input_unit: str
    coordinate_frame: str
    ptp_epoch_ns: int
    ptp_exact: bool


class CalibrationPending(RuntimeError):
    """Normal startup state while the fixed-beta window is being collected."""


class UnsafeFit(RuntimeError):
    """Candidate pose exceeded a safety threshold and must not reach Unity."""

    def __init__(self, diagnostic: dict[str, object]) -> None:
        self.diagnostic = diagnostic
        super().__init__(", ".join(diagnostic["reasons"]))


def parse_axis_map(spec: str) -> tuple[tuple[int, float], ...]:
    """Parse e.g. ``x,-y,z`` or ``y,z,x`` into a signed permutation."""
    axes = {"x": 0, "y": 1, "z": 2}
    tokens = [item.strip().lower() for item in spec.split(",")]
    if len(tokens) != 3:
        raise ValueError("axis map must contain three comma-separated axes")
    result: list[tuple[int, float]] = []
    used: set[int] = set()
    for token in tokens:
        sign = -1.0 if token.startswith("-") else 1.0
        name = token.lstrip("+-")
        if name not in axes or axes[name] in used:
            raise ValueError(f"axis map must be a signed x/y/z permutation, got {spec!r}")
        used.add(axes[name])
        result.append((axes[name], sign))
    return tuple(result)


def _ordered_joints(record: dict) -> np.ndarray:
    raw = record.get("keypoints_3d", record.get("points_3d", record.get("joints")))
    if raw is not None:
        if isinstance(raw, list):
            raw = [[float("nan")] * 3 if joint is None else joint for joint in raw]
        points = np.asarray(raw, dtype=np.float32)
        if points.shape == (133, 3):
            points = points[np.asarray(FACTORY_IDS)]
        if points.shape != (59, 3):
            raise ValueError(f"joint array must have shape [59,3] (or [133,3]), got {points.shape}")
        return points

    raw_map = record.get("keypoint_3d")
    if not isinstance(raw_map, dict):
        raise ValueError("missing keypoints_3d/points_3d/joints [59,3] or keypoint_3d mapping")
    missing = [joint_id for joint_id in FACTORY_IDS if str(joint_id) not in raw_map and joint_id not in raw_map]
    if missing:
        raise ValueError(f"keypoint_3d is missing COCO-WholeBody ids {missing[:8]}")
    return np.asarray(
        [raw_map.get(str(joint_id), raw_map.get(joint_id)) for joint_id in FACTORY_IDS],
        dtype=np.float32,
    )


def _confidence(record: dict) -> np.ndarray:
    values = np.ones(59, dtype=np.float32)
    reliable = record.get("reliable")
    if isinstance(reliable, dict):
        values = np.asarray(
            [float(bool(reliable.get(str(i), reliable.get(i, False)))) for i in FACTORY_IDS],
            dtype=np.float32,
        )
    elif reliable is not None:
        candidate = np.asarray(reliable, dtype=np.float32).reshape(-1)
        if candidate.size == 59:
            values = candidate
    # main_predict JSONL does not currently carry `reliable`, but it does carry
    # one reprojection residual per joint. Mirror its production 120 px gate.
    elif record.get("reprojection_errors_px", record.get("reproj_px")) is not None:
        errors = np.asarray(
            record.get("reprojection_errors_px", record.get("reproj_px")),
            dtype=np.float32,
        ).reshape(-1)
        if errors.size == 59:
            values = (np.isfinite(errors) & (errors <= 120.0)).astype(np.float32)
    return np.clip(values, 0.0, 1.0)


def parse_joint_frame(record: dict, *, units: str, axis_map: str, fallback_id: int) -> JointFrame:
    schema = record.get("schema")
    supported_schemas = (None, "factory_59pt_body_hands", "dt-pose.pose3d/v1")
    if schema not in supported_schemas:
        raise ValueError(
            f"unsupported schema {schema!r}; expected factory_59pt_body_hands "
            "or dt-pose.pose3d/v1"
        )
    if schema == "dt-pose.pose3d/v1":
        layout = record.get("layout")
        if layout != "factory59":
            raise ValueError(
                f"dt-pose.pose3d/v1 layout must be factory59, got {layout!r}"
            )
    points = _ordered_joints(record)
    raw_points = points.copy()
    confidence = _confidence(record)
    confidence[~np.isfinite(points).all(axis=1)] = 0.0
    if units == "auto":
        # factory_59pt_dlt_demo's JSONL/NPZ contract is calibration-world mm.
        # dt-pose.pose3d/v1 declares metres in `units`; legacy records declare
        # `_input_units` or retain their historical mm default.
        units = str(record.get("units", record.get("_input_units", "mm"))).lower()
    if units not in ("m", "mm"):
        raise ValueError(f"input units must be m or mm, got {units!r}")
    scale = 0.001 if units == "mm" else 1.0
    points = points * scale
    mapping = parse_axis_map(axis_map)
    points = np.stack([points[:, index] * sign for index, sign in mapping], axis=1)
    frame_id = int(record.get(
        "frame_id", record.get(
            "frame_index", record.get("frameId", record.get("frame", fallback_id))
        )
    ))
    raw_ptp = record.get("ptp_epoch_ns", record.get("timestamp_ns"))
    fallback_timestamp = (
        int(raw_ptp) / 1_000_000_000.0 if raw_ptp is not None else time.time()
    )
    timestamp = float(record.get(
        "timestamp", record.get("timestamp_s", fallback_timestamp)
    ))
    ptp_exact = raw_ptp is not None
    ptp_epoch_ns = (
        int(raw_ptp) if ptp_exact else int(round(timestamp * 1_000_000_000.0))
    )
    coordinate_frame = str(record.get("coordinate_frame", "unknown"))
    return JointFrame(
        frame_id, timestamp, points.astype(np.float32), confidence,
        raw_points.astype(np.float32), units, coordinate_frame, ptp_epoch_ns, ptp_exact,
    )


def body25_from_factory59(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map COCO body17 to OpenPose Body25; return body and both Hand21 arrays."""
    source = np.asarray(points, dtype=np.float32)
    if source.shape != (59, 3):
        raise ValueError(f"expected [59,3], got {source.shape}")
    body = source[:17]
    output = np.zeros((25, 3), dtype=np.float32)
    output[0] = body[0]
    output[1] = (body[5] + body[6]) * 0.5
    output[2], output[3], output[4] = body[6], body[8], body[10]
    output[5], output[6], output[7] = body[5], body[7], body[9]
    output[8] = (body[11] + body[12]) * 0.5
    output[9], output[10], output[11] = body[12], body[14], body[16]
    output[12], output[13], output[14] = body[11], body[13], body[15]
    output[15:19] = body[0]
    output[19:22] = body[15]
    output[22:25] = body[16]
    return output, source[17:38].copy(), source[38:59].copy()


def body25_confidence_from_factory59(confidence: np.ndarray) -> np.ndarray:
    """Map factory COCO-17 confidence to the Body25 joints used by the fitter."""
    source = np.asarray(confidence, dtype=np.float32).reshape(-1)
    if source.shape != (59,):
        raise ValueError(f"expected confidence [59], got {source.shape}")
    body = source[:17]
    output = np.zeros(25, dtype=np.float32)
    output[0] = body[0]
    output[1] = min(body[5], body[6])
    output[2], output[3], output[4] = body[6], body[8], body[10]
    output[5], output[6], output[7] = body[5], body[7], body[9]
    output[8] = min(body[11], body[12])
    output[9], output[10], output[11] = body[12], body[14], body[16]
    output[12], output[13], output[14] = body[11], body[13], body[15]
    return np.clip(output, 0.0, 1.0)


def _json_points(points: np.ndarray) -> list[list[float] | None]:
    values = np.asarray(points, dtype=np.float32)
    return [row.tolist() if np.isfinite(row).all() else None for row in values]


SMPL24_JOINT_NAMES = (
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee",
    "right_knee", "spine2", "left_ankle", "right_ankle", "spine3",
    "left_foot", "right_foot", "neck", "left_collar", "right_collar",
    "head", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand",
)
BODY25_JOINT_NAMES = (
    "nose", "neck", "right_shoulder", "right_elbow", "right_wrist",
    "left_shoulder", "left_elbow", "left_wrist", "mid_hip", "right_hip",
    "right_knee", "right_ankle", "left_hip", "left_knee", "left_ankle",
    "right_eye", "left_eye", "right_ear", "left_ear", "left_big_toe",
    "left_small_toe", "left_heel", "right_big_toe", "right_small_toe",
    "right_heel",
)
SMPL_PRIMARY_CHILD = {
    1: 4, 2: 5, 3: 6, 4: 7, 5: 8, 6: 9, 7: 10, 8: 11,
    9: 12, 12: 15, 13: 16, 14: 17, 16: 18, 17: 19,
    18: 20, 19: 21, 20: 22, 21: 23,
}


def pose_rotation_diagnostics(
    root_rotvec: np.ndarray,
    body_rotvec: np.ndarray,
    rest_joints: np.ndarray,
    previous_root: np.ndarray | None = None,
    previous_body: np.ndarray | None = None,
) -> dict[str, object]:
    """Report local rotation magnitude, axial twist, and frame-to-frame jump."""
    current = np.concatenate(
        [np.asarray(root_rotvec, dtype=np.float64).reshape(1, 3),
         np.asarray(body_rotvec, dtype=np.float64).reshape(23, 3)]
    )
    rotation_deg = np.degrees(Rotation.from_rotvec(current).magnitude())
    twist_deg: list[float | None] = [None] * 24
    rest = np.asarray(rest_joints, dtype=np.float64)
    quaternions = Rotation.from_rotvec(current).as_quat()
    for joint, child in SMPL_PRIMARY_CHILD.items():
        axis = rest[child] - rest[joint]
        norm = np.linalg.norm(axis)
        if norm < 1e-8:
            continue
        axis /= norm
        quat = quaternions[joint]
        signed = float(np.dot(quat[:3], axis))
        angle = 2.0 * np.arctan2(signed, float(quat[3]))
        angle = (angle + np.pi) % (2.0 * np.pi) - np.pi
        twist_deg[joint] = abs(float(np.degrees(angle)))

    delta_deg: list[float | None] = [None] * 24
    if previous_root is not None and previous_body is not None:
        previous = np.concatenate(
            [np.asarray(previous_root, dtype=np.float64).reshape(1, 3),
             np.asarray(previous_body, dtype=np.float64).reshape(23, 3)]
        )
        delta = Rotation.from_rotvec(previous).inv() * Rotation.from_rotvec(current)
        delta_deg = np.degrees(delta.magnitude()).tolist()

    def worst(
        values: list[float | None] | np.ndarray, *, include_root: bool = True
    ) -> dict[str, object] | None:
        finite = [(index, float(value)) for index, value in enumerate(values)
                  if (include_root or index != 0)
                  and value is not None and np.isfinite(value)]
        if not finite:
            return None
        index, value = max(finite, key=lambda item: item[1])
        return {"index": index, "joint": SMPL24_JOINT_NAMES[index], "deg": value}

    warnings = []
    for index, name in enumerate(SMPL24_JOINT_NAMES):
        reasons = []
        if index != 0 and rotation_deg[index] > 120.0:
            reasons.append("rotation")
        if twist_deg[index] is not None and twist_deg[index] > 75.0:
            reasons.append("twist")
        if delta_deg[index] is not None and delta_deg[index] > 45.0:
            reasons.append("temporal_jump")
        if reasons:
            warnings.append({"index": index, "joint": name, "reasons": reasons})

    return {
        "joint_names": list(SMPL24_JOINT_NAMES),
        "root_rotation_deg": float(rotation_deg[0]),
        "rotation_deg": rotation_deg.tolist(),
        "twist_deg": twist_deg,
        "delta_deg": delta_deg,
        "worst_rotation": worst(rotation_deg, include_root=False),
        "worst_twist": worst(twist_deg),
        "worst_delta": worst(delta_deg),
        "warning_joints": warnings,
        "thresholds_deg": {"rotation": 120.0, "twist": 75.0, "delta": 45.0},
    }


def body_facing_mismatch_deg(body25: np.ndarray, smpl24: np.ndarray) -> float | None:
    """Horizontal angle between observed torso facing and SMPL feet.

    This assumes the input was converted using a proper (determinant +1) axis map.
    """
    body = np.asarray(body25, dtype=np.float64)
    joints = np.asarray(smpl24, dtype=np.float64)
    if body.shape != (25, 3) or joints.shape != (24, 3):
        raise ValueError("facing diagnostic expects Body25 [25,3] and SMPL24 [24,3]")
    torso = np.cross(body[5] - body[2], (body[2] + body[5]) * 0.5 - body[8])
    feet = ((joints[10] - joints[7]) + (joints[11] - joints[8])) * 0.5
    torso[1] = 0.0
    feet[1] = 0.0
    denominator = float(np.linalg.norm(torso) * np.linalg.norm(feet))
    if denominator < 1e-8:
        return None
    cosine = float(np.clip(np.dot(torso, feet) / denominator, -1.0, 1.0))
    return float(np.degrees(np.arccos(cosine)))


def unsafe_fit_reasons(
    residual_mm: float,
    pose_diagnostics: dict[str, object],
    *,
    max_residual_mm: float,
    max_twist_deg: float,
    max_delta_deg: float,
    facing_mismatch_deg: float | None = None,
    max_facing_mismatch_deg: float = 0.0,
) -> list[str]:
    """Return machine-readable reasons for holding a pathological candidate."""
    reasons: list[str] = []
    if max_residual_mm > 0 and residual_mm > max_residual_mm:
        reasons.append(f"fit_residual>{max_residual_mm:g}mm")
    worst_twist = pose_diagnostics.get("worst_twist")
    if (
        max_twist_deg > 0
        and isinstance(worst_twist, dict)
        and float(worst_twist["deg"]) > max_twist_deg
    ):
        reasons.append(f"twist>{max_twist_deg:g}deg")
    worst_delta = pose_diagnostics.get("worst_delta")
    if (
        max_delta_deg > 0
        and isinstance(worst_delta, dict)
        and float(worst_delta["deg"]) > max_delta_deg
    ):
        reasons.append(f"delta>{max_delta_deg:g}deg")
    if (
        max_facing_mismatch_deg > 0
        and facing_mismatch_deg is not None
        and facing_mismatch_deg > max_facing_mismatch_deg
    ):
        reasons.append(f"facing_mismatch>{max_facing_mismatch_deg:g}deg")
    return reasons


def compact_mesh_preview_topology(
    vertices: np.ndarray, faces: np.ndarray, max_faces: int
) -> tuple[np.ndarray, np.ndarray]:
    """Build a connected lightweight mesh with vertex-cluster decimation."""
    template = np.asarray(vertices, dtype=np.float32)
    source = np.asarray(faces, dtype=np.int32)
    if template.ndim != 2 or template.shape[1] != 3:
        raise ValueError(f"SMPL vertices must have shape [V,3], got {template.shape}")
    if source.ndim != 2 or source.shape[1] != 3:
        raise ValueError(f"SMPL faces must have shape [F,3], got {source.shape}")
    if max_faces <= 0:
        raise ValueError("mesh preview face count must be positive")
    if source.min() < 0 or source.max() >= len(template):
        raise ValueError("SMPL face index is outside the vertex array")

    lower = template.min(axis=0)
    extent = np.maximum(template.max(axis=0) - lower, 1e-6)
    best: tuple[np.ndarray, np.ndarray] | None = None
    best_count = -1
    for resolution in range(2, 65):
        cells = np.floor((template - lower) / extent * resolution).astype(np.int32)
        _, representative, inverse = np.unique(
            cells, axis=0, return_index=True, return_inverse=True
        )
        mapped = inverse[source]
        mapped = mapped[
            (mapped[:, 0] != mapped[:, 1])
            & (mapped[:, 1] != mapped[:, 2])
            & (mapped[:, 0] != mapped[:, 2])
        ]
        if not len(mapped):
            continue
        _, unique_rows = np.unique(np.sort(mapped, axis=1), axis=0, return_index=True)
        mapped = mapped[np.sort(unique_rows)]
        if len(mapped) <= max_faces and len(mapped) > best_count:
            used, compact = np.unique(mapped.reshape(-1), return_inverse=True)
            best = (
                representative[used].astype(np.int32),
                compact.reshape(-1, 3).astype(np.int32),
            )
            best_count = len(mapped)

    if best is None:
        raise ValueError("could not build a non-empty SMPL mesh preview")
    return best


def write_json_atomic(path: Path, record: dict[str, object]) -> None:
    """Replace a latest-only JSON snapshot without exposing partial writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def iter_json_records(uri: str, *, max_datagram: int = 1 << 20) -> Iterator[dict]:
    """Yield records from sockets, stdin, main_predict JSON/JSONL, or NPZ."""
    if uri == "stdin://":
        for line in sys.stdin:
            if line.strip():
                yield json.loads(line)
        return
    if uri.startswith("jsonl://"):
        path = Path(uri[len("jsonl://"):])
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)
        return
    if uri.startswith("json://"):
        path = Path(uri[len("json://"):])
        container = json.loads(path.read_text(encoding="utf-8"))
        metadata = container.get("metadata", {}) if isinstance(container, dict) else {}
        input_units = metadata.get("unit") if isinstance(metadata, dict) else None
        frames = container.get("frames", container) if isinstance(container, dict) else container
        if isinstance(frames, dict):
            ordered = sorted(frames.items(), key=lambda item: int(item[0]))
            records = []
            for frame_id, value in ordered:
                record = dict(value)
                record.setdefault("frame_id", int(frame_id))
                records.append(record)
        elif isinstance(frames, list):
            records = frames
        else:
            records = [container]
        for value in records:
            record = dict(value)
            if input_units:
                record["_input_units"] = input_units
            yield record
        return
    if uri.startswith("npz://"):
        path = Path(uri[len("npz://"):])
        with np.load(path, allow_pickle=False) as data:
            key = "keypoints_3d_smoothed" if "keypoints_3d_smoothed" in data else "keypoints_3d"
            points = np.asarray(data[key])
            reproj = np.asarray(data["reprojection_errors_px"]) if "reprojection_errors_px" in data else None
            view_counts = np.asarray(data["triangulation_view_counts"]) if "triangulation_view_counts" in data else None
            for index, joints in enumerate(points):
                record = {
                    "frame_index": index,
                    "schema": "factory_59pt_body_hands",
                    "keypoints_3d": joints.tolist(),
                }
                if reproj is not None:
                    record["reprojection_errors_px"] = reproj[index].tolist()
                if view_counts is not None:
                    record["reliable"] = (
                        np.isfinite(joints).all(axis=1)
                        & (view_counts[index] >= 2)
                        & (np.isfinite(reproj[index]) & (reproj[index] <= 120.0) if reproj is not None else True)
                    ).tolist()
                yield record
        return
    if uri.startswith("udp://"):
        host_port = uri[len("udp://"):]
        host, port_text = host_port.rsplit(":", 1)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((host, int(port_text)))
            while True:
                payload, _ = receiver.recvfrom(max_datagram)
                # Fitting may be slower than the camera. Discard queued stale
                # poses and process the newest complete datagram available.
                receiver.setblocking(False)
                try:
                    while True:
                        payload, _ = receiver.recvfrom(max_datagram)
                except BlockingIOError:
                    pass
                finally:
                    receiver.setblocking(True)
                yield json.loads(payload.decode("utf-8"))
    elif uri.startswith("unix://"):
        path = Path(uri[len("unix://"):])
        if path.exists():
            mode = path.stat().st_mode
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(f"refusing to replace non-socket path: {path}")
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            receiver.bind(str(path))
            while True:
                payload = receiver.recv(max_datagram)
                receiver.setblocking(False)
                try:
                    while True:
                        payload = receiver.recv(max_datagram)
                except BlockingIOError:
                    pass
                finally:
                    receiver.setblocking(True)
                yield json.loads(payload.decode("utf-8"))
        finally:
            receiver.close()
            if path.exists() and stat.S_ISSOCK(path.stat().st_mode):
                path.unlink()
    else:
        raise ValueError(
            "input URI must start with unix://, udp://, json://, jsonl://, npz://, or be stdin://"
        )


def default_smpl_dir() -> Path:
    return RELEASE_ROOT / "models"


class Smpl0901Bridge:
    def __init__(self, args: argparse.Namespace) -> None:
        import torch
        from .model import load_smpl_body25

        self.torch = torch
        self.args = args
        self.device = torch.device(args.device)
        self.smpl_layer, self.regressor = load_smpl_body25(args.smpl_dir, self.device)
        with torch.no_grad():
            self.rest_joints = (
                self.smpl_layer.J_regressor @ self.smpl_layer.v_template
            ).detach().cpu().numpy()
        self.fixed_betas = None
        self.calibration: list[np.ndarray] = []
        self.prev_root = None
        self.prev_body = None
        self.prev_translation = None
        self.pelvis_anchor = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.raw_destination = (
            args.raw_skeleton_host or args.unity_host, args.raw_skeleton_port
        ) if args.raw_skeleton_port else None
        self.last_fit_record: dict[str, object] | None = None
        self.last_mesh_record: dict[str, object] | None = None
        self.mesh_vertex_indices: np.ndarray | None = None
        self.mesh_vertex_indices_torch = None
        self.mesh_faces: np.ndarray | None = None
        self.mesh_face_joints: np.ndarray | None = None
        if args.mesh_preview_json is not None:
            vertex_indices, compact_faces = compact_mesh_preview_topology(
                self.smpl_layer.v_template.detach().cpu().numpy(),
                np.asarray(self.smpl_layer.faces),
                args.mesh_preview_faces,
            )
            self.mesh_vertex_indices = vertex_indices
            self.mesh_vertex_indices_torch = torch.tensor(
                vertex_indices, dtype=torch.long, device=self.device
            )
            self.mesh_faces = compact_faces
            compact_weights = (
                self.smpl_layer.lbs_weights[self.mesh_vertex_indices_torch]
                .detach().cpu().numpy()
            )
            self.mesh_face_joints = np.argmax(
                compact_weights[compact_faces].mean(axis=1), axis=1
            ).astype(np.int32)

    def close(self) -> None:
        self.sock.close()

    def _calibrate(self) -> None:
        from .fixed_betas_fitter import estimate_fixed_betas

        target = self.torch.tensor(np.stack(self.calibration), dtype=self.torch.float32, device=self.device)
        self.fixed_betas = estimate_fixed_betas(
            self.smpl_layer, self.regressor, target,
            iterations=self.args.calibration_iterations,
            joint_indices=FIT_PROFILES[self.args.fit_profile],
            beta_limit=self.args.beta_limit,
        )
        print(f"[bridge] calibration complete; fixed betas={self.fixed_betas.cpu().numpy().round(3).tolist()}")

    def process(self, frame: JointFrame) -> tuple[bytes, float]:
        from .fixed_betas_fitter import fit_fixed_betas_soft_target
        from .frame0_initializer import analytical_root_seed
        from .protocol_v2 import wrist_local_hand
        from .protocol_v2_udp import pack_protocol_v2_frame

        body25, left_hand, right_hand = body25_from_factory59(frame.joints)
        body25_conf = body25_confidence_from_factory59(frame.confidence)
        selected = FIT_PROFILES[self.args.fit_profile]
        if (
            not np.isfinite(body25[list(selected)]).all()
            or not np.all(body25_conf[list(selected)] >= self.args.min_confidence)
        ):
            raise ValueError(
                f"{self.args.fit_profile} input is incomplete/non-finite; "
                "holding the last Unity pose"
            )

        pelvis_world = body25[8].copy()
        if self.pelvis_anchor is None:
            self.pelvis_anchor = pelvis_world.copy()
        anchored_root = pelvis_world - self.pelvis_anchor
        target_np = body25 - pelvis_world
        if self.fixed_betas is None:
            self.calibration.append(target_np)
            if len(self.calibration) < self.args.calibration_frames:
                raise CalibrationPending(
                    f"calibrating {len(self.calibration)}/{self.args.calibration_frames}"
                )
            self._calibrate()

        if self.prev_root is None:
            root_np = analytical_root_seed(target_np)
            init_root = self.torch.tensor(root_np[None], dtype=self.torch.float32, device=self.device)
        else:
            init_root = self.prev_root
        target = self.torch.tensor(target_np[None], dtype=self.torch.float32, device=self.device)
        previous_root_np = (
            None if self.prev_root is None
            else self.prev_root[0].detach().cpu().numpy()
        )
        previous_body_np = (
            None if self.prev_body is None
            else self.prev_body[0].detach().cpu().numpy()
        )
        result = fit_fixed_betas_soft_target(
            self.smpl_layer,
            self.regressor,
            target,
            self.fixed_betas,
            init_root,
            init_body=self.prev_body,
            init_translation=self.prev_translation,
            iterations=self.args.iterations,
            joint_indices=selected,
            endpoint_weight=self.args.endpoint_weight,
            torso_normal_weight=self.args.torso_weight,
            body_facing_weight=self.args.body_facing_weight,
            temporal_smooth_weight=self.args.temporal_weight,
            prev_body_pose=self.prev_body,
            use_huber=self.args.robust_huber,
            joint_weights=self.torch.tensor(
                body25_conf[None], dtype=self.torch.float32, device=self.device
            ),
            frozen_pose_indices=(
                LOWER_BODY_SMPL_POSE_INDICES
                if self.args.fit_profile == "upper-body" else ()
            ),
        )
        pose = np.zeros(156, dtype=np.float32)
        root = result.root_orient[0].cpu().numpy()
        body = result.body_pose[0].reshape(23, 3).cpu().numpy()
        pose_diagnostics = pose_rotation_diagnostics(
            root, body, self.rest_joints, previous_root_np, previous_body_np
        )
        pose[:3] = root
        pose[3:66] = body[:21].reshape(-1)

        left_local, left_conf, left_ok = wrist_local_hand(
            left_hand, frame.confidence[17:38], side="left"
        )
        right_local, right_conf, right_ok = wrist_local_hand(
            right_hand, frame.confidence[38:59], side="right"
        )
        pred_body25 = result.pred_body25[0].cpu().numpy()
        pred_smpl24 = result.pred_smpl24[0].cpu().numpy()
        residuals = np.full(25, np.nan, dtype=np.float32)
        residuals[list(selected)] = (
            np.linalg.norm(pred_body25[list(selected)] - target_np[list(selected)], axis=1)
            * 1000.0
        )
        residual = float(result.residual_mm[0].cpu())
        worst_target_index = max(
            selected, key=lambda index: float(residuals[index])
        )
        worst_target_joint = {
            "index": int(worst_target_index),
            "joint": BODY25_JOINT_NAMES[worst_target_index],
            "mm": float(residuals[worst_target_index]),
        }
        torso_deg = float(result.torso_orientation_deg[0].cpu())
        facing_mismatch_deg = body_facing_mismatch_deg(target_np, pred_smpl24)
        safety_reasons = unsafe_fit_reasons(
            residual,
            pose_diagnostics,
            max_residual_mm=self.args.max_fit_residual_mm,
            max_twist_deg=self.args.max_twist_deg,
            max_delta_deg=self.args.max_delta_deg,
            facing_mismatch_deg=facing_mismatch_deg,
            max_facing_mismatch_deg=self.args.max_facing_mismatch_deg,
        )
        input_score = float(np.mean(frame.confidence))
        packet_frame = {
            "protocolVersion": 2,
            "frameId": frame.frame_id,
            "body": {
                # RootMotionDriver expects displacement from the stream's first
                # valid pelvis, not an absolute camera/world coordinate.
                "rootPosition": anchored_root.tolist(),
                "pelvisWorld": pelvis_world.tolist(),
                "rootRotation": Rotation.from_rotvec(root).as_quat().astype(np.float32).tolist(),
                "rootConfidence": float(np.mean(body25_conf[list(selected)])),
                "pose": pose.tolist(),
            },
            "hands": {
                "leftLocalJoints": left_local.reshape(-1).tolist(),
                "leftConfidence": (left_conf if left_ok else np.zeros(21)).tolist(),
                "rightLocalJoints": right_local.reshape(-1).tolist(),
                "rightConfidence": (right_conf if right_ok else np.zeros(21)).tolist(),
            },
            "quality": {
                "inputValid": True,
                "inputScore": input_score,
                "fitResidualMm": residual,
                "worstJointResidualMm": float(np.nanmax(residuals)),
                "torsoOrientationDeg": torso_deg,
                "solverState": "TRACKING" if residual < 50.0 and torso_deg < 10.0 else "RECOVERED",
                "stepsUsed": self.args.iterations,
                "reasons": [],
            },
        }
        factory59_relative = frame.joints - pelvis_world
        self.last_fit_record = {
            "schema": "smpl-0901.fit/v1",
            "frame": frame.frame_id,
            "timestamp_ns": frame.ptp_epoch_ns,
            "accepted": not bool(safety_reasons),
            "action": "hold_previous" if safety_reasons else "send",
            "reasons": safety_reasons,
            "units": "m",
            "coordinate_frame": "smpl_axes_pelvis_relative",
            "axis_map": self.args.axis_map,
            "fit_profile": self.args.fit_profile,
            "solver": {
                "endpoint_weight": self.args.endpoint_weight,
                "torso_weight": self.args.torso_weight,
                "body_facing_weight": self.args.body_facing_weight,
                "temporal_weight": self.args.temporal_weight,
                "robust_huber": self.args.robust_huber,
            },
            "selected_body25_joints": list(selected),
            "target_factory59": _json_points(factory59_relative),
            "target_body25": _json_points(target_np),
            "fitted_body25": _json_points(pred_body25),
            "fitted_smpl24": _json_points(pred_smpl24),
            "joint_residual_mm": [
                None if not np.isfinite(value) else float(value) for value in residuals
            ],
            "fit_residual_mm": residual,
            "worst_joint_residual_mm": float(np.nanmax(residuals)),
            "torso_orientation_deg": torso_deg,
            "fit_elapsed_ms": result.elapsed_seconds * 1000.0,
            "fit_iterations": result.iterations,
            "body_facing_mismatch_deg": facing_mismatch_deg,
            "worst_target_joint": worst_target_joint,
            "pose_diagnostics": pose_diagnostics,
            "fixed_betas": self.fixed_betas.cpu().numpy().tolist(),
        }
        if self.mesh_vertex_indices_torch is not None and self.mesh_faces is not None:
            preview_vertices = (
                result.pred_vertices[0]
                .index_select(0, self.mesh_vertex_indices_torch)
                .cpu()
                .numpy()
            )
            self.last_mesh_record = {
                "schema": "smpl-0901.mesh-preview/v1",
                "frame": frame.frame_id,
                "timestamp_ns": frame.ptp_epoch_ns,
                "accepted": not bool(safety_reasons),
                "units": "m",
                "coordinate_frame": "smpl_axes_pelvis_relative",
                "fit_profile": self.args.fit_profile,
                "source_vertex_count": int(result.pred_vertices.shape[1]),
                "vertices": _json_points(preview_vertices),
                "faces": self.mesh_faces.tolist(),
                "face_joint": self.mesh_face_joints.tolist(),
            }
        if safety_reasons:
            raise UnsafeFit({
                "schema": "smpl-0901.distortion-log/v1",
                "frame": frame.frame_id,
                "timestamp_ns": frame.ptp_epoch_ns,
                "accepted": False,
                "action": "hold_previous",
                "reasons": safety_reasons,
                "fit_residual_mm": residual,
                "torso_orientation_deg": torso_deg,
                "fit_elapsed_ms": result.elapsed_seconds * 1000.0,
                "fit_iterations": result.iterations,
                "body_facing_mismatch_deg": facing_mismatch_deg,
                "worst_target_joint": worst_target_joint,
                "worst_rotation": pose_diagnostics["worst_rotation"],
                "worst_twist": pose_diagnostics["worst_twist"],
                "worst_delta": pose_diagnostics["worst_delta"],
                "warning_joints": pose_diagnostics["warning_joints"],
            })

        self.prev_root = result.root_orient
        self.prev_body = result.body_pose
        self.prev_translation = result.translation
        return pack_protocol_v2_frame(packet_frame), residual

    def send(self, packet: bytes) -> None:
        self.sock.sendto(packet, (self.args.unity_host, self.args.unity_port))

    def send_raw_skeleton(self, frame: JointFrame) -> bool:
        if self.raw_destination is None:
            return False
        from .raw_skeleton_udp import pack_raw_skeleton_frame

        packet = pack_raw_skeleton_frame(
            frame_id=frame.frame_id,
            ptp_epoch_ns=frame.ptp_epoch_ns,
            points=frame.raw_joints,
            confidence=frame.confidence,
            unit=frame.input_unit,
            coordinate_frame=frame.coordinate_frame,
            ptp_exact=frame.ptp_exact,
        )
        self.sock.sendto(packet, self.raw_destination)
        return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="unix:///tmp/dt_pose_3d.sock")
    parser.add_argument(
        "--input-units", choices=("auto", "m", "mm"), default="auto",
        help="auto follows each payload's units field; legacy payloads without units default to mm",
    )
    parser.add_argument(
        "--axis-map", default="x,-y,-z",
        help="output axes as signed input axes; camera x-right/y-down/z-forward -> right-handed SMPL coordinates",
    )
    parser.add_argument("--unity-host", default="127.0.0.1")
    parser.add_argument("--unity-port", type=int, default=9095)
    parser.add_argument(
        "--raw-skeleton-host",
        help="RSV1 destination host; defaults to --unity-host",
    )
    parser.add_argument(
        "--raw-skeleton-port", type=int, default=9096,
        help="RSV1 raw factory-59 UDP port; use 0 to disable",
    )
    parser.add_argument("--smpl-dir", type=Path, default=default_smpl_dir())
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--calibration-frames", type=int, default=30)
    parser.add_argument("--calibration-iterations", type=int, default=100)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument(
        "--fit-profile", choices=tuple(FIT_PROFILES), default="full",
        help="full fits through ankles; upper-body ignores occluded legs and freezes their rotations",
    )
    parser.add_argument(
        "--beta-limit", type=float, default=3.0,
        help="absolute clamp for each calibrated SMPL shape coefficient; 0 disables",
    )
    parser.add_argument(
        "--fit-jsonl", type=Path,
        help="append same-frame raw, fitted Body25/SMPL24 joints and true residual diagnostics",
    )
    parser.add_argument(
        "--mesh-preview-json", type=Path,
        help="atomically overwrite a latest-only connected SMPL surface mesh for Dashboard debug",
    )
    parser.add_argument(
        "--mesh-preview-faces", type=int, default=2400,
        help="maximum triangles in the connected, vertex-clustered SMPL preview",
    )
    parser.add_argument("--endpoint-weight", type=float, default=0.5)
    parser.add_argument("--torso-weight", type=float, default=0.05)
    parser.add_argument(
        "--body-facing-weight", type=float, default=0.01,
        help="align fitted torso front with the horizontal SMPL feet direction",
    )
    parser.add_argument("--temporal-weight", type=float, default=0.01)
    parser.add_argument(
        "--max-fit-residual-mm", type=float, default=100.0,
        help="hold the previous Unity pose when MPJPE exceeds this value; 0 disables",
    )
    parser.add_argument(
        "--max-twist-deg", type=float, default=100.0,
        help="hold the previous Unity pose when any axial joint twist exceeds this value; 0 disables",
    )
    parser.add_argument(
        "--max-delta-deg", type=float, default=90.0,
        help="hold the previous Unity pose when any one-frame joint rotation jump exceeds this value; 0 disables",
    )
    parser.add_argument(
        "--max-facing-mismatch-deg", type=float, default=90.0,
        help="hold Unity pose when horizontal torso/feet directions disagree; 0 disables",
    )
    parser.add_argument(
        "--diagnostic-log-every", type=int, default=10,
        help="emit one structured distortion log every N successful fits; 0 disables",
    )
    parser.add_argument(
        "--robust-huber", action="store_true",
        help="optional noisy-input robustness; off preserves the measured 0901 squared-loss method",
    )
    parser.add_argument("--min-confidence", type=float, default=0.5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.diagnostic_log_every < 0:
        raise ValueError("diagnostic log interval must be non-negative")
    if args.body_facing_weight < 0:
        raise ValueError("body facing weight must be non-negative")
    if min(
        args.max_fit_residual_mm, args.max_twist_deg, args.max_delta_deg,
        args.max_facing_mismatch_deg,
    ) < 0:
        raise ValueError("fit safety thresholds must be non-negative")
    if not (args.smpl_dir / "smpl" / "SMPL_NEUTRAL.pkl").exists():
        print(
            f"SMPL model not found: {args.smpl_dir / 'smpl' / 'SMPL_NEUTRAL.pkl'}",
            file=sys.stderr,
        )
        return 2
    print(f"[bridge] input={args.input}")
    print(f"[bridge] Unity={args.unity_host}:{args.unity_port}, units={args.input_units}, axis={args.axis_map}")
    raw_host = args.raw_skeleton_host or args.unity_host
    print(
        f"[bridge] Raw skeleton={raw_host}:{args.raw_skeleton_port}"
        if args.raw_skeleton_port else "[bridge] Raw skeleton=disabled"
    )
    bridge = Smpl0901Bridge(args)
    fit_stream = None
    if args.fit_jsonl is not None:
        args.fit_jsonl.parent.mkdir(parents=True, exist_ok=True)
        fit_stream = args.fit_jsonl.open("a", encoding="utf-8")
        print(f"[bridge] fit diagnostics={args.fit_jsonl}")
    if args.mesh_preview_json is not None:
        args.mesh_preview_json.parent.mkdir(parents=True, exist_ok=True)
        print(
            f"[bridge] mesh preview={args.mesh_preview_json} "
            f"faces={args.mesh_preview_faces}"
        )
    received = sent = held = dropped = raw_sent = raw_dropped = 0
    try:
        for record in iter_json_records(args.input):
            received += 1
            try:
                frame = parse_joint_frame(
                    record, units=args.input_units, axis_map=args.axis_map, fallback_id=received - 1
                )
                try:
                    if bridge.send_raw_skeleton(frame):
                        raw_sent += 1
                except (ValueError, OSError) as error:
                    raw_dropped += 1
                    print(
                        f"[bridge] raw skeleton drop frame {frame.frame_id}: {error}",
                        file=sys.stderr,
                    )
                packet, residual = bridge.process(frame)
                bridge.send(packet)
                if fit_stream is not None and bridge.last_fit_record is not None:
                    fit_stream.write(json.dumps(bridge.last_fit_record, allow_nan=False) + "\n")
                    fit_stream.flush()
                if args.mesh_preview_json is not None and bridge.last_mesh_record is not None:
                    write_json_atomic(args.mesh_preview_json, bridge.last_mesh_record)
                sent += 1
                if (
                    args.diagnostic_log_every > 0
                    and (sent == 1 or sent % args.diagnostic_log_every == 0)
                    and bridge.last_fit_record is not None
                ):
                    fit = bridge.last_fit_record
                    pose_diagnostic = fit["pose_diagnostics"]
                    diagnostic_log = {
                        "schema": "smpl-0901.distortion-log/v1",
                        "frame": fit["frame"],
                        "timestamp_ns": fit["timestamp_ns"],
                        "accepted": True,
                        "action": "send",
                        "reasons": [],
                        "fit_residual_mm": fit["fit_residual_mm"],
                        "torso_orientation_deg": fit["torso_orientation_deg"],
                        "fit_elapsed_ms": fit["fit_elapsed_ms"],
                        "fit_iterations": fit["fit_iterations"],
                        "body_facing_mismatch_deg": fit["body_facing_mismatch_deg"],
                        "worst_target_joint": fit["worst_target_joint"],
                        "worst_rotation": pose_diagnostic["worst_rotation"],
                        "worst_twist": pose_diagnostic["worst_twist"],
                        "worst_delta": pose_diagnostic["worst_delta"],
                        "warning_joints": pose_diagnostic["warning_joints"],
                    }
                    print(
                        "[bridge] distortion "
                        + json.dumps(diagnostic_log, allow_nan=False, separators=(",", ":")),
                        flush=True,
                    )
                if sent == 1 or sent % 30 == 0:
                    fit_ms = float(bridge.last_fit_record["fit_elapsed_ms"])
                    fit_fps = 1000.0 / fit_ms if fit_ms > 0 else 0.0
                    print(
                        f"[bridge] received={received} sent={sent} raw_sent={raw_sent} "
                        f"raw_dropped={raw_dropped} held={held} dropped={dropped} "
                        f"residual={residual:.1f} mm fit_ms={fit_ms:.1f} "
                        f"fit_fps={fit_fps:.2f}"
                    )
            except CalibrationPending as error:
                # Expected during the initial fixed-beta calibration window.
                print(f"[bridge] {error}")
            except UnsafeFit as error:
                held += 1
                if fit_stream is not None and bridge.last_fit_record is not None:
                    fit_stream.write(json.dumps(bridge.last_fit_record, allow_nan=False) + "\n")
                    fit_stream.flush()
                if args.mesh_preview_json is not None and bridge.last_mesh_record is not None:
                    write_json_atomic(args.mesh_preview_json, bridge.last_mesh_record)
                print(
                    "[bridge] distortion "
                    + json.dumps(error.diagnostic, allow_nan=False, separators=(",", ":")),
                    flush=True,
                )
            except (ValueError, KeyError, TypeError) as error:
                dropped += 1
                print(f"[bridge] drop frame {received - 1}: {error}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
    finally:
        if fit_stream is not None:
            fit_stream.close()
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
