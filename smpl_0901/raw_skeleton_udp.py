"""Raw factory-59 skeleton UDP protocol, independent of SMPL fitting output.

The fixed 1032-byte RSV1 datagram stays below the usual 1500-byte Ethernet MTU.
Coordinates are the original dt-pose values, before unit conversion or axis map.
"""
from __future__ import annotations

import struct
from typing import Iterable

import numpy as np

HEADER = b"RSV1"
PROTOCOL_VERSION = 1
JOINT_COUNT = 59
COORDINATE_FRAME_BYTES = 64
FLAG_PTP_EXACT = 1 << 0
UNIT_TO_CODE = {"unknown": 0, "m": 1, "mm": 2}
CODE_TO_UNIT = {value: key for key, value in UNIT_TO_CODE.items()}
PACK_FORMAT = f"<4sHHIQB3x{COORDINATE_FRAME_BYTES}s{JOINT_COUNT * 3}f{JOINT_COUNT}f"
PACKET_SIZE = struct.calcsize(PACK_FORMAT)


def _coordinate_frame_bytes(value: str) -> bytes:
    encoded = str(value).encode("utf-8")
    if len(encoded) >= COORDINATE_FRAME_BYTES:
        raise ValueError(
            f"coordinate frame must be shorter than {COORDINATE_FRAME_BYTES} UTF-8 bytes"
        )
    return encoded.ljust(COORDINATE_FRAME_BYTES, b"\0")


def pack_raw_skeleton_frame(
    *,
    frame_id: int,
    ptp_epoch_ns: int,
    points: Iterable[Iterable[float]],
    confidence: Iterable[float],
    unit: str,
    coordinate_frame: str,
    ptp_exact: bool = True,
) -> bytes:
    joints = np.asarray(points, dtype=np.float32)
    scores = np.asarray(confidence, dtype=np.float32).reshape(-1)
    if joints.shape != (JOINT_COUNT, 3):
        raise ValueError(f"points must have shape [{JOINT_COUNT},3], got {joints.shape}")
    if scores.shape != (JOINT_COUNT,):
        raise ValueError(f"confidence must have shape [{JOINT_COUNT}], got {scores.shape}")
    if not np.isfinite(scores).all():
        raise ValueError("confidence contains NaN or infinity")
    unit_value = str(unit).lower()
    if unit_value not in UNIT_TO_CODE:
        raise ValueError(f"unsupported raw skeleton unit {unit!r}")
    if not 0 <= int(frame_id) <= 0xFFFFFFFF:
        raise ValueError("frame_id must fit uint32")
    if not 0 <= int(ptp_epoch_ns) <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("ptp_epoch_ns must fit uint64")
    packet = struct.pack(
        PACK_FORMAT,
        HEADER,
        PROTOCOL_VERSION,
        FLAG_PTP_EXACT if ptp_exact else 0,
        int(frame_id),
        int(ptp_epoch_ns),
        UNIT_TO_CODE[unit_value],
        _coordinate_frame_bytes(coordinate_frame),
        *joints.reshape(-1).tolist(),
        *np.clip(scores, 0.0, 1.0).tolist(),
    )
    if len(packet) != PACKET_SIZE:
        raise AssertionError(f"unexpected RSV1 packet size {len(packet)}")
    return packet


def unpack_raw_skeleton_frame(packet: bytes) -> dict[str, object]:
    if len(packet) != PACKET_SIZE:
        raise ValueError(f"RSV1 packet must be {PACKET_SIZE} bytes, got {len(packet)}")
    values = struct.unpack(PACK_FORMAT, packet)
    header, version, flags, frame_id, ptp_epoch_ns, unit_code, frame_bytes = values[:7]
    if header != HEADER:
        raise ValueError(f"unexpected raw skeleton header {header!r}")
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported raw skeleton version {version}")
    if unit_code not in CODE_TO_UNIT:
        raise ValueError(f"unsupported raw skeleton unit code {unit_code}")
    cursor = 7
    point_values = values[cursor:cursor + JOINT_COUNT * 3]
    cursor += JOINT_COUNT * 3
    confidence = values[cursor:cursor + JOINT_COUNT]
    return {
        "protocolVersion": version,
        "frameId": frame_id,
        "ptpEpochNs": ptp_epoch_ns,
        "ptpExact": bool(flags & FLAG_PTP_EXACT),
        "unit": CODE_TO_UNIT[unit_code],
        "coordinateFrame": frame_bytes.split(b"\0", 1)[0].decode("utf-8"),
        "points": np.asarray(point_values, dtype=np.float32).reshape(JOINT_COUNT, 3),
        "confidence": np.asarray(confidence, dtype=np.float32),
    }
