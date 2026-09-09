"""Binary UDP extension for the existing SMPL/SMPJ Unity transport.

SMV2 keeps the legacy 644-byte SMPL prefix (header, frame, translation,
156-axis-angle pose) and appends root, raw hands and no-GT quality fields.
The complete datagram is 1389 bytes, below the usual 1500-byte Ethernet MTU.
"""

from __future__ import annotations

import json
import socket
import struct
import time
from pathlib import Path
from typing import Iterable

import numpy as np


HEADER = b"SMV2"
SOLVER_STATES = (
    "TRACKING",
    "RECOVERED",
    "ADAPTIVE_100",
    "KAMA_REINITIALIZE",
    "HOLD_INPUT_INVALID",
    "TRACKING_LOST",
    "FAILED_HOLD",
)
STATE_TO_CODE = {name: index for index, name in enumerate(SOLVER_STATES)}
REASON_BITS = {
    "non_finite": 1 << 0,
    "coordinate_range": 1 << 1,
    "torso_length": 1 << 2,
    "left_right_asymmetry": 1 << 3,
    "bone_length_outlier": 1 << 4,
    "joint_speed": 1 << 5,
    "joint_residual": 1 << 6,
    "max_joint_residual": 1 << 7,
    "torso_orientation": 1 << 8,
    "twist": 1 << 9,
    "delta": 1 << 10,
    "facing_mismatch": 1 << 11,
    "fit_residual": 1 << 12,
}

# No native alignment ("<"). The B quality flag is intentionally unpadded.
PACK_FORMAT = "<4sI3f156f3f3f4ff63f21f63f21fB4fiiI"
PACKET_SIZE = struct.calcsize(PACK_FORMAT)


def _floats(values: Iterable[float], count: int, field: str) -> list[float]:
    array = np.asarray(values, dtype=np.float32).reshape(-1)
    if array.size != count:
        raise ValueError(f"{field} must contain {count} values, got {array.size}")
    if not np.isfinite(array).all():
        raise ValueError(f"{field} contains NaN or infinity")
    return array.tolist()


def _reason_mask(reasons: Iterable[str]) -> int:
    mask = 0
    for reason in reasons:
        key = str(reason).split(">", 1)[0]
        mask |= REASON_BITS.get(key, 0)
    return mask


def pack_protocol_v2_frame(frame: dict) -> bytes:
    if int(frame.get("protocolVersion", -1)) != 2:
        raise ValueError("protocolVersion must be 2")
    body = frame["body"]
    hands = frame["hands"]
    quality = frame["quality"]
    packet = struct.pack(
        PACK_FORMAT,
        HEADER,
        int(frame["frameId"]),
        *_floats(body["rootPosition"], 3, "body.rootPosition"),
        *_floats(body["pose"], 156, "body.pose"),
        *_floats(body["rootPosition"], 3, "body.rootPosition"),
        *_floats(body["pelvisWorld"], 3, "body.pelvisWorld"),
        *_floats(body["rootRotation"], 4, "body.rootRotation"),
        float(body["rootConfidence"]),
        *_floats(hands["leftLocalJoints"], 63, "hands.leftLocalJoints"),
        *_floats(hands["leftConfidence"], 21, "hands.leftConfidence"),
        *_floats(hands["rightLocalJoints"], 63, "hands.rightLocalJoints"),
        *_floats(hands["rightConfidence"], 21, "hands.rightConfidence"),
        1 if quality["inputValid"] else 0,
        float(quality["inputScore"]),
        float(quality["fitResidualMm"]),
        float(quality["worstJointResidualMm"]),
        float(quality["torsoOrientationDeg"]),
        int(STATE_TO_CODE.get(quality["solverState"], STATE_TO_CODE["FAILED_HOLD"])),
        int(quality["stepsUsed"]),
        _reason_mask(quality.get("reasons", ())),
    )
    if len(packet) != PACKET_SIZE:
        raise AssertionError(f"Unexpected SMV2 packet size {len(packet)}")
    return packet


def unpack_protocol_v2_frame(packet: bytes) -> dict:
    if len(packet) != PACKET_SIZE:
        raise ValueError(f"SMV2 packet must be {PACKET_SIZE} bytes, got {len(packet)}")
    values = struct.unpack(PACK_FORMAT, packet)
    cursor = 0
    header, frame_id = values[cursor], values[cursor + 1]
    cursor += 2
    if header != HEADER:
        raise ValueError(f"Unexpected header {header!r}")

    def take(count: int) -> list[float]:
        nonlocal cursor
        result = list(values[cursor:cursor + count])
        cursor += count
        return result

    legacy_trans = take(3)
    pose = take(156)
    root_position = take(3)
    pelvis_world = take(3)
    root_rotation = take(4)
    root_confidence = float(values[cursor]); cursor += 1
    left_local = take(63)
    left_confidence = take(21)
    right_local = take(63)
    right_confidence = take(21)
    input_valid = bool(values[cursor]); cursor += 1
    input_score, fit_mm, worst_mm, torso_deg = take(4)
    state_code = int(values[cursor]); cursor += 1
    steps_used = int(values[cursor]); cursor += 1
    reason_mask = int(values[cursor])
    return {
        "protocolVersion": 2,
        "frameId": int(frame_id),
        "legacyTranslation": legacy_trans,
        "body": {
            "rootPosition": root_position,
            "pelvisWorld": pelvis_world,
            "rootRotation": root_rotation,
            "rootConfidence": root_confidence,
            "pose": pose,
        },
        "hands": {
            "leftLocalJoints": left_local,
            "leftConfidence": left_confidence,
            "rightLocalJoints": right_local,
            "rightConfidence": right_confidence,
        },
        "quality": {
            "inputValid": input_valid,
            "inputScore": input_score,
            "fitResidualMm": fit_mm,
            "worstJointResidualMm": worst_mm,
            "torsoOrientationDeg": torso_deg,
            "solverState": SOLVER_STATES[state_code] if 0 <= state_code < len(SOLVER_STATES) else "FAILED_HOLD",
            "stepsUsed": steps_used,
            "reasonMask": reason_mask,
        },
    }


def stream_playback(
    playback_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 9095,
    fps: float = 15.0,
    realtime: bool = True,
    packet_dump: str | Path | None = None,
) -> dict:
    path = Path(playback_path)
    playback = json.loads(path.read_text(encoding="utf-8"))
    frames = playback.get("frames", [])
    if not frames:
        raise ValueError(f"No protocol-v2 frames in {path}")
    if fps <= 0:
        raise ValueError("fps must be positive")

    first_packet = pack_protocol_v2_frame(frames[0])
    if packet_dump is not None:
        Path(packet_dump).write_bytes(first_packet)

    sent_bytes = 0
    start = time.perf_counter()
    deadline = start
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for frame in frames:
            packet = pack_protocol_v2_frame(frame)
            sock.sendto(packet, (host, int(port)))
            sent_bytes += len(packet)
            if realtime:
                deadline += 1.0 / fps
                delay = deadline - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
    elapsed = time.perf_counter() - start
    return {
        "frames": len(frames),
        "packetBytes": PACKET_SIZE,
        "totalBytes": sent_bytes,
        "elapsedSeconds": elapsed,
        "effectiveFps": len(frames) / max(elapsed, 1e-9),
        "destination": f"{host}:{port}",
    }

