"""Record and replay the exact SMV2/RSV1 UDP stream sent to Unity."""

from __future__ import annotations

import argparse
import base64
import json
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from .protocol_v2_udp import PACKET_SIZE as SMV2_PACKET_SIZE
from .raw_skeleton_udp import PACKET_SIZE as RSV1_PACKET_SIZE


SCHEMA = "smpl-0901.unity-packet-record/v1"
PACKET_SIZES = {"SMV2": SMV2_PACKET_SIZE, "RSV1": RSV1_PACKET_SIZE}
FRAME_ID_OFFSETS = {"SMV2": 4, "RSV1": 8}


@dataclass(frozen=True)
class RecordedPacket:
    elapsed_ns: int
    protocol: str
    packet: bytes


def validate_packet(protocol: str, packet: bytes) -> None:
    expected = PACKET_SIZES.get(protocol)
    if expected is None:
        raise ValueError(f"unsupported protocol {protocol!r}")
    if len(packet) != expected:
        raise ValueError(f"{protocol} packet must be {expected} bytes, got {len(packet)}")
    if packet[:4] != protocol.encode("ascii"):
        raise ValueError(f"{protocol} packet has wrong magic {packet[:4]!r}")


class UnityPacketRecorder:
    """Write exact outgoing Unity datagrams with their relative send time."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("w", encoding="utf-8")
        self._start_ns = time.monotonic_ns()

    def record(self, protocol: str, packet: bytes) -> None:
        validate_packet(protocol, packet)
        record = {
            "schema": SCHEMA,
            "elapsed_ns": time.monotonic_ns() - self._start_ns,
            "protocol": protocol,
            "packet_b64": base64.b64encode(packet).decode("ascii"),
        }
        self._stream.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()


def load_recording(path: str | Path) -> list[RecordedPacket]:
    events: list[RecordedPacket] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            if raw.get("schema") != SCHEMA:
                raise ValueError(f"unexpected schema {raw.get('schema')!r}")
            protocol = str(raw["protocol"])
            packet = base64.b64decode(raw["packet_b64"], validate=True)
            validate_packet(protocol, packet)
            events.append(RecordedPacket(int(raw["elapsed_ns"]), protocol, packet))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid recording line {line_number}: {error}") from error
    if not events:
        raise ValueError(f"recording is empty: {path}")
    if any(current.elapsed_ns < previous.elapsed_ns for previous, current in zip(events, events[1:])):
        raise ValueError("recording elapsed_ns must be monotonic")
    return events


def packet_frame_id(event: RecordedPacket) -> int:
    return struct.unpack_from("<I", event.packet, FRAME_ID_OFFSETS[event.protocol])[0]


def replace_frame_id(event: RecordedPacket, frame_id: int) -> bytes:
    packet = bytearray(event.packet)
    struct.pack_into("<I", packet, FRAME_ID_OFFSETS[event.protocol], int(frame_id) & 0xFFFFFFFF)
    return bytes(packet)


def replay(
    events: list[RecordedPacket], *, host: str, smv2_port: int = 9095,
    rsv1_port: int = 9096, speed: float = 1.0, loops: int = 1,
    preserve_timing: bool = True,
) -> dict[str, object]:
    if speed <= 0:
        raise ValueError("speed must be positive")
    if loops < 0:
        raise ValueError("loops must be non-negative")
    ports = {"SMV2": int(smv2_port), "RSV1": int(rsv1_port)}
    frame_ids = [packet_frame_id(event) for event in events]
    frame_span = max(frame_ids) - min(frame_ids) + 1
    sent = 0
    cycle = 0
    start = time.perf_counter()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        while loops == 0 or cycle < loops:
            cycle_start = time.perf_counter()
            first_elapsed = events[0].elapsed_ns
            for event in events:
                if preserve_timing:
                    deadline = cycle_start + (event.elapsed_ns - first_elapsed) / 1e9 / speed
                    delay = deadline - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                frame_id = packet_frame_id(event) + cycle * frame_span
                sender.sendto(replace_frame_id(event, frame_id), (host, ports[event.protocol]))
                sent += 1
            cycle += 1
    elapsed = time.perf_counter() - start
    return {"packets": sent, "loops": cycle, "seconds": elapsed, "destination": host}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path, help="JSONL created by Bridge --record-unity-packets")
    parser.add_argument("--unity-host", required=True, help="Unity PC LAN/VPN IPv4 or 127.0.0.1")
    parser.add_argument("--unity-port", type=int, default=9095)
    parser.add_argument("--raw-skeleton-port", type=int, default=9096)
    parser.add_argument("--speed", type=float, default=1.0, help="1=recorded timing, 2=twice as fast")
    parser.add_argument("--loop", action="store_true", help="repeat until Ctrl+C")
    parser.add_argument("--no-timing", action="store_true", help="send without recorded delays")
    args = parser.parse_args()
    events = load_recording(args.recording)
    print(f"[unity-fake] loaded={len(events)} from {args.recording}")
    print(f"[unity-fake] Unity={args.unity_host}:{args.unity_port}, RSV1={args.raw_skeleton_port}")
    try:
        stats = replay(
            events, host=args.unity_host, smv2_port=args.unity_port,
            rsv1_port=args.raw_skeleton_port, speed=args.speed,
            loops=0 if args.loop else 1, preserve_timing=not args.no_timing,
        )
    except KeyboardInterrupt:
        print("\n[unity-fake] stopped")
        return 0
    print("[unity-fake] " + json.dumps(stats, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
