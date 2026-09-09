# SMPL 0901 Live Bridge (to-smpl)

這是一份可獨立放上 GitHub 的「`main_predict` 59 點 3D 關節 → SMPL → Unity」常駐即時轉換服務。它接在 3D 姿態估計管線（`dt-pose`）後面，不負責相機影像 IPC、2D pose 或 DLT；**輸入是已完成 3D 預測的 JSON 串流，原生支援新版 `dt-pose.pose3d/v1` 並向後相容 `factory_59pt_body_hands`；Bridge 平行輸出 Unity `SMV2`（UDP 9095）與原始 59 點 `RSV1`（UDP 9096）二進位封包**。

> 生產策略使用固定體型（Fixed Betas）、姿勢 soft-target、跨幀 warm start、root motion 與原始 Hand21 混合驅動。工廠畫面下半身常受遮擋時，Compose 預設採 `upper-body` 模式，避免不可信的膝／腳踝把全身擬合拉壞。

---

## 1. 系統全景架構圖 (End-to-End Architecture)

本圖清楚展示完整資料流；橘色框標示 **本 Repository (`to-smpl`)** 的責任邊界：監聽 UDP 9100、接收 59 點 JSON，將原始骨架以 RSV1 送往 UDP 9096，並執行 SMPL 擬合後將 SMV2 送往 Unity UDP 9095。

![工業數位分身即時姿態與 SMPL 系統架構](docs/digital-twin-system-architecture.svg)

公司部署與維運請見 [Docker 部署手冊](docs/DOCKER_DEPLOYMENT.md)；輸入 JSON、SMV2、RSV1 byte offset 與 CLI 合約請見 [UDP API 文件](docs/UDP_API.md)；不開 Pipeline／Bridge 單獨測 Unity 請見 [Unity Fake Sender](docs/UNITY_FAKE_SENDER.md)。

---

## 2. 輸入資料格式 (Input Stream: UDP 9100)

`to-smpl` 接收由 3D 姿態估計管線發送的 **JSON 格式 59 點 3D 關節資料**：

* **傳輸協定**：UDP Datagram（預設監聽 `udp://0.0.0.0:9100`）。
* **隊列機制**：非阻塞接收（Non-blocking Socket Drain）。每次 GPU 算完一幀，會清空 Socket 緩衝區中堆積的舊封包，只取最新抵達的一筆，確保延遲永遠維持在 ~30ms。
* **資料 Schema**：`dt-pose.pose3d/v1`（新版）或 `factory_59pt_body_hands`（舊版相容）

### JSON 結構範例
```json
{
  "schema": "dt-pose.pose3d/v1",
  "source": "rig_b",
  "frame": 1054,
  "timestamp_ns": 1725150000123456789,
  "units": "m",
  "layout": "factory59",
  "joints": [
    [-0.580, -0.853, -1.332],
    [-0.603, -0.829, -1.308],
    ...
    [0.653, -0.765, -1.765]
  ],
  "single_person": true
}
```

### 59 點關鍵點拓撲順序 (COCO-WholeBody 59-Point Subset)
| 索引區間 | 部位 | 包含關節 |
| :--- | :--- | :--- |
| **`0..16`** (共 17 點) | **Body17 軀幹與四肢** | `0`: 鼻子, `1, 2`: 左右眼, `3, 4`: 左右耳, `5, 6`: 左右肩, `7, 8`: 左右肘, `9, 10`: 左右手腕, `11, 12`: 左右髖, `13, 14`: 左右膝, `15, 16`: 左右腳踝 |
| **`17..37`** (共 21 點) | **Left Hand 左手** | `17`: 左手腕根部, `18..21`: 拇指, `22..25`: 食指, `26..29`: 中指, `30..33`: 無名指, `34..37`: 小指 |
| **`38..58`** (共 21 點) | **Right Hand 右手** | `38`: 右手腕根部, `39..42`: 拇指, `43..46`: 食指, `47..50`: 中指, `51..54`: 無名指, `55..58`: 小指 |

### 品質閘門與遮擋模式

