# 工業數位分身 3D 人體姿態估計與 SMPL 即時串流系統架構

本文件詳細說明從 **影像擷取（Fake Sender / Basler DeepStream）** 到 **3D 姿態估計（Pipeline）**、**SMPL 人體模型擬合（to-smpl）**、**即時儀表板監控（Dashboard）** 以及 **Unity 3D 數位分身播放** 的完整系統架構、通訊協定、內部運算流程與封包格式。

---

## 1. 系統全景架構圖 (End-to-End System Architecture)

![工業數位分身即時姿態與 SMPL 系統架構](docs/digital-twin-system-architecture.svg)

資料主路徑為：**三視角影像 → `dt-pose` → UDP 9100 JSON → `smpl-0901-bridge`**，Bridge 再平行輸出 **UDP 9095 SMV2（擬合結果）** 與 **UDP 9096 RSV1（原始 59 點骨架）**。Dashboard 是由 Pipeline artifacts 分出的唯讀觀測支線，不介入 SMPL 擬合。

---

## 2. 各模組運作細節與通訊協定

### 階段一：影像擷取與發送端 (Fake Sender / Basler DeepStream)

發送端負責驅動 3 台工業相機（或重放工廠標準錄影），並將影像與時間戳以兩條獨立通道送入 IPC：

1. **影像傳輸通道（Image IPC Socket）**：
   * **路徑**：`/tmp/ds_ipc_bridge/{camera_id}.sock`
   * **協定**：GStreamer `nvunixfdsink` 搭配 Linux Unix Domain Socket（`SCM_RIGHTS`）。
   * **機制**：直接傳遞 GPU 顯存的 DMA-BUF 檔案描述子（NVMM NV12 格式），**達到 0% CPU 複製開銷的極限傳輸速度**。
2. **時間戳側通道（Metadata Side-Channel Socket）**：
   * **路徑**：`/tmp/ds_ipc_bridge/{camera_id}.meta.sock`
   * **協定**：二進位固定長度結構體（每筆 40 Bytes）。
   * **資料欄位**：
     * `pts_ns` (`uint64`): GStreamer 緩衝區的時間戳。
     * `frame_id` (`uint64`): 硬體影格流水號。
     * `ptp_epoch_ns` (`uint64`): IEEE 1588 PTP 硬體同步時間戳（精確至奈秒）。
     * `host_ts_ns` (`uint64`): 主機接收系統時間。
     * `device_temp` (`float32`): 相機硬體感測器溫度。

---

### 階段二：3D 姿態估計管線 (LivePosePipeline / dt-pose)

Pipeline 是整個系統的幾何與神經網路運算核心：

1. **多相機時間窗對齊 (`PtpFrameJoiner`)**：
   * 3 台相機以非同步方式獨立推送影格。
   * Joiner 維護一個 `±1ms` 的滑動時間窗，自動將 PTP 時間戳最接近的 3 視角影格結合成一個 `JoinedFrameSet`。
   * **循環重播自適應（Stream Rewind Detection）**：當偵測到時間戳倒退（`> 200ms`，例如影片循環播放或發送端重啟），會自動清空舊佇列並重置水位線，確保串流永不中斷。
2. **2D 人體與手部姿態估計 (TensorRT FP16)**：
   * **第一階段（人體偵測）**：`YOLOX-M` 進行即時目標方框偵測。若背景機具反光產生多個候選框，系統自動挑選最高信心度的主目標（Primary Person），避免誤判中斷。
   * **第二階段（關鍵點估計）**：`RTMW-x 256x192` 進行 Top-down 全身關鍵點回歸，產出 COCO-WholeBody 133 點，並擷取其中的 **59 點精簡子集（Body17 + 左手21 + 右手21）**。
3. **光學去畸變與 3D DLT 三角化 (`DLTTriangulator`)**：
   * 根據各相機內參 $K$ 與畸變參數 $D$（`intri.yml`），呼叫 `cv2.undistortPoints` 去除廣角鏡頭桶狀/枕狀畸變。
   * 結合外參旋轉平移矩陣 $[R \mid T]$（`extri.yml`），建立投影矩陣 $P = K [R \mid T]$。
   * 透過 SVD 奇異值分解最小平方法（Direct Linear Transform），求出 59 個關節的世界座標 $(X, Y, Z)$ 與重投影誤差。
