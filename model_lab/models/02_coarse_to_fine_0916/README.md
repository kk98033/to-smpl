# 02 — Coarse-to-Fine Joints-First 0916

## 目的

保留正式版的 fixed betas、上半身約束、時間平滑與 safety gate，但減少每幀反覆生成完整 SMPL Mesh 的成本。

## 方法

```text
Body25 target
  → previous accepted pose / analytical root seed
  → Coarse stage：SMPL24 kinematic joints-only fitting
       - 不計算 6,890 vertices
       - 輕量迭代與 early stop
  → Fine stage：少量完整 SMPL + Body25 iterations
  → 完整 Mesh forward 一次
  → 現行 safety gate
```

### Coarse stage

- fixed betas 下的 shaped rest joints 只計算一次。
- 每次 iteration 只執行 rotation matrix 與 kinematic rigid transform。
- Body25 的 neck、shoulders、elbows、wrists、pelvis、hips 由 SMPL24 對應。
- nose 由 head joint 與固定體型的 head-local offset 近似。
- 支援 loss threshold 與 plateau early stop。

### Fine stage

- 使用 coarse 結果作為完整 SMPL fitter 初值。
- 僅執行少量完整 Mesh iterations，用 exact Body25 regressor 修正 skeletal approximation。
- 下肢鎖定及 neck/head/wrist forward lock 與正式版一致。

## 與正式版差異

- 正式版：50 次完整 Mesh forward。
- 本版：多次低成本 skeletal forward + 少量完整 Mesh refinement。
- safety gate、fixed betas 與最終 exact Body25 輸出不變。

## 驗證狀態

此方法屬實驗候選，必須完成 Rig B、AMASS、H3WB 三資料集比較後，才可考慮整合正式 Bridge。
