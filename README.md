# SMPL 0901 Live Bridge

這是一份可獨立放上 GitHub 的「`main_predict` 59 點 3D 關節 → SMPL → Unity」常駐轉換服務。它接在組員的 3D 預測後面，不負責相機影像 IPC、2D pose 或 DLT；輸入是已經三角化完成的 `factory_59pt_body_hands`，輸出是 Unity `SMV2` UDP 封包。

> 「0901 最佳版」指目前最適合即時串流的生產策略：固定體型、姿勢 soft-target、跨幀 warm start、root motion 與原始 Hand21 混合驅動。它是速度／穩定性／全身觀感的選擇，不代表離線 benchmark 中單看 MPJPE 最低的實驗。

## 流程

```text
main_predict / factory_59pt_dlt_demo
  └─ 59×3 joints（Body17 + Left Hand21 + Right Hand21）
       └─ SMPL 0901 bridge
            ├─ Body17 → Body25 soft targets → SMPL pose + fixed betas
            ├─ Hand21 → wrist-local raw hand joints
            └─ root displacement + quality → SMV2 binary UDP :9095
                 └─ Unity hybrid player
                      ├─ SMPL 驅動身體
                      └─ RawHandRetargeter 驅動手指
```

## 0901 策略紀錄

1. **一次校正體型**：啟動後收集前 10 個有效 frame，以 100 iteration 估計一組 `betas`；後續固定 betas，避免每幀身材改變造成骨架抖動。
2. **每幀 soft-target fitting**：Body17 先映射為 OpenPose Body25，pelvis 歸零後最佳化 SMPL `global_orient + body_pose + translation`。預設 100 iteration。
3. **重點關節加權**：手腕、腳踝等 endpoint 權重 `2.5`；torso normal 方向權重 `1.5`；跨幀 pose smoothness `0.01`。
4. **Warm start**：第一幀用肩／髖方向解析初始化 root；之後沿用上一幀 root、body pose、translation，提升速度與連續性。
5. **Root motion**：以串流第一個有效 pelvis 為 anchor，只送相對位移，Unity 不會跳到相機世界座標。
6. **Hybrid body/hand**：SMPL pose 只負責 pelvis、身體與手腕；兩手保留 `main_predict` 的原始 21 點，轉成 wrist-local 後交給 Unity `RawHandRetargeter`。這就是新版播放器的 hybrid 套骨架方式。
7. **品質閘門**：可讀 `reliable`，或使用 `reprojection_errors_px <= 120`；身體必要點不完整時丟棄該 frame，Unity 保持上一姿勢。即時 socket 會清掉排隊的舊 frame，只算最新姿勢。

0901 當時的比較紀錄如下；數字用來說明取捨，不應混稱為同一種「準確度」：

| 方法 | MPJPE | Endpoint | Torso angle | 單幀時間 |
|---|---:|---:|---:|---:|
| KAMA 100 | 15.35 mm | — | — | 62.8 ms |
| KAMA adaptive | 8.18 mm | — | — | 56.9 ms |
| **Fixed Betas + Soft Target（本版）** | 38.03 mm | 9.44 mm | 3.37° | **31.9 ms / 31.3 FPS** |

本版選擇最後一列，原因是即時系統需要固定骨長、穩定方向、手腳 endpoint 觀感與較低延遲。若 GPU 有餘裕，可以把 `--iterations` 提高到 150 或 200；這是品質模式，但不屬於上表原始 100-iteration 測量。

## 安裝

建議 Python 3.10/3.11，並使用與 CUDA 相符的 PyTorch：