4. **雙向分流 (`FanoutSink`)**：
   * **分流 A**：透過 UDP `9100` 即時傳送 JSON 給 SMPL Bridge。
   * **分流 B**：輸出 `relative_3d.jsonl` 與 JPEG 預覽給 Dashboard 前端。

---

### 階段三：SMPL 0901 Bridge 人體網格擬合 (to-smpl)

SMPL Bridge 是將 59 點 3D 骨架轉換為工業數位分身（SMPL Mesh）與驅動 Unity 的核心服務：

#### 1. 輸入串流規格 (Input: UDP 9100)
* **通訊方式**：UDP Datagram Socket（`udp://0.0.0.0:9100`）。
* **即時隊列機制**：非阻塞接收（Non-blocking Drain），處理新幀前自動排空累積的舊封包，**永遠只處理最新到達的一筆，延遲穩定維持在 ~30ms**。
* **輸入 JSON 格式 (`factory_59pt_body_hands`)**：
  ```json
  {
    "schema": "factory_59pt_body_hands",
    "frame_index": 1054,
    "timestamp_s": 1725150000.123,
    "ptp_epoch_ns": 1725150000123456789,
    "keypoints_3d": [
      [-579.69, -852.64, -1332.22],
      ... (共 59 點 [x, y, z] 座標)
    ],
    "reliable": [true, true, ...],
    "reprojection_errors_px": [3.21, 4.05, ...],
    "_input_units": "mm",
    "coordinate_frame": "factory_rig_B_world"
  }
  ```

#### 2. 59 點關鍵點拓撲定義表
| 索引區間 | 部位 | 包含關節 |
| :--- | :--- | :--- |
| **`0..16`** (共 17 點) | **Body17 軀幹與四肢** | 0: 鼻子, 1-2: 左右眼, 3-4: 左右耳, 5-6: 左右肩, 7-8: 左右肘, 9-10: 左右手腕, 11-12: 左右髖, 13-14: 左右膝, 15-16: 左右腳踝 |
| **`17..37`** (共 21 點) | **Left Hand 左手** | 17: 左手腕根部, 18-21: 拇指, 22-25: 食指, 26-29: 中指, 30-33: 無名指, 34-37: 小指 |
| **`38..58`** (共 21 點) | **Right Hand 右手** | 38: 右手腕根部, 39-42: 拇指, 43-46: 食指, 47-50: 中指, 51-54: 無名指, 55-58: 小指 |

#### 3. 擬合演算法 (Fixed Betas + Soft-Target Optimization)
* **前 10 幀固定身形（Fixed Betas）**：收集前 10 幀估計出一組工人體型參數 $\beta$，後續全程鎖定骨長，消除動態估計時人體骨頭長度忽長忽短的抖動。
* **姿勢 Soft-Target 求解**：以骨盆為錨點，在 GPU 上進行 100 次梯度迭代（~31.9 ms / 31.3 FPS），求解出：
  * `global_orient`：人體朝向旋轉。
  * `body_pose`：23 個身體關節的局部旋轉四元數。
  * `translation`：骨盆相對於初始點的世界平移位移（Root Motion）。
* **手部座標局部化**：將 42 個手指點轉換為相對於各自手腕的局部座標（`wrist-local`）。

#### 4. 輸出串流規格（Output Streams）

##### SMPL Protocol V2（UDP 9095 to Unity）
* **通訊方式**：UDP Datagram Socket（`udp://UNITY_HOST:9095`）。
* **協定格式**：**`Protocol V2 (SMV2)` 高效二進位封包**：
  ```
  +--------------+-------------+---------------+-------------------+---------------------+--------------------+-----------------+
  | Magic Header | Version/Flg | Timestamp(ms) | Root Translation  | 24 Joint Quats      | 42 Hand Keypoints  | Quality Metrics |
  | (ASCII 4B)   | (uint16 2B) | (uint64 8B)   | (float32 x 3 =12B)| (float32 x 96 =384B)| (float32 x 126=504B)| (float32 x 4=16B)|
  +--------------+-------------+---------------+-------------------+---------------------+--------------------+-----------------+
  總封包大小：固定 1389 Bytes（極小頻寬開銷）
  ```

##### Raw Skeleton V1（RSV1，UDP 9096）
* **送出時機**：Bridge 成功解析 UDP 9100 JSON 後立即送出，早於單位轉換、軸向映射、品質閘門與 SMPL 擬合。
* **用途**：讓獨立 receiver 取得未經 SMPL 改寫的原始 59×3 空間點；SMPL 被拒絕的幀仍可送出 RSV1。
* **固定封包**：little-endian，共 **1032 Bytes**。

