# SMPL 0901 Live Bridge (to-smpl)

這是一份可獨立放上 GitHub 的「`main_predict` 59 點 3D 關節 → SMPL → Unity」常駐即時轉換服務。它接在 3D 姿態估計管線（`dt-pose`）後面，不負責相機影像 IPC、2D pose 或 DLT；**輸入是已經三角化完成的 `factory_59pt_body_hands` JSON 串流，輸出是 Unity `SMV2` 二進位 UDP 封包**。

> 「0901 最佳版」指目前最適合即時串流的生產策略：固定體型（Fixed Betas）、姿勢 soft-target、跨幀 warm start、root motion 與原始 Hand21 混合驅動。在 GPU 上以 31.9 ms / 31.3 FPS 全速運行，兼顧全身骨架穩定度與手部靈活度。

---

## 1. 系統全景架構圖 (End-to-End Architecture)

本圖清楚展示從工廠相機端到 Unity 3D 數位分身的全鏈路架構，並標註 **本 Repository (`to-smpl`)** 所處的位置（區塊 3）：

```text
+---------------------------------------------------------------------------------------------------+
| 1. 影像擷取與發送端 (Fake Sender / Basler DeepStream)                                             |
|    - 3 視角工業相機 (CAM 41966649, 41966650, 41966651)                                            |
|    - 硬體 PTP 奈秒時間戳 (IEEE 1588 PtpEpochNs)                                                    |
+---------------------------------------------------------------------------------------------------+
       |                                                    |
       | Unix Domain Socket (SCM_RIGHTS / DMA-BUF 零複製)   | Unix Domain Socket (Meta Struct)
       | /tmp/ds_ipc_bridge/{cam_id}.sock                   | /tmp/ds_ipc_bridge/{cam_id}.meta.sock
       ▼                                                    ▼
+---------------------------------------------------------------------------------------------------+
| 2. 即時 3D 姿態估計管線 (LivePosePipeline / dt-pose)                                               |
|                                                                                                   |
|   [CameraReceiver]                                                                                |
|          │                                                                                        |
|          ▼                                                                                        |
|   [PtpFrameJoiner]  ───► 滑動時間窗配對 (±20ms 容差, 支援循環重播/時間戳倒退重置)                 |
|          │                                                                                        |
|          ▼ (JoinedFrameSet: 3 視角同一瞬間影格)                                                    |
|   [TensorRT 2D Pose 推理] (FP16 / GPU)                                                            |
|          ├─► YOLOX-M: 人員方框偵測 (含多人員容錯與信心度主目標挑選)                                |
|          └─► RTMW-x 256x192: 133 點 WholeBody 估計 ──► 擷取 59 點 (Body17 + 雙手 Hand42)         |
|          │                                                                                        |
|          ▼                                                                                        |
|   [3D DLT 幾何三角化] (DLTTriangulator)                                                           |
|          ├─► cv2.undistortPoints: OpenCV 相機內參去畸變 (intri.yml)                               |
|          └─► SVD 最小平方法: 結合相機外參矩陣 P = K[R|T] 求解 3D 空間座標 (extri.yml)             |
|          │                                                                                        |
|          ▼                                                                                        |
|   [FanoutSink 雙向分流]                                                                           |
+---------------------------------------------------------------------------------------------------+
          │                                                                     │
          │ UDP Socket (JSON: factory_59pt_body_hands)                          │ IPC / HTTP API
          │ udp://127.0.0.1:9100                                                │ relative_3d.jsonl + JPEG
          ▼                                                                     ▼
+----------------------------------------------------+   +------------------------------------------+
| 3. SMPL 0901 Bridge (to-smpl) 📍【本 REPO】        |   | 4. 即時 2x2 監看面板 (Dashboard)          |
|                                                    |   |                                          |
|   [Non-blocking Drain Socket Receiver]             |   |   - 3 相機即時影像串流 (10 FPS 預載更新) |
|   (清空排隊舊幀，保持零延遲串流)                   |   |   - 3D Pelvis 根節點人體骨架渲染         |
|          │                                         |   |   - 攝影機視角鎖定 (零晃動/零拉伸)       |
|          ▼                                         |   |   - Web 服務埠號: http://127.0.0.1:8088  |
|   [Fixed Betas 體型校正] (前 10 幀鎖定骨長)        |   +------------------------------------------+
|          │                                         |
|          ▼                                         |
|   [Soft-target GPU 擬合] (PyTorch CUDA, 100 iters) |
|   - 求解 global_orient, body_pose (24 關節四元數)  |
|   - 求解 translation (骨盆 Root Motion)            |
|   - 手部 Wrist-Local 局部座標轉換                  |
|          │                                         |
|          ▼                                         |
|   [Protocol V2 Binary 打包]                        |
+----------------------------------------------------+
          │
          │ UDP Socket (SMV2 二進位高效封包, 1389 Bytes)
          │ udp://127.0.0.1:9095
          ▼
+---------------------------------------------------------------------------------------------------+
| 5. Unity 3D 數位分身播放器 (Unity Hybrid Player)                                                  |
|    - ProtocolV2Decoder: 二進位封包即時解析                                                        |
|    - SMPL Body Pose: 驅動 24 處身體骨骼旋轉與骨盆位移 (Root Motion)                                |
|    - RawHandRetargeter: 驅動雙手 10 根手指靈活動態                                                |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. 輸入資料格式 (Input Stream: UDP 9100)

`to-smpl` 接收由 3D 姿態估計管線發送的 **JSON 格式 59 點 3D 關節資料**：

* **傳輸協定**：UDP Datagram（預設監聽 `udp://0.0.0.0:9100`）。
* **隊列機制**：非阻塞接收（Non-blocking Socket Drain）。每次 GPU 算完一幀，會清空 Socket 緩衝區中堆積的舊封包，只取最新抵達的一筆，確保延遲永遠維持在 ~30ms。
* **資料 Schema**：`factory_59pt_body_hands`