```bash
git clone <YOUR_GITHUB_URL>
cd smpl_0901_github_release
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Windows 啟用環境改用 `.venv\Scripts\activate`。若 PyTorch 需要特定 CUDA wheel，先依 PyTorch 官方指令安裝，再執行 `pip install -e .`。

模型已放在 `models/` 並由 Git LFS 管理。clone 私人 repository 後執行 `git lfs pull`，再確認 `models/smpl/SMPL_NEUTRAL.pkl` 存在。模型受原始授權限制，repository 必須保持私有。

## 接受的 main_predict 輸入

### 新版 JSONL（建議）

每行一個 JSON：

```json
{"schema":"factory_59pt_body_hands","frame_index":0,"timestamp_s":0.0,"keypoints_3d":[[0.0,0.0,0.0]],"reprojection_errors_px":[0.0]}
```

實際 `keypoints_3d` 必須是 `[59,3]`，順序必須為 Body17、左手21、右手21；也接受完整 `[133,3]`，程式會取 WholeBody ID `0..16, 91..132`。

### 舊版 JSON

也接受 `keypoint_3d` dictionary，key 為 COCO-WholeBody ID `0..16, 91..132`。可選品質欄位：

- `reliable`: `[59]` 或以 joint ID 為 key 的 dictionary
- `reprojection_errors_px`: `[59]`，未提供 `reliable` 時用 120 px 門檻
- `frame_id` / `frame_index`、`timestamp` / `timestamp_s`

預設 `--input-units auto` 依照 `main_predict` 的 factory contract 將數值視為毫米；舊版 container JSON 若有 `metadata.unit` 也會採用它。自訂串流若已是公尺，請加 `--input-units m`。預設座標轉換為 `--axis-map x,-y,z`；若你的 calibration world 已是 y-up，改成 `--axis-map x,y,z`。軸向不能只靠 schema 猜測，第一次部署請用站立、向前走與舉右手三個動作確認。

## 執行方式

直接播放 `factory_59pt_dlt_demo.py` 產生的 JSONL：

```bash
smpl-0901-bridge \
  --input jsonl:///absolute/path/to/joints_3d_4view.jsonl \
  --device cuda \
  --unity-host 192.168.1.20 \
  --unity-port 9095
```

舊版 `joints_3d_4view.json`（含 `metadata + frames`）可直接讀，不必先轉檔：

```bash
smpl-0901-bridge --input json:///absolute/path/to/joints_3d_4view.json --device cuda
```

直接讀 demo 的 NPZ（優先使用 `keypoints_3d_smoothed`）：

```bash
smpl-0901-bridge --input npz:///absolute/path/to/joints_3d_4view.npz --device cuda
```

Linux 同一台機器即時串流，先常駐 bridge：

```bash
smpl-0901-bridge --input unix:///tmp/dt_pose_3d.sock --device cuda
```

再由預測端送出每一筆結果：

```python
from smpl_0901.sender import send_record

record = {
    "schema": "factory_59pt_body_hands",
    "frame_index": frame_index,
    "timestamp_s": timestamp_s,
    "keypoints_3d": keypoints_3d.tolist(),
    "reprojection_errors_px": reprojection_errors_px.tolist(),
}
send_record(record, "unix:///tmp/dt_pose_3d.sock")
```

跨 container 或跨主機可改用 `--input udp://0.0.0.0:9100`，sender destination 改成 `udp://BRIDGE_IP:9100`。UDP/Unix datagram 不會讓 predictor 因 SMPL fitting 變慢；忙碌時以最新 frame 為準。

已有 JSON/JSONL 檔也可按原始 FPS 模擬 sender：

```bash
smpl-0901-send joints_3d_4view.jsonl --destination unix:///tmp/dt_pose_3d.sock --fps 30
```

注意：目前 `factory_59pt_dlt_demo.py` 的 JSONL/NPZ 是整段離線流程的輸出；要真正即時，需在它產生每個 `record` 的位置呼叫 `send_record`，或讓常駐 predictor 送相同 schema。

## Unity

1. Unity 專案先安裝 BioMotionLab SUP（程式會尋找 `Packages/com.biomotionlab.sup/Models/SMPLH/SMPLH Character Male New.prefab`）以及 TextMeshPro/uGUI。
2. 把 `unity/CustomSMPL` 複製到 Unity 專案的 `Assets/CustomSMPL`。
3. Unity 上方選單按 **CustomSMPL → Setup 0901 Live Bridge Player**。
4. 進入 Play Mode，UI 預設監聽 UDP `9095`。若 Prefab 沒自動找到，在 Inspector 指定 SUP 的 SMPL-H character prefab。

Editor 按鈕會建立 player、root motion、raw hand retargeter、quality debug 與 UI，不必手動拉腳本。`bodyPoseOnly=true` 確保身體由 SMPL pose 驅動、手指由原始 Hand21 hybrid 驅動。

## 專案結構

```text
smpl_0901/                 Python 常駐 bridge、fitter、協定與 sender
models/                    Body25 regressor 與 Git LFS 管理的 SMPL pkl
unity/CustomSMPL/          Protocol V2 hybrid Unity player 與一鍵設定選單
tests/                     schema、映射、NPZ、binary protocol 測試
```

模型只適合放在有權限控管的私人 repository。若未來要公開程式碼，請先閱讀 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，移除 SMPL pkl，並確認 Body25 regressor 的散布來源。