| 欄位 | 型態 | 說明 |
| :--- | :--- | :--- |
| Magic / Version / Flags | `char[4]` + `uint16` + `uint16` | `RSV1`、版本 1；flags bit 0 表示來源具有精確 PTP |
| Frame ID / PTP timestamp | `uint32` + `uint64` | 輸入 frame index 與 epoch ns |
| Unit | `uint8` + 3-byte padding | `0=unknown`、`1=m`、`2=mm` |
| Coordinate frame | `char[64]` | UTF-8、NUL padding |
| Raw keypoints | `float32[59][3]` | 原始座標；無效關節可為 `NaN` |
| Confidence | `float32[59]` | `[0,1]`；目前由 reliable 映射為 1/0 |

預設 RSV1 目的主機沿用 `--unity-host`、port 為 `9096`；指定 `--raw-skeleton-port 0` 可停用。UDP 9095 與 9096 互不依賴。

---

### 階段四：Unity 3D 數位分身播放器 (Unity Hybrid Player)

Unity 端接收到二進位封包後，透過混合骨架系統（Hybrid Player）進行高真實度重現：

1. **ProtocolV2Decoder**：接收 UDP 9095 封包並快速解析出四元數旋轉與手部座標。
2. **Raw Skeleton receiver（選用）**：獨立監聽 UDP 9096 並解析 RSV1，可顯示或記錄未擬合的 59 點骨架；既有 Unity 元件尚不會自動解析此埠。
3. **SMPL 身體驅動**：將 24 個關節的旋轉四元數套用至 SMPL-H 骨架階層，骨盆平移套用至 Root Motion。
4. **RawHandRetargeter 手指驅動**：利用 Wrist-Local 42 點原始手部幾何，直接映射並驅動 10 根手指關節，保留細緻的工件抓握手勢。

---

### 階段五：即時 2x2 監看儀表板 (Dashboard Observer)

* **存取位址**：`http://127.0.0.1:8088/?token=...`
* **畫面配置（2x2 網格零滾動設計）**：
  * **Slot 1 (左上)**：CAM 41966649 即時畫面與 2D 骨架疊加。
  * **Slot 2 (右上)**：CAM 41966650 即時畫面與 2D 骨架疊加。
  * **Slot 3 (左下)**：CAM 41966651 即時畫面與 2D 骨架疊加。
  * **Slot 4 (右下)**：**3D Pelvis 根節點直立人體骨架 ＋ 3D 地面透視網格 ＋ 系統延遲與 SMPL 連線狀態**。
* **技術亮點**：
  * **骨盆根節點渲染（Pelvis-Rooted）**：骨架穩定置於視角中央，徹底消除攝影機晃動與爆點拉伸。
  * **離屏預載（Offscreen Preload）**：三台相機畫面無撕裂同步刷新。

---

## 3. 完整啟動指令對照表

請在各自獨立的終端機執行：

### 終端機 1：啟動 SMPL 0901 Bridge
```bash
smpl-0901-bridge \
  --input udp://0.0.0.0:9100 \
  --smpl-dir /home/chiayu/iii/to-smpl/models \
  --device cuda \
  --unity-host 127.0.0.1 \
  --unity-port 9095 \
  --raw-skeleton-host 127.0.0.1 \
  --raw-skeleton-port 9096
```

#### Docker 替代啟動方式
```bash
cd /home/chiayu/iii/to-smpl
sudo UNITY_HOST=192.168.200.1 docker compose up --build
```

SMPL models 由 `./models` 唯讀掛載至容器 `/models`；Compose 使用 host network 與 NVIDIA GPU runtime，不會啟動其他系統模組。

### 終端機 2：啟動 Fake Sender（發送端）
```bash
cd /home/chiayu/projects/human-pose-sender/fake_sender_gx10
sudo CAMS_DIR=/home/renn/digital-twin-data/Session_20260824_025005 ./build_and_run-gx10.sh
```

### 終端機 3：啟動 Live Pipeline（姿態估計管線）
```bash
cd /home/chiayu/iii/digital-twin-pose
./deploy/live_pipeline/run-gx10.sh
```

### 終端機 4：啟動 Dashboard（監控面板）
```bash
cd /home/chiayu/iii/digital-twin-pose
./deploy/dashboard/run-gx10.sh
```
開啟瀏覽器連線至腳本印出的 `http://127.0.0.1:8088/?token=...` 即可進行即時監控。
