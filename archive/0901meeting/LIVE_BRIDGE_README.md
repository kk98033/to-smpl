# 即時 59 關節 → 0901 SMPL → Unity

## 資料流

```text
fake/正式 sender（三相機影像 + metadata）
  -> dt-pose receiver + 組幀 + RTMW + 3D
  -> factory_59pt_body_hands JSON frame
  -> live_smpl_unity_bridge.py
  -> SMV2 UDP 9095
  -> Unity「CustomSMPL/0818 Realtime Protocol V2 UDP Player」
```

`deploy/ipc_receiver/run-gx10.sh` 目前只跑 `dt_pose.transport.smoke`，預設 10 秒後結束；它驗證三路 CUDA IPC 影像與 metadata，並不執行 RTMW、3D、SMPL，也不是常駐服務。

## 建議的接收方式

同一台 Linux/DGX 上，使用 Unix datagram：`unix:///tmp/dt_pose_3d.sock`。它保留一幀一訊息的邊界、不需要額外套件、不開網路 port。sender 是 non-blocking；bridge 每次擬合前會排空 backlog、只保留最新完整幀，因此 SMPL 不會反壓相機推論。

若 3D producer 與 bridge 不在同一台機器，改用 `udp://0.0.0.0:9100`。正式環境若要求可靠重連、身分驗證或跨網段，再把這一小段換成 ZeroMQ PUB/SUB；Unity 端仍維持既有 SMV2 UDP。

## 啟動

先在 Unity 選單點：

```text
CustomSMPL > 0818 Realtime Protocol V2 UDP Player
```

Unity 按 Play 後，在 DGX 啟動 bridge（Unity 在另一台機器時把 IP 改成該電腦 IP）：

```bash
python main/0901meeting/live_smpl_unity_bridge.py \
  --input unix:///tmp/dt_pose_3d.sock \
  --input-units m \
  --axis-map x,-y,z \
  --unity-host 192.168.1.50 \
  --unity-port 9095
```

目前 `main_predict` 的 factory DLT 產物是 `[59,3]` 的 `keypoints_3d`；舊版組員 JSON 是 `keypoint_3d` 字典且通常為 mm，因此舊資料請用 `--input-units mm`。`--axis-map` 必須用正式標定座標系確認；預設值適用 x-right/y-down/z-forward 相機座標。

用現有 JSONL 做端到端測試：

```bash
python main/0901meeting/send_joint_frame.py \
  path/to/factory_59pt_keypoints.jsonl \
  --destination unix:///tmp/dt_pose_3d.sock --fps 30
```

## 接到組員的 live loop

在組員產生單幀 3D 結果的位置加入：

```python
from send_joint_frame import send_record

send_record(
    {
        "frame_id": frame_index,
        "timestamp": timestamp_seconds,
        "schema": "factory_59pt_body_hands",
        "keypoints_3d": points_3d.tolist(),       # [59,3]
        "reliable": reliable.astype(bool).tolist(), # [59]，可省略
    },
    "unix:///tmp/dt_pose_3d.sock",
)
```

Bridge 會先收 10 個有效幀估計並鎖定同一人的 betas；校正完成後，每幀用 0901 的 fixed-betas soft-target/torso constraint 擬合身體。手部走新版 hybrid：SMPL 驅動 body，兩組 Hand21 交給 Unity `RawHandRetargeter`，避免用 3D 點硬猜 90 維手指 axis-angle。
