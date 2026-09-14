"""Live factory-59 joints -> 0901 SMPL -> Unity Protocol V2 bridge.

The input is one JSON object per datagram/line.  Accepted joint fields are:

* ``keypoints_3d``: a [59, 3] array in factory order (body17, LH21, RH21)
* ``keypoint_3d``: a mapping keyed by COCO-WholeBody ids
  (0..16, 91..111, 112..132)

This service deliberately sits after the teammate's 3-D predictor.  It does not
receive the three CUDA image IPC streams; those belong to dt-pose's upstream
transport/inference service.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

# chumpy (used by the bundled SMPL code) still references removed numpy aliases.
for _name, _value in {
    "bool": bool, "int": int, "float": float, "complex": complex,
    "object": object, "unicode": str, "str": str,
}.items():
    if _name not in np.__dict__:
        setattr(np, _name, _value)

SCRIPT_DIR = Path(__file__).resolve().parent
MAIN_ROOT = SCRIPT_DIR.parent
PIPELINE_ROOT = MAIN_ROOT / "my_method" / "realtime_smplh_pipeline"
CORE_DIR = PIPELINE_ROOT / "core"
for _path in (PIPELINE_ROOT, CORE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

FACTORY_IDS = tuple(range(17)) + tuple(range(91, 133))


@dataclass(frozen=True)
class JointFrame:
    frame_id: int
    timestamp: float
    joints: np.ndarray  # [59,3], meters, SMPL axes
    confidence: np.ndarray  # [59]


class CalibrationPending(RuntimeError):
    """Normal startup state while the fixed-beta window is being collected."""


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
    raw = record.get("keypoints_3d", record.get("points_3d"))
    if raw is not None:
        points = np.asarray(raw, dtype=np.float32)
        if points.shape == (133, 3):
            points = points[np.asarray(FACTORY_IDS)]
        if points.shape != (59, 3):
            raise ValueError(f"keypoints_3d must have shape [59,3] (or [133,3]), got {points.shape}")
        return points

    raw_map = record.get("keypoint_3d")
    if not isinstance(raw_map, dict):
        raise ValueError("missing keypoints_3d [59,3] or keypoint_3d mapping")
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
    return np.clip(values, 0.0, 1.0)


def parse_joint_frame(record: dict, *, units: str, axis_map: str, fallback_id: int) -> JointFrame:
    schema = record.get("schema")
    if schema not in (None, "factory_59pt_body_hands"):
        raise ValueError(f"unsupported schema {schema!r}; expected factory_59pt_body_hands")
    points = _ordered_joints(record)
    confidence = _confidence(record)
    confidence[~np.isfinite(points).all(axis=1)] = 0.0
    scale = 0.001 if units == "mm" else 1.0
    points = points * scale
    mapping = parse_axis_map(axis_map)
    points = np.stack([points[:, index] * sign for index, sign in mapping], axis=1)
    frame_id = int(record.get("frame_id", record.get("frame_index", record.get("frameId", fallback_id))))
    timestamp = float(record.get("timestamp", record.get("timestamp_s", time.time())))
    return JointFrame(frame_id, timestamp, points.astype(np.float32), confidence)


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


def iter_json_records(uri: str, *, max_datagram: int = 1 << 20) -> Iterator[dict]:
    """Yield JSON records from unix://, udp://, stdin://, or jsonl://."""
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
        raise ValueError("input URI must start with unix://, udp://, jsonl://, or be stdin://")


def default_smpl_dir() -> Path:
    candidates = (
        MAIN_ROOT.parent / "hyberik" / "Learnable-SMPLify" / "src" / "data" / "SMPL-family",
        MAIN_ROOT / "my_method" / "Learnable-SMPLify" / "src" / "data" / "SMPL-family",
    )
    for path in candidates:
        if path.exists():
            return path
    return candidates[-1]


