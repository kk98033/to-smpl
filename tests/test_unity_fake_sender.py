import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from smpl_0901.protocol_v2_udp import PACKET_SIZE as SMV2_PACKET_SIZE
from smpl_0901.raw_skeleton_udp import PACKET_SIZE as RSV1_PACKET_SIZE
from smpl_0901.unity_fake_sender import (
    RecordedPacket,
    UnityPacketRecorder,
    load_recording,
    packet_frame_id,
    replay,
)


def packet(protocol: str, frame_id: int) -> bytes:
    size = SMV2_PACKET_SIZE if protocol == "SMV2" else RSV1_PACKET_SIZE
    data = bytearray(size)
    data[:4] = protocol.encode("ascii")
    struct.pack_into("<I", data, 4 if protocol == "SMV2" else 8, frame_id)
    return bytes(data)


class FakeSocket:
    def __init__(self) -> None:
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def sendto(self, payload, destination):
        self.calls.append((payload, destination))


class UnityFakeSenderTests(unittest.TestCase):
    def test_recording_round_trip_preserves_exact_packets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unity_packets.jsonl"
            recorder = UnityPacketRecorder(path)
            recorder.record("RSV1", packet("RSV1", 7))
            recorder.record("SMV2", packet("SMV2", 7))
            recorder.close()

            events = load_recording(path)
            self.assertEqual([event.protocol for event in events], ["RSV1", "SMV2"])
            self.assertEqual(events[0].packet, packet("RSV1", 7))
            self.assertEqual(events[1].packet, packet("SMV2", 7))

    def test_replay_routes_protocols_and_advances_ids_when_looping(self):
        events = [
            RecordedPacket(0, "RSV1", packet("RSV1", 7)),
            RecordedPacket(10_000_000, "SMV2", packet("SMV2", 7)),
        ]
        fake_socket = FakeSocket()
        with mock.patch(
            "smpl_0901.unity_fake_sender.socket.socket", return_value=fake_socket
        ):
            stats = replay(
                events, host="192.0.2.1", loops=2, preserve_timing=False
            )

        self.assertEqual(stats["packets"], 4)
        self.assertEqual(
            [destination for _, destination in fake_socket.calls],
            [
                ("192.0.2.1", 9096),
                ("192.0.2.1", 9095),
                ("192.0.2.1", 9096),
                ("192.0.2.1", 9095),
            ],
        )
        replayed = [
            RecordedPacket(0, event.protocol, payload)
            for event, (payload, _) in zip(events * 2, fake_socket.calls)
        ]
        self.assertEqual([packet_frame_id(event) for event in replayed], [7, 7, 8, 8])


if __name__ == "__main__":
    unittest.main()