* `--fit-profile full`：使用 Body25 `0..14`，包含髖、膝與腳踝；適合全身清楚可見的資料。
* `--fit-profile upper-body`：只使用鼻、頸、雙臂與骨盆 Body25 `0..9,12`。膝與腳踝不進 loss，下肢 SMPL rotation 保持上一幀（首次為自然零姿勢），上半身仍持續追蹤。Docker Compose 預設使用此模式。
* 每個 Body25 target 使用輸入 `reliable/confidence` 加權；有提供品質資料的來源不再讓低可信度關節與可靠關節等權影響 loss。
* 部署預設 `--endpoint-weight 0.5`、`--torso-weight 0.05` 與 `--spine-stability-weight 0.02`。三節 spine 保留彎曲能力但會被拉回自然 rest rotation；neck、head 與左右 wrist 的 local rotation 固定為零，讓頭頸跟隨胸口向前，手掌根節點跟隨前臂，避免關節位置 loss 無法觀測的軸向 twist。
* `--robust-huber` 可手動啟用，但不作部署預設；本機歷史資料測試顯示 squared loss 收斂較準，Huber 僅適合已確認有少數極端離群點時。

---

## 3. 輸出資料格式 (Output Stream: UDP 9095 to Unity)

`to-smpl` 擬合完成後，打包成 **`Protocol V2 (SMV2)` 高效二進位封包** 送往 Unity：

* **傳輸協定**：UDP Datagram（發送至 `udp://UNITY_HOST:9095`）。
* **封包大小**：固定長度 1389 Bytes（小於常見 Ethernet MTU 1500，通常不需 IP fragmentation；UDP 本身不保證送達）。
* **二進位結構表**：

| 欄位名稱 | 型態與長度 | 說明 |
| :--- | :--- | :--- |
| **Magic Header** | `char[4]` | 固定為 ASCII 字串 `SMV2` |
| **Frame ID** | `uint32` | 影格流水編號 |
| **Legacy Translation** | `float32[3]` | 相容舊版位移 |
| **SMPL Pose** | `float32[156]` | 52×3 軸角 slots；目前 body 使用前 66 floats，雙手另由 Hand21 驅動 |
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

### Raw Skeleton V1（RSV1，UDP 9096）

Bridge 一收到並成功解析 UDP 9100 JSON，就會在任何單位轉換、軸向映射、品質閘門或 SMPL 擬合之前，將原始 59 點平行送至 `udp://RAW_SKELETON_HOST:9096`。因此即使該幀之後被 SMPL 品質閘門拒絕，RSV1 仍可供獨立接收器記錄或視覺化。

| 欄位名稱 | 型態與長度 | 說明 |
| :--- | :--- | :--- |
| **Magic Header** | `char[4]` | 固定為 ASCII `RSV1` |
| **Version** | `uint16` | 協定版本，目前為 `1` |
| **Flags** | `uint16` | bit 0：`ptp_epoch_ns` 為來源提供的精確 PTP；否則為時間戳回退值 |
| **Frame ID** | `uint32` | 對應輸入 JSON 的 `frame_index` |
| **PTP Epoch** | `uint64` | 奈秒級 epoch timestamp |
| **Unit** | `uint8` + 3 bytes padding | `0=unknown`、`1=m`、`2=mm` |
| **Coordinate Frame** | `char[64]` | UTF-8、NUL padding，來源座標系名稱 |
| **Raw Keypoints** | `float32[59][3]` | 輸入的原始 59×3 座標；無效關節可為 `NaN` |
| **Confidence** | `float32[59]` | 每點信心度 `[0,1]`；目前由 `reliable` 映射為 `1.0/0.0` |

RSV1 固定為 little-endian、封包大小 **1032 Bytes**，小於標準 Ethernet MTU。預設目標主機沿用 `--unity-host`，`--raw-skeleton-port 0` 可停用；此輸出不取代也不改變既有 UDP 9095 SMV2。

---

### 真實 SMPL 擬合診斷 JSONL

指定 `--fit-jsonl PATH` 時，Bridge 每個成功的 SMPL frame 會追加一筆 `smpl-0901.fit/v1`。內容包括同一 `frame` 的 `target_factory59`、`target_body25`、實際 SMPL model 的 `fitted_smpl24`、Body25 regressor 的 `fitted_body25`、逐關節 residual 與真實 `fit_residual_mm`。整合 Dashboard 使用這份資料，不再在瀏覽器內用固定骨長偽造 SMPL 骨架。
每筆診斷也包含最差 Body25 target、SMPL24 local rotation、沿主要子骨軸的 twist、相對上一幀的 geodesic rotation jump、輸入上半身／腳掌水平朝向差與超標關節清單。fitter 另以 `SMPL_SPINE_STABILITY_WEIGHT=0.02` 抑制 spine1/2/3 的無法觀測軸向扭轉，並將 neck、head、左右 wrist 固定於相對父關節的自然朝前姿勢；再以預設 `SMPL_BODY_FACING_WEIGHT=0.01` 的 facing alignment loss（輸入先以 determinant +1 的 `x,-y,-z` proper rotation 轉換，避免單軸鏡射造成不可解的左右手性），防止 pelvis／腿朝後而上半身反弓來換取低關節位置誤差。

