# 05 — Hybrid Joint IK + Learnable-SMPLify Prior（0917）

## 定位

本模型是隔離的研究原型，不修改 `smpl_0901/service.py`、Docker Compose 或正式 50-step Bridge。

它在 fixed-beta SMPL24 kinematic skeleton 中工作：可觀測的骨段方向由 Body25 Joint IK 決定，Learnable-SMPLify OG 只提供不可由位置唯一決定的 rotation prior。最後仍輸出標準 SMPL root/body local rotations，因此既可做一次 SMPL forward 產生 Dashboard Mesh，也可直接經 Protocol V2 驅動 Unity rigged avatar。

## 第一版範圍

```text
Body25 target
  ├─ analytical torso/root orientation
  ├─ shoulder→elbow swing
  ├─ elbow→wrist swing
  └─ pelvis translation alignment

Previous accepted pose / OG one-pass pose
  ├─ axial twist prior
  ├─ bounded spine/collar prior
  └─ unobserved-joint prior

Joint swing correction + bounded prior
  → one SMPL forward
  → existing safety gate
```

第一輪 benchmark 同時包含：

- `direct_joint_ik`：上一個 accepted pose 作不可觀測旋轉 prior。
- `hybrid_jointik_og`：OG one-pass pose 作 prior，再由 joints 強制修正手臂 swing。

## 目前規則

- Root：比較 analytical、world/local 180°、neutral、上一個 accepted root；Hybrid 另將 OG root 當成候選假設，但不直接強制採用。
- 下肢 local rotations：保持上一個 accepted pose。
- Neck、head、左右 wrist local rotations：固定為零。
- Spine rotation：每節限制在 35°。
- Collar rotation：限制在 45°。
- Shoulder／elbow：以 OG／previous pose 為初始 frame，再以最小 global swing correction 對準觀測骨段；此操作保留 prior 的 roll/twist 成分。
- Translation：將回歸後 Body25 pelvis 對齊輸入 pelvis。
- Safety gate：沿用正式版 100 mm residual、100° twist、90° delta、90° facing mismatch。

## 尚未納入

- Hand42 palm frame 與 wrist orientation。現有統一 benchmark datasets 沒有一致的 Hand42 GT，將於 live-input 階段加入。
- 三節 spine 的 log-space總旋轉重新分配。
- 多視角 reprojection quality gate。
- 背景 optimizer recovery。

## 驗證規則

不得只以 Body25 fitting residual 宣稱 Direct IK 準確。AMASS 必須同時檢查 Ground Truth Mesh／rotation；Rig B 與 H3WB 必須揭露沒有 SMPL parameter GT。比較輸出放在 `model_lab/comparisons/runs/`，預設不納入 Git。

## 2026-09-17 第一輪結果

本輪使用 Rig B 錄製資料 30 幀、AMASS clean 233 幀及 H3WB 280 幀。數字是 batch=1 core throughput；不含 I/O、UDP、Dashboard 與 Unity。

| 資料集 | 方法 | FPS | Upper11 p50 | 採用率 |
|---|---|---:|---:|---:|
| Rig B | 正式 50-step | 2.41 | 36.37 mm | 100.0% |
| Rig B | Direct Joint IK | 42.74 | 74.32 mm | 100.0% |
| Rig B | Joint IK + OG prior | 25.99 | 71.74 mm | 100.0% |
| AMASS | 正式 50-step | 2.51 | 17.46 mm | 100.0% |
| AMASS | Direct Joint IK | 43.17 | 174.39 mm | 13.3% |
| AMASS | Joint IK + OG prior | 26.34 | 174.39 mm | 0.4% |
| H3WB | 正式 50-step | 2.38 | 14.40 mm | 100.0% |
| H3WB | Direct Joint IK | 44.32 | 42.64 mm | 99.6% |
| H3WB | Joint IK + OG prior | 26.61 | 35.22 mm | 37.1% |

判讀：第一版 Hybrid 在 Rig B 達到約 26 FPS（正式版約 10.8 倍），但殘差仍比正式版高 35.37 mm。AMASS 暴露 root／local rotation 前後向歧義與長序列漂移；H3WB 則主要被 axial-twist gate 擋下。因此此版本不可取代 production。下一個實驗應依計畫加入條件式 3/5-step refinement，並先修正 swing/twist 分解與 spine log-space 分配。
