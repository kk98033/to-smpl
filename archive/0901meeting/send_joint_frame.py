"""Small producer/helper for the live SMPL bridge.

It sends existing teammate JSON/JSONL output to unix:// or udp://.  The
``send_record`` function can also be imported at the point where the live 3-D
result is produced.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path


def send_record(record: dict, destination: str) -> bool:
    """Send without ever back-pressuring the predictor; False means dropped."""
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        if destination.startswith("unix://"):
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
                sender.setblocking(False)
                sender.sendto(payload, destination[len("unix://"):])
        elif destination.startswith("udp://"):
            host, port = destination[len("udp://"):].rsplit(":", 1)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.setblocking(False)
                sender.sendto(payload, (host, int(port)))
        else:
            raise ValueError("destination must start with unix:// or udp://")
    except (BlockingIOError, FileNotFoundError, ConnectionRefusedError):
        return False
    return True


def records(path: Path):
    if path.suffix.lower() == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data.get("frames"), dict):
        for frame_id in sorted(data["frames"], key=lambda item: int(item)):
            record = dict(data["frames"][frame_id])
            record.setdefault("frame_id", int(frame_id))
            yield record
    elif isinstance(data.get("frames"), list):
        yield from data["frames"]
    else:
        yield data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="teammate JSON or JSONL output")
    parser.add_argument("--destination", default="unix:///tmp/dt_pose_3d.sock")
    parser.add_argument("--fps", type=float, default=30.0)
    args = parser.parse_args()
    deadline = time.perf_counter()
    for record in records(args.path):
        send_record(record, args.destination)
        deadline += 1.0 / args.fps
        time.sleep(max(0.0, deadline - time.perf_counter()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