### JSON 結構範例
```json
{
  "schema": "factory_59pt_body_hands",
  "frame_index": 1054,
  "timestamp_s": 1725150000.123,
  "ptp_epoch_ns": 1725150000123456789,
  "keypoints_3d": [
    [-579.69, -852.64, -1332.22],
    [-602.92, -829.20, -1308.17],
    ...
    [653.28, -764.50, -1765.41]
  ],
  "reliable": [true, true, true, ...],
  "reprojection_errors_px": [3.21, 4.05, 2.89, ...],
  "_input_units": "mm",
  "calibration_id": "factory_rig_B_wall_2026_08-manual-relative-v1"
}
```

### 59 點關鍵點拓撲順序 (COCO-WholeBody 59-Point Subset)
| 索引區間 | 部位 | 包含關節 |
| :--- | :--- | :--- |
| **`0..16`** (共 17 點) | **Body17 軀幹與四肢** | `0`: 鼻子, `1, 2`: 左右眼, `3, 4`: 左右耳, `5, 6`: 左右肩, `7, 8`: 左右肘, `9, 10`: 左右手腕, `11, 12`: 左右髖, `13, 14`: 左右膝, `15, 16`: 左右腳踝 |
| **`17..37`** (共 21 點) | **Left Hand 左手** | `17`: 左手腕根部, `18..21`: 拇指, `22..25`: 食指, `26..29`: 中指, `30..33`: 無名指, `34..37`: 小指 |
| **`38..58`** (共 21 點) | **Right Hand 右手** | `38`: 右手腕根部, `39..42`: 拇指, `43..46`: 食指, `47..50`: 中指, `51..54`: 無名指, `55..58`: 小指 |

### 品質閘門保護
* **必要人體關節**：`[0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]` 必須數值非 null。
* **下肢遮擋保護**：若工廠機台遮擋雙腳導致關節為 NaN，系統會自動觸發 `holding the last Unity pose`，使 Unity 角色雙腳穩固站立於地面，上半身與手指持續動態追蹤。

---

## 3. 輸出資料格式 (Output Stream: UDP 9095 to Unity)

`to-smpl` 擬合完成後，打包成 **`Protocol V2 (SMV2)` 高效二進位封包** 送往 Unity：

* **傳輸協定**：UDP Datagram（發送至 `udp://UNITY_HOST:9095`）。
* **封包大小**：固定長度 1389 Bytes（小於標準 Ethernet MTU 1500，保證不拆包零掉包）。
* **二進位結構表**：

