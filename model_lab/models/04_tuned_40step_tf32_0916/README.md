# 04 — Tuned 40-step TF32 Production Fitter 0916

## 定位

本模型不改變正式版的 SMPL loss、fixed betas、upper-body profile、下肢鎖定、方向約束與 safety gate，只調整數值運算模式與 optimizer 超參數，屬低風險加速候選。

## 相對正式版修改

| 項目 | 正式版 | 本版 |
|---|---:|---:|
| Exact SMPL iterations | 50 | 40 |
| Adam learning rate | 0.02 | 0.03 |
| Float32 matmul precision | highest/default | high（允許 TF32） |
| Loss、joint profile、gate | 不變 | 不變 |

## 方法

```text
Body25 target
  → fixed-betas calibration
  → previous accepted pose / analytical first-frame root
  → 40 × exact SMPL + Body25 soft-target fitting (Adam lr=0.03, TF32)
  → unchanged safety gate
  → accepted pose / hold previous
```

## 統一三資料集結果

同一輪固定 protocol：

- Rig B：4.15 FPS、Upper11 p50 36.95 mm；正式版為 3.18 FPS、36.37 mm。
- AMASS：4.83 FPS、Upper11 p50 18.29 mm；正式版為 3.39 FPS、17.64 mm。
- H3WB：4.48 FPS、Upper11 p50 15.86 mm；正式版為 3.91 FPS、14.45 mm。

相對正式版，平均 FPS 提升 14.5–42.8%，Upper11 p50 殘差增加 0.58–1.41 mm。完整資料、圖與影片位於 `model_lab/comparisons/runs/20260916_three_model_suite/`（Git ignored）。

## 限制

- TF32 會降低部分矩陣乘法 mantissa precision；必須以實測殘差與姿態穩定性確認可接受。
- 速度仍受 batch=1、Python iteration loop 與完整 Mesh forward 影響。
- 本設定在完成三資料集驗證前不取代正式服務。

## 設定
