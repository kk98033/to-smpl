"""Fake Sender for Real-time Dataset Inference & SMPL Video Playback (0901 Meeting).

Simulates real-time AI inference by streaming pre-computed SMPL-H / Protocol V2
frames over UDP (Port 9095) in a loop, while simultaneously sending the corresponding
rendered SMPL visualization MP4 video path to Unity for synchronized side-by-side playback.
"""

import argparse
import json
import socket
import struct
import sys
import time
from pathlib import Path

# Force UTF-8 stdout for Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
MAIN_ROOT = SCRIPT_DIR.parent
PIPELINE_ROOT = MAIN_ROOT / "my_method" / "realtime_smplh_pipeline"
CORE_DIR = PIPELINE_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from core.protocol_v2_udp import PACKET_SIZE, pack_protocol_v2_frame
from scipy.spatial.transform import Rotation as R

# Dataset & Video Mapping Table
NEW_OUT = SCRIPT_DIR / "new_outputs"

DATASET_MAP = {
    0: {
        "id": "h3wb_300",
        "alias": ["0", "h3wb", "h3wb_300"],
        "name": "H3WB 300 — Whole-Body GT / Hands / Root (Calibrated Upright)",
        "json_path": (NEW_OUT / "h3wb_300" / "h3wb_300.json") if (NEW_OUT / "h3wb_300" / "h3wb_300.json").exists() else (MAIN_ROOT / "0804meeting" / "unity_playback" / "h3wb_300.json"),
        "video_path": (NEW_OUT / "h3wb_300" / "h3wb_300_comparison.mp4") if (NEW_OUT / "h3wb_300" / "h3wb_300_comparison.mp4").exists() else (MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "08_H3WB_FullBody_With_21x2_Hands.mp4"),
        "alt_video": MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "01_H3WB_GT_vs_SMPL.mp4",
        "fps": 15.0,
    },
    1: {
        "id": "h36m_300",
        "alias": ["1", "h36m", "h36m_300", "human36m"],
        "name": "H3.6M 300 — Ground Truth Body / Root (Calibrated Upright)",
        "json_path": (NEW_OUT / "h36m_300" / "h36m_300.json") if (NEW_OUT / "h36m_300" / "h36m_300.json").exists() else (MAIN_ROOT / "0804meeting" / "unity_playback" / "h36m_300.json"),
        "video_path": (NEW_OUT / "h36m_300" / "h36m_300_comparison.mp4") if (NEW_OUT / "h36m_300" / "h36m_300_comparison.mp4").exists() else (MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "02_H36M_GT_vs_SMPL.mp4"),
        "alt_video": MAIN_ROOT / "0721meeting" / "experiments" / "Best_Adaptive_Long_Suite" / "h36m_300" / "long_gt_prediction_comparison.mp4",
        "fps": 15.0,
    },
    2: {
        "id": "amass_punching",
        "alias": ["2", "punching", "amass_punching"],
        "name": "AMASS Punching — Fast Boxing Motion (Real SMPL-H Hands)",
        "json_path": (NEW_OUT / "amass_punching" / "amass_punching.json") if (NEW_OUT / "amass_punching" / "amass_punching.json").exists() else (MAIN_ROOT / "0804meeting" / "unity_playback" / "amass_punching.json"),
        "video_path": (NEW_OUT / "amass_punching" / "amass_punching_comparison.mp4") if (NEW_OUT / "amass_punching" / "amass_punching_comparison.mp4").exists() else (MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "09_AMASS_Punching_FullBody_With_21x2_Hands.mp4"),
        "alt_video": MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "03_AMASS_Punching_GT_vs_SMPL.mp4",
        "fps": 15.0,
    },
    3: {
        "id": "amass_sample_300",
        "alias": ["3", "sample", "amass_sample", "amass_sample_300"],
        "name": "AMASS Sample 300 — Full Body & Hand Reference (Real SMPL-H Hands)",
        "json_path": (NEW_OUT / "amass_sample_300" / "amass_sample_300.json") if (NEW_OUT / "amass_sample_300" / "amass_sample_300.json").exists() else (MAIN_ROOT / "0804meeting" / "unity_playback" / "amass_sample_300.json"),
        "video_path": (NEW_OUT / "amass_sample_300" / "amass_sample_300_comparison.mp4") if (NEW_OUT / "amass_sample_300" / "amass_sample_300_comparison.mp4").exists() else (MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "10_AMASS_Sample_FullBody_With_21x2_Hands.mp4"),
        "alt_video": MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "04_AMASS_Sample_GT_vs_SMPL.mp4",
        "fps": 15.0,
    },
    4: {
        "id": "amass_hand_motion_300",
        "alias": ["4", "hand", "hand_motion", "amass_hand_motion_300"],
        "name": "AMASS Hand Motion 300 — Dynamic Finger Rotations (Real SMPL-H Hands)",
        "json_path": MAIN_ROOT / "0804meeting" / "unity_playback" / "amass_hand_motion_300.json",
        "video_path": MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "13_AMASS_HandMotion_SMPLRotation_With_21x2_Hands.mp4",
        "alt_video": None,
        "fps": 15.0,
    },
    5: {
        "id": "teammate_2cam_300",
        "alias": ["5", "2cam", "teammate_2cam", "teammate_2cam_300"],
        "name": "Teammate 2-Camera — Noisy Triangulation",
        "json_path": MAIN_ROOT / "0804meeting" / "unity_playback" / "teammate_2cam_300.json",
        "video_path": MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "11_Teammate_2Cam_With_21x2_Hands_NoGT.mp4",
        "alt_video": MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "05_Teammate_2Cam_Input_vs_SMPL_NoGT.mp4",
        "fps": 15.0,
    },
    6: {
        "id": "teammate_4view_300",
        "alias": ["6", "4view", "teammate_4view", "teammate_4view_300"],
        "name": "Teammate 4-View — Multiview Predicted Joints",
        "json_path": MAIN_ROOT / "0804meeting" / "unity_playback" / "teammate_4view_300.json",
        "video_path": MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "12_Teammate_4View_With_21x2_Hands_NoGT.mp4",
        "alt_video": MAIN_ROOT / "0804meeting" / "presentation_assets" / "videos" / "06_Teammate_4View_Input_vs_SMPL_NoGT.mp4",
        "fps": 15.0,
    },
}