| 欄位名稱 | 型態與長度 | 說明 |
| :--- | :--- | :--- |
| **Magic Header** | `char[4]` | 固定為 ASCII 字串 `SMV2` |
| **Frame ID** | `uint32` | 影格流水編號 |
| **Legacy Translation** | `float32[3]` | 相容舊版位移 |
| **SMPL Pose** | `float32[156]` | 52 個關節旋轉軸角 (24 身體 + 28 手指) |
| **Root Position** | `float32[3]` | 骨盆相對於初始錨點的位移 (x, y, z 公尺) |
| **Pelvis World** | `float32[3]` | 世界座標系下的骨盆位置 |
| **Root Rotation** | `float32[4]` | 骨盆全域旋轉四元數 (qx, qy, qz, qw) |
| **Root Confidence**| `float32` | 骨盆估計信心度 |
| **Left Local Joints**| `float32[63]` | 左手 21 點相對於手腕的局部座標 (3D float32 x 21) |
| **Left Confidence** | `float32[21]` | 左手 21 點信心度 |
| **Right Local Joints**| `float32[63]` | 右手 21 點相對於手腕的局部座標 (3D float32 x 21) |
| **Right Confidence**| `float32[21]` | 右手 21 點信心度 |
| **Input Valid** | `uint8` | 1=輸入有效, 0=保持上一姿勢 |
| **Quality Metrics** | `float32[4]` | `inputScore`, `fitResidualMm` (MPJPE), `worstResidualMm`, `torsoOrientationDeg` |
| **Solver State** | `int32` | `TRACKING` (0), `RECOVERED` (1), `HOLD` (4) |
| **Steps Used** | `int32` | 擬合迭代步數 (預設 100) |
| **Reason Mask** | `uint32` | 異常原因位元遮罩 |

---

## 4. 0901 擬合策略與效能

| 方法 | MPJPE 誤差 | Endpoint 誤差 | 軀幹角度偏差 | 單幀耗時 / 幀率 |
| :--- | :---:| :---:| :---:| :---:|
| KAMA 100 iters | 15.35 mm | — | — | 62.8 ms (15.9 FPS) |
| KAMA adaptive | 8.18 mm | — | — | 56.9 ms (17.5 FPS) |
| **Fixed Betas + Soft Target（本版）** | **38.03 mm** | **9.44 mm** | **3.37°** | **31.9 ms / 31.3 FPS (全速即時)** |

### 核心演算法亮點
1. **Fixed Betas 體型鎖定**：前 10 幀擬合一次性身材參數 $\beta$ 後全程鎖定骨長，徹底消除動態辨識時人體骨頭伸縮抖動。
2. **端點加權 Soft-Target**：手腕與腳踝端點賦予 2.5 倍權重，確保工人操作工具與腳踩地面高度貼合。
3. **軀幹法向量約束 (Torso Normal Constraint)**：計算肩-髖法向量，防止工人背對鏡頭時模型發生前後翻轉。
4. **Hybrid 混合骨架驅動**：SMPL 驅動全身 24 處關節四元數，`RawHandRetargeter` 驅動 10 根手指原始幾何。

---

## 5. 快速啟動指南

### 步驟 1：啟動 SMPL 0901 Bridge
```bash
# 在 to-smpl 目錄下啟動
smpl-0901-bridge \
  --input udp://0.0.0.0:9100 \
  --smpl-dir /home/chiayu/iii/to-smpl/models \
  --device cuda \
  --unity-host 127.0.0.1 \
  --unity-port 9095
```

### 步驟 2：啟動 Pipeline 推送串流 (已內建於 run-gx10.sh)
```bash
cd /home/chiayu/iii/digital-twin-pose
./deploy/live_pipeline/run-gx10.sh
```

### 步驟 3：Unity 端一鍵對接
1. Unity 開啟專案，將 `unity/CustomSMPL` 複製至專案的 `Assets/CustomSMPL`。
2. 點選 Unity 上方選單：**CustomSMPL → Setup 0901 Live Bridge Player**。
3. 按下 **Play**，元件將自動綁定 UDP `9095` 埠號，以 30 FPS 即時驅動 3D 數位分身角色與 10 指抓握動態！