class Smpl0901Bridge:
    def __init__(self, args: argparse.Namespace) -> None:
        import torch
        from common.human_models import SMPL

        self.torch = torch
        self.args = args
        self.device = torch.device(args.device)
        human_model = SMPL(str(args.smpl_dir))
        self.smpl_layer = human_model.layer["neutral"].to(self.device)
        self.regressor = torch.tensor(
            np.load(args.smpl_dir / "smpl" / "J_regressor_body25.npy"),
            dtype=torch.float32,
            device=self.device,
        )
        self.fixed_betas = None
        self.calibration: list[np.ndarray] = []
        self.prev_root = None
        self.prev_body = None
        self.prev_translation = None
        self.pelvis_anchor = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def close(self) -> None:
        self.sock.close()

    def _calibrate(self) -> None:
        from fixed_betas_fitter import estimate_fixed_betas

        target = self.torch.tensor(np.stack(self.calibration), dtype=self.torch.float32, device=self.device)
        self.fixed_betas = estimate_fixed_betas(
            self.smpl_layer, self.regressor, target,
            iterations=self.args.calibration_iterations,
        )
        print(f"[bridge] calibration complete; fixed betas={self.fixed_betas.cpu().numpy().round(3).tolist()}")

    def process(self, frame: JointFrame) -> tuple[bytes, float]:
        from scipy.spatial.transform import Rotation
        from fixed_betas_fitter import fit_fixed_betas_soft_target
        from frame0_initializer import analytical_root_seed
        from protocol_v2 import wrist_local_hand
        from protocol_v2_udp import pack_protocol_v2_frame

        body25, left_hand, right_hand = body25_from_factory59(frame.joints)
        body_conf = frame.confidence[:17]
        required_coco = np.asarray((0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16))
        if (
            not np.isfinite(body25[:15]).all()
            or not np.all(body_conf[required_coco] >= self.args.min_confidence)
        ):
            raise ValueError("body input is incomplete/non-finite; holding the last Unity pose")

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
        result = fit_fixed_betas_soft_target(
            self.smpl_layer,
            self.regressor,
            target,
            self.fixed_betas,
            init_root,
            init_body=self.prev_body,
            init_translation=self.prev_translation,
            iterations=self.args.iterations,
            endpoint_weight=self.args.endpoint_weight,
            torso_normal_weight=self.args.torso_weight,
            temporal_smooth_weight=self.args.temporal_weight,
            prev_body_pose=self.prev_body,
            use_huber=True,
        )
        self.prev_root = result.root_orient
        self.prev_body = result.body_pose
        self.prev_translation = result.translation

        pose = np.zeros(156, dtype=np.float32)
        root = result.root_orient[0].cpu().numpy()
        body = result.body_pose[0].reshape(23, 3).cpu().numpy()
        pose[:3] = root
        pose[3:66] = body[:21].reshape(-1)

        left_local, left_conf, left_ok = wrist_local_hand(
            left_hand, frame.confidence[17:38], side="left"
        )
        right_local, right_conf, right_ok = wrist_local_hand(
            right_hand, frame.confidence[38:59], side="right"
        )
        residuals = np.linalg.norm(result.pred_body25[0, :15].cpu().numpy() - target_np[:15], axis=1) * 1000.0
        residual = float(residuals.mean())
        torso_deg = float(result.torso_orientation_deg[0].cpu())
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
                "rootConfidence": float(np.mean(body_conf)),
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
                "worstJointResidualMm": float(residuals.max()),
                "torsoOrientationDeg": torso_deg,
                "solverState": "TRACKING" if residual < 50.0 and torso_deg < 10.0 else "RECOVERED",
                "stepsUsed": self.args.iterations,
                "reasons": [],
            },
        }
        return pack_protocol_v2_frame(packet_frame), residual

    def send(self, packet: bytes) -> None:
        self.sock.sendto(packet, (self.args.unity_host, self.args.unity_port))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="unix:///tmp/dt_pose_3d.sock")
    parser.add_argument("--input-units", choices=("m", "mm"), default="m")
    parser.add_argument(
        "--axis-map", default="x,-y,z",
        help="output axes as signed input axes; camera x-right/y-down/z-forward -> SMPL x-right/y-up/z-forward",
    )
    parser.add_argument("--unity-host", default="127.0.0.1")
    parser.add_argument("--unity-port", type=int, default=9095)
    parser.add_argument("--smpl-dir", type=Path, default=default_smpl_dir())
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--calibration-frames", type=int, default=10)
    parser.add_argument("--calibration-iterations", type=int, default=100)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--endpoint-weight", type=float, default=2.5)
    parser.add_argument("--torso-weight", type=float, default=1.5)
    parser.add_argument("--temporal-weight", type=float, default=0.01)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.smpl_dir.exists():
        print(f"SMPL model directory not found: {args.smpl_dir}", file=sys.stderr)
        return 2
    print(f"[bridge] input={args.input}")
    print(f"[bridge] Unity={args.unity_host}:{args.unity_port}, units={args.input_units}, axis={args.axis_map}")
    bridge = Smpl0901Bridge(args)
    received = sent = dropped = 0
    try:
        for record in iter_json_records(args.input):
            received += 1
            try:
                frame = parse_joint_frame(
                    record, units=args.input_units, axis_map=args.axis_map, fallback_id=received - 1
                )
                packet, residual = bridge.process(frame)
                bridge.send(packet)
                sent += 1
                if sent == 1 or sent % 30 == 0:
                    print(f"[bridge] received={received} sent={sent} dropped={dropped} residual={residual:.1f} mm")
            except CalibrationPending as error:
                # Expected during the initial fixed-beta calibration window.
                print(f"[bridge] {error}")
            except (ValueError, KeyError, TypeError) as error:
                dropped += 1
                print(f"[bridge] drop frame {received - 1}: {error}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