def prepare_calibrated_frames(dataset_id: str, raw_frames: list[dict]) -> list[dict]:
    """Preprocess and calibrate dataset frames for clean, upright real-time UDP streaming."""
    frames = json.loads(json.dumps(raw_frames))
    count = len(frames)
    import numpy as np

    # 1. AMASS Mocap Hand Pose Injection (Real SMPL-H 90-D hand rotation)
    if dataset_id == "amass_punching":
        punch_path = MAIN_ROOT / "data" / "amass_dataset" / "punching_poses.npz"
        if punch_path.exists():
            data = np.load(punch_path, allow_pickle=True)
            amass_poses = np.asarray(data["poses"], dtype=np.float32)
            for i in range(min(count, len(amass_poses))):
                hand_rot = amass_poses[i, 66:156].tolist()
                frames[i]["body"]["pose"][66:156] = hand_rot
    elif dataset_id == "amass_sample_300":
        sample_path = MAIN_ROOT / "data" / "amass_dataset" / "amass_sample.npz"
        if sample_path.exists():
            data = np.load(sample_path, allow_pickle=True)
            amass_poses = np.asarray(data["poses"], dtype=np.float32)
            for i in range(min(count, len(amass_poses))):
                hand_rot = amass_poses[i, 66:156].tolist()
                frames[i]["body"]["pose"][66:156] = hand_rot

    # 2. Upright Root Orientation Calibration for H3.6M and H3WB (Fix upside-down flip)
    if dataset_id in ("h36m_300", "h3wb_300"):
        r_corr = R.from_euler("x", 180, degrees=True)
        for frame in frames:
            body = frame["body"]
            pose = body["pose"]
            r_old = R.from_rotvec(pose[:3])
            r_new = r_corr * r_old
            pose[:3] = r_new.as_rotvec().tolist()

            # Root rotation quaternion (XYZW)
            if "rootRotation" in body and body["rootRotation"]:
                q_old = R.from_quat(body["rootRotation"])
                q_new = r_corr * q_old
                body["rootRotation"] = q_new.as_quat().tolist()

            # Pelvis position & Observation joints (invert Y & Z to match upright)
            if "pelvisWorld" in body and body["pelvisWorld"]:
                body["pelvisWorld"][1] = -body["pelvisWorld"][1]
                body["pelvisWorld"][2] = -body["pelvisWorld"][2]
            if "observation" in frame and "joints" in frame["observation"]:
                joints = frame["observation"]["joints"]
                for j in range(0, len(joints), 3):
                    joints[j + 1] = -joints[j + 1]
                    joints[j + 2] = -joints[j + 2]

    # 3. Natural Relaxed Hand Pose for datasets without hand tracking (H3.6M)
    if dataset_id == "h36m_300":
        relaxed_hand = [0.0] * 90
        for finger in range(4):
            for seg in range(3):
                idx = finger * 3 + seg
                relaxed_hand[idx * 3 + 2] = 0.20  # Left hand
                relaxed_hand[45 + idx * 3 + 2] = -0.20  # Right hand
        relaxed_hand[12 * 3 + 1] = -0.15  # Left thumb
        relaxed_hand[45 + 12 * 3 + 1] = 0.15  # Right thumb
        for frame in frames:
            frame["body"]["pose"][66:156] = relaxed_hand

    return frames


