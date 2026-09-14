# 0901 Multi-Dataset Verified Playback & Reconstruction Outputs

本資料夾彙整 0901 最新修正後的多資料集重建成果、正面對照影片，以及完全符合 `fakesender.py` / Unity Protocol V2 規格的 JSON 串流格式。

---

## 📁 資料夾結構一覽

```text
0901meeting/new_outputs/
|-- playback_catalog.json           <- Unity / fakesender 總播放目錄清單
|-- README.md                       <- 本說明文件
|-- SUMMARY_REPORT.md               <- 跨資料集評測與分析報告
|-- h36m_300/                       <- Human3.6M Subject 1 Action 2 (300 幀)
|   |-- h36m_300.json               <- Protocol V2 完整串流格式
|   |-- h36m_300_comparison.mp4     <- 正面 1:1 骨架與 SMPL 疊合對照影片
|   |-- h36m_300_preview.png        <- 關鍵幀預覽圖 (Frame 150)
|-- amass_sample_300/               <- AMASS 坐姿延伸連續動作 (300 幀)
|   |-- amass_sample_300.json       <- Protocol V2 完整串流格式 (脊椎挺直無駝背)
|   |-- amass_sample_300_comparison.mp4 <- 正面坐姿與伸展對照影片
|   |-- amass_sample_300_preview.png    <- 關鍵幀預覽圖 (Frame 150)
|-- amass_punching/                 <- AMASS 快速拳擊連續動作 (234 幀)
|   |-- amass_punching.json         <- Protocol V2 完整串流格式
|   |-- amass_punching_comparison.mp4 <- 正面出拳與格擋對照影片
|   |-- amass_punching_preview.png  <- 關鍵幀預覽圖 (Frame 117)
|-- h3wb_300/                       <- H3WB 全身關節點連續動作 (300 幀)
|   |-- h3wb_300.json               <- Protocol V2 完整串流格式 (含雙手 21 關節)
|   |-- h3wb_300_comparison.mp4     <- 正面全身對照影片
|   |-- h3wb_300_preview.png        <- 關鍵幀預覽圖 (Frame 150)
```

---

## 🔍 解決「駝背與頸部前傾扭曲」問題

1. **扭曲成因**：
   - 純遞迴神經網路（如 Learnable-SMPLify ST-GCN）在長時間長序列（300 幀）持續依賴前一幀姿態做殘差預測時，微小的脊椎與頸部旋轉誤差會持續向下累積，導致在特定影格（如 Frame 78 坐姿時）出現嚴重的「駝背（Hunchback）」與「烏龜頸（Turtle Neck）」現象。
2. **解決方案**：
   - 採用 **KAMA-100 + Adaptive Refinement 獨立幀擬合**。每幀均以剛體幾何分析解為基礎，並加上解剖學關節旋轉約束，無任何時序累積漂移，確保坐姿時背部自然挺直、頸部垂直對齊。

---

## 📡 `fakesender.py` Protocol V2 JSON 格式標準

每一份 JSON 檔案結構完全相容於 `fakesender.py` 與 Unity 端 `Protocol V2 (SMV2)` 接收器：

```json
{
  "protocolVersion": 2,
  "datasetName": "h36m_300",
  "displayName": "H3.6M 300 — GT body / root",
  "gtAvailable": true,
  "hasHands": false,
  "hasRootMotion": true,
  "frames": [
    {
      "protocolVersion": 2,
      "frameId": 0,
      "timestamp": 0.0,
      "units": "meter",
      "body": {
        "rootPosition": [0.0, 0.0, 0.0],
        "pelvisWorld": [0.091, 0.154, -0.907],
        "rootRotation": [0.036, 0.708, -0.704, -0.007],
        "rootConfidence": 1.0,
        "pose": [/* 156-D SMPL-H axis-angle */],
        "betas": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
      },
      "hands": {
        "leftLocalJoints": [/* 63-D wrist-local (21x3) */],
        "leftConfidence": [/* 21-D confidence */],
        "rightLocalJoints": [/* 63-D wrist-local (21x3) */],
        "rightConfidence": [/* 21-D confidence */]
      },
      "observation": {
        "jointCount": 25,
        "joints": [/* 75-D 3D joints */],
        "confidence": [/* 25-D confidence */],
        "label": "GT joints",
        "gtAvailable": true
      },
      "quality": {
        "inputValid": true,
        "inputScore": 1.0,
        "fitResidualMm": 35.45,
        "worstJointResidualMm": 65.93,
        "torsoOrientationDeg": 5.35,
        "solverState": "TRACKING",
        "stepsUsed": 100
      }
    }
  ]
}
```

---

## 🚀 測試 fakesender.py 串流指令

在 `0901meeting` 目錄下，可指定切換不同資料集進行 UDP 串流：

```powershell
# 1. 串流 Human3.6M 資料集 (Dataset Index 1)
python fakesender.py --dataset 1

# 2. 串流 AMASS 坐姿延伸資料集 (Dataset Index 3)
python fakesender.py --dataset 3

# 3. 串流 AMASS 快速拳擊資料集 (Dataset Index 2)
python fakesender.py --dataset 2

# 4. 串流 H3WB 全身關節點資料集 (Dataset Index 0)
python fakesender.py --dataset 0
```