指定 `--mesh-preview-json PATH` 時，Bridge 會以 atomic replace 維護一份最新候選 frame 的 `smpl-0901.mesh-preview/v1`，包含真正 SMPL forward surface 的 vertex-cluster 簡化後的 compact vertices 與連續 faces，並以 `accepted` 標示是否通過安全門檻。預設 `--mesh-preview-faces 2400`，供 Dashboard 除錯而不讓 append-only JSONL 快速膨脹；此檔案不是 UDP 協定，也不影響 Unity 輸出。

Bridge 預設每 10 個成功 fit 輸出一筆 `[bridge] distortion {JSON}` structured log；以 `SMPL_DIAGNOSTIC_LOG_EVERY` 調整 Compose 間隔，`1` 表示每幀，`0` 停用。候選姿勢若超過 MPJPE 100 mm、任一關節 twist 100°、單幀 rotation delta 90°，或上半身／腳掌水平朝向差 90°，Bridge 會記錄 `accepted:false`、`action:"hold_previous"`，且不更新已接受的 fitting 狀態；但仍會將同一候選用 SMV2 送出，並標記 `inputValid=false`、`FAILED_HOLD` 與拒絕原因。新版 Unity 的 `Show Held Fit` 預設開啟，會顯示這份與 Dashboard 相同的候選結果；關閉後則採嚴格模式並保留上一個正常姿勢。四個門檻可分別用 `SMPL_MAX_FIT_RESIDUAL_MM`、`SMPL_MAX_TWIST_DEG`、`SMPL_MAX_DELTA_DEG`、`SMPL_MAX_FACING_MISMATCH_DEG` 調整，設為 `0` 可個別停用。

## 4. 0901 擬合策略與效能

以下是舊版離線資料的歷史基準，**不是目前遮擋影片的線上保證值**；實際品質請看 Bridge/Unity 的 `fitResidualMm`。

| 方法 | MPJPE 誤差 | Endpoint 誤差 | 軀幹角度偏差 | 單幀耗時 / 幀率 |
| :--- | :---:| :---:| :---:| :---:|
| KAMA 100 iters | 15.35 mm | — | — | 62.8 ms (15.9 FPS) |
| KAMA adaptive | 8.18 mm | — | — | 56.9 ms (17.5 FPS) |
| **Fixed Betas + Soft Target（本版）** | **38.03 mm** | **9.44 mm** | **3.37°** | **31.9 ms / 31.3 FPS (全速即時)** |

### 核心演算法亮點
1. **Fixed Betas 體型鎖定**：預設收集 30 個通過目前 profile 品質閘門的 frame，估計一次性身材參數 $\beta$，並將每個係數限制在 `[-3,3]`，避免遮擋點被永久吸收到體型。
2. **遮擋友善 Soft-Target**：`upper-body` 模式不使用膝／腳踝 target；`full` 模式才對手腕與腳踝增加端點權重。
3. **軀幹法向量與 Spine 穩定**：計算肩-髖法向量，並正則化 spine1/2/3；neck、head 固定朝向胸口前方，避免前後翻轉及沿骨軸扭曲。
4. **Hybrid 混合骨架驅動**：SMPL 驅動身體至前臂，左右 wrist 使用自然零旋轉跟隨前臂；原始 Hand21 wrist-local 幾何與 ROM 限制驅動 10 根手指。

---

## 5. Docker（NVIDIA GB10 / ARM64）

Docker image 使用支援 GB10／Blackwell `sm_12x` 的 NVIDIA PyTorch base，SMPL 模型不會複製進 image；執行時以唯讀方式掛載 `models/`。Compose 使用 host network，讓 Pipeline 繼續送到 host UDP 9100，Bridge 也能直接將 9095/9096 送往 Unity。

本節提供快速啟動；公司主機的完整前置需求、模型目錄、GPU 驗證、網路規則、日常維運、更新方式與問題排查請依照 [Docker 部署手冊](docs/DOCKER_DEPLOYMENT.md)。