def find_dataset(query: str | None) -> dict | None:
    if query is None:
        return None
    q = str(query).strip().lower()
    for entry in DATASET_MAP.values():
        if q in [str(a).lower() for a in entry["alias"]]:
            return entry
    return None


def send_vide_packet(sock: socket.socket, host: str, port: int, video_path: Path | str) -> bool:
    """Send 'VIDE' packet with the video's absolute path to Unity."""
    path_str = str(Path(video_path).resolve())
    payload = b"VIDE" + path_str.encode("utf-8")
    try:
        sock.sendto(payload, (host, port))
        return True
    except Exception as e:
        print(f"[-] Failed to send VIDE packet: {e}")
        return False


def build_legacy_smpj_packet(frame: dict) -> bytes:
    """Pack legacy SMPJ binary packet (header, frame_id, trans, poses, 67 joints)."""
    frame_id = int(frame.get("frameId", 0))
    body = frame.get("body", {})
    trans = body.get("rootPosition", [0.0, 0.0, 0.0])
    poses = body.get("pose", [0.0] * 156)

    header = b"SMPJ"
    flat_trans = [float(v) for v in trans[:3]]
    flat_poses = [float(v) for v in poses[:156]]
    if len(flat_poses) < 156:
        flat_poses += [0.0] * (156 - len(flat_poses))

    obs = frame.get("observation", {})
    joints_67 = obs.get("joints", [])
    flat_joints = []
    if joints_67:
        for pt in joints_67[:67]:
            flat_joints.extend([float(pt[0]), float(pt[1]), float(pt[2])])
    if len(flat_joints) < 67 * 3:
        flat_joints += [0.0] * (67 * 3 - len(flat_joints))

    packet_fmt = f"<4sI3f156f{len(flat_joints)}f"
    return struct.pack(packet_fmt, header, frame_id, *flat_trans, *flat_poses, *flat_joints)


