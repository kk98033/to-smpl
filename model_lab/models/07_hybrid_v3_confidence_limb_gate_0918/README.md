# 07 — Hybrid v3 Confidence + Limb Gate（0918）

## 定位

隔離實驗版，不修改正式 bridge。目標是在 Hybrid v2 基礎上減少不必要的 optimizer 與全身 HOLD：每幀仍先產生標準 SMPL pose，但輸入 joints 依品質加權，安全閘門拆成 torso、左臂、右臂三區。

## 流程

```text
Body25 joints + confidence
  → 低可信 joints 與上一 accepted SMPL joints 混合
  → Hybrid v2 swing/twist IK + OG prior
  → weighted 0/2/4-step refinement
  → torso / left-arm / right-arm regional gate
  → SMPL forward → joints / mesh / Unity pose
```

## Confidence 來源

正式即時資料應直接使用 pipeline 的 2D confidence、可見相機數與重投影誤差。本次歷史 Rig B `smpl_fit.jsonl` 沒有保存這些欄位，因此 benchmark 使用確定性的 causal fallback：

- 關節速度 5 m/s 以下保持完整權重，12 m/s 以上降為零。
- 骨長偏離歷史基準 12% 以下保持完整權重，45% 以上降為零。
- pelvis 維持 translation anchor。

此 fallback 不能冒充真實 detector confidence；報告必須分開標示。

## Gate 規則

- Torso、左右手臂分別計算 confidence、weighted residual、rotation delta 與 twist。
- 單側手臂不安全時，只沿用該手臂上一個 accepted local rotation。
- Torso 不安全時保留上一個 root/spine/collar，但安全的手臂仍可更新。
- applied Mesh 必須由 gate 後完整 SMPL pose 重新 forward，不能拼接 vertices。

## 狀態

已完成三資料集離線 benchmark，仍不得直接取代 production；需要真實 pipeline confidence、長序列與即時 Unity A/B 驗證。

## 2026-09-18 結果

| 資料集 | v3 FPS | Upper11 p50 | 採用率 | 區域更新 |
|---|---:|---:|---:|---|
| Rig B 錄製 | 23.03 | 53.12 mm | 100.00% | 三區皆 100% |
| AMASS clean | 33.21 | 15.46 mm | 100.00% | 三區皆 100% |
| H3WB | 33.25 | 30.05 mm | 100.00% frame update | 右臂 99.29%，其餘 100% |

相較 Hybrid v2：

- Rig B：14.95 → 23.03 FPS；Upper11 p50 55.19 → 53.12 mm；時序加速度 p95 168.12 → 98.53 mm。
- AMASS：31.10 → 33.21 FPS；Upper11 與 MPVE p50 幾乎不變，233 幀無 HOLD。
- H3WB：30.98 → 33.25 FPS；Upper11 p50 增加 0.83 mm；原本兩幀全身 HOLD 改為只保留右臂。

Rig B 的 mean joint quality 為 0.984，且沒有區域被 gate；因此本輪 Rig B 改善主要來自較合理的 0/2/4-step refinement 排程，不可誤稱為 confidence gate 的效果。區域 gate 的直接效果出現在 H3WB 的兩個右臂異常幀。