必要條件：Docker、Docker Compose、NVIDIA Container Toolkit。第一次建置會下載數 GB 的 NGC base image。

執行前置檢查與映像檔建置腳本：

```bash
cd /path/to/to-smpl
./prepare-gx10.sh
```

（該腳本會檢查必要 SMPL 模型是否存在並執行 `docker compose build`）

`UNITY_HOST` 不參與 image 建置；同一份 image 可部署到不同機器。啟動時才指定 Unity PC 的實際 LAN 或 VPN IPv4：

```bash
cd /path/to/to-smpl
sudo UNITY_HOST=192.168.200.1 docker compose up

# 工廠下半身遮擋（Compose 預設）
sudo UNITY_HOST=192.168.200.1 \
  SMPL_FIT_PROFILE=upper-body \
  docker compose up -d --build --force-recreate bridge

# 全身清楚可見時
sudo UNITY_HOST=192.168.200.1 \
  SMPL_FIT_PROFILE=full \
  docker compose up -d --force-recreate bridge
```

若 Unity 與 Bridge 在同一台主機，使用 loopback：

```bash
sudo UNITY_HOST=127.0.0.1 docker compose up
```

若未設定 `UNITY_HOST`，容器會在啟動時立即停止並顯示設定提示，不會把目的位址寫死或誤送到其他主機。Unity 接收端須監聽 `0.0.0.0:9095`（SMV2）及 `0.0.0.0:9096`（RSV1）。

停止可按 `Ctrl+C`；SMPL models 預設由 `./models` 掛載到容器 `/models:ro`。若 models 位於別處：

```bash
sudo UNITY_HOST=192.168.200.1 \
  SMPL_MODELS_DIR=/absolute/path/to/models \
  docker compose up
```

> 此 Compose 不設定自動重啟，也不會操作 Pipeline、Fake Sender 或 Dashboard。

Bridge 沒有 HTTP/REST API；三個 UDP 介面的正式合約與 decoder 說明請見 [UDP API 文件](docs/UDP_API.md)。

---

## 6. 快速啟動指南

### 步驟 1：啟動 SMPL 0901 Bridge
```bash
# 在 to-smpl 目錄下啟動
smpl-0901-bridge \
  --input udp://0.0.0.0:9100 \
  --smpl-dir /path/to/to-smpl/models \
  --device cuda \
  --unity-host 127.0.0.1 \
  --unity-port 9095 \
  --raw-skeleton-host 127.0.0.1 \
  --raw-skeleton-port 9096 \
  --fit-profile upper-body \
  --calibration-frames 30 \
  --beta-limit 3 \
  --fit-jsonl artifacts/live/smpl_fit.jsonl
```

### 步驟 2：啟動 Pipeline 推送串流 (已內建於 run-gx10.sh)
```bash
cd /path/to/digital-twin-pose
./deploy/live_pipeline/run-gx10.sh
```

### 步驟 3：Unity 端一鍵對接
1. 將 `unity/SMPL0901Player` 複製到 Unity 專案的 `Assets/SMPL0901Player`；舊版 `CustomSMPL` 不需修改。
2. 點選 Unity 上方選單：**SMPL 0901 → Create Live Player in Scene**。
3. 按下 **Play**。播放器預設接受 Server IP `192.168.1.250`，同時監聽 UDP `9095`（SMV2）與 `9096`（RSV1）。

播放器採 Hybrid 驅動：SMPL 負責身體至前臂，wrist 固定自然 local rotation 跟隨前臂，原始 Hand21 負責手指彎曲與張開。Runtime UI 可修改 Server IP 與兩個 Port，並分別開關 SMPL Mesh、SMPL 反推骨架和原始 59 點骨架。完整操作方式見 [`unity/SMPL0901Player/README.md`](unity/SMPL0901Player/README.md)。

## 專案結構

```text
smpl_0901/                 Python 常駐 bridge、fitter 與二進位協定
docs/UNITY_FAKE_SENDER.md  Conda 錄製／重播 Unity SMV2 + RSV1
models/                    Body25 regressor 與 SMPL 模型
unity/SMPL0901Player/      獨立的 SMV2/RSV1 Hybrid Unity 播放器
unity/CustomSMPL/          舊版播放器參考副本
tests/                     輸入 schema 與 Python/Unity protocol contract 測試
```