def main():
    parser = argparse.ArgumentParser(description="Fake Sender for SMPL / Protocol V2 Realtime UDP Stream.")
    parser.add_argument("-d", "--dataset", type=str, default=None, help="Dataset index (0..6) or name (h3wb, h36m, punching, sample, hand_motion, 2cam, 4view)")
    parser.add_argument("--fps", type=float, default=None, help="Playback FPS (default: clip native FPS or 15)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Target UDP host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9095, help="Target UDP port (default 9095)")
    parser.add_argument("--no_video", action="store_true", help="Do not send VIDE packet to Unity")
    parser.add_argument("--video_path", type=str, default="", help="Override custom video file path")
    parser.add_argument("--protocol", choices=["smv2", "legacy", "both"], default="smv2", help="Packet format: smv2 (Protocol V2), legacy (SMPJ), or both")
    parser.add_argument("--single_run", action="store_true", help="Play only once instead of continuous infinite loop")
    args = parser.parse_args()

    selected = find_dataset(args.dataset)

    if selected is None:
        print("\n" + "=" * 70)
        print(" 🎬 0901 Fake Sender: 請選擇要重複串流的資料集推理結果與影片")
        print("=" * 70)
        for idx, item in DATASET_MAP.items():
            print(f" [{idx}] {item['name']}")
        print("=" * 70)
        choice = input("請輸入選項編號 [0-6] (預設 0 - H3WB 300): ").strip()
        if not choice:
            choice = "0"
        selected = find_dataset(choice)
        if selected is None:
            print("[-] 無效的選項，使用預設 H3WB 300")
            selected = DATASET_MAP[0]

    fps = args.fps if args.fps is not None and args.fps > 0 else selected["fps"]
    json_path = selected["json_path"]

    video_path = None
    if not args.no_video:
        if args.video_path:
            video_path = Path(args.video_path)
        elif selected["video_path"] and selected["video_path"].exists():
            video_path = selected["video_path"]
        elif selected["alt_video"] and selected["alt_video"].exists():
            video_path = selected["alt_video"]

    if not json_path.exists():
        print(f"[-] 找不到推理結果 JSON 檔案: {json_path}")
        return

    data = json.loads(json_path.read_text(encoding="utf-8"))
    raw_frames = data.get("frames", [])
    if not raw_frames:
        print("[-] 推理結果檔案包含 0 幀")
        return

    frames = prepare_calibrated_frames(selected["id"], raw_frames)

    print("\n" + "=" * 75)
    print(" 🚀 0901 SMPL-H Fake Sender 即時串流器已啟動")
    print("=" * 75)
    print(f" • 資料集名稱:   {selected['name']}")
    print(f" • 推理結果檔:   {json_path.name} ({len(frames)} 影格)")
    if video_path and video_path.exists():
        print(f" • 視覺化影片:   {video_path.name}")
        print(f"   (完整路徑: {video_path})")
    else:
        print(" • 視覺化影片:   (未指定或跳過)")
    print(f" • 目標位置:     {args.host}:{args.port} (UDP)")
    print(f" • 串流幀率:     {fps:.1f} FPS (間隔 {1000.0/fps:.1f} ms)")
    print(f" • 封包格式:     {args.protocol.upper()} (SMV2 = 1389 Bytes/frame)")
    print(f" • 循環模式:     {'單次播放' if args.single_run else '無限重複循環 (Looping)'}")
    print("=" * 75)
    print("💡 提示：在 Unity 中開啟 '0818 Realtime Protocol V2 UDP Player' 並按 Play，即可同步看到動作與影片！")
    print("串流進行中... 按 Ctrl+C 可隨時停止。\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    frame_interval = 1.0 / max(0.1, fps)
    loop_count = 0
    total_packets = 0

    try:
        while True:
            loop_count += 1
            if video_path and video_path.exists() and not args.no_video:
                send_vide_packet(sock, args.host, args.port, video_path)

            print(f"\n▶ [循環 Loop #{loop_count}] 開始串流 {len(frames)} 影格...")
            loop_start = time.perf_counter()

            for i, frame in enumerate(frames):
                t0 = time.perf_counter()

                if args.protocol in ("smv2", "both"):
                    v2_packet = pack_protocol_v2_frame(frame)
                    sock.sendto(v2_packet, (args.host, args.port))
                    total_packets += 1

                if args.protocol in ("legacy", "both"):
                    legacy_packet = build_legacy_smpj_packet(frame)
                    sock.sendto(legacy_packet, (args.host, args.port))
                    total_packets += 1

                quality = frame.get("quality", {})
                state = quality.get("solverState", "TRACKING")
                fit_res = quality.get("fitResidualMm", 0.0)
                input_valid = quality.get("inputValid", True)

                percent = (i + 1) * 100.0 / len(frames)
                sys.stdout.write(
                    f"\r  [{i+1:03d}/{len(frames):03d} - {percent:4.1f}%] "
                    f"| 狀態: {state:<14} "
                    f"| 殘差: {fit_res:5.1f} mm "
                    f"| 輸入有效: {'✔' if input_valid else '✘'} "
                    f"| 累計封包: {total_packets}"
                )
                sys.stdout.flush()

                elapsed = time.perf_counter() - t0
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

            loop_elapsed = time.perf_counter() - loop_start
            effective_fps = len(frames) / max(loop_elapsed, 1e-6)
            print(f"\n  ✔ 循環 #{loop_count} 結束 (耗時 {loop_elapsed:.2f}s, 實際 FPS: {effective_fps:.1f})")

            if args.single_run:
                break

    except KeyboardInterrupt:
        print("\n\n[!] 使用者中斷串流。")
    finally:
        sock.close()
        print(f"[+] UDP Socket 已關閉。總發送封包數: {total_packets}\n")


if __name__ == "__main__":
    main()
