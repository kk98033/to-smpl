# 08 — Hybrid v4 Fast Path（0918）

## 定位

隔離實驗版，不修改正式 bridge。這個版本不需要每關節 2D confidence；它沿用 v3 的因果式 3D 幾何品質檢查與區域安全閘門，主要以兩個排程變更提高即時吞吐量。

## 流程

```text
Body25 3D joints
  → causal 3D geometry quality（速度／骨長一致性）
  → 每 4 幀執行一次 OG neural prior
      └─ 中間 3 幀沿用上一個 accepted pose 作 prior
  → Hybrid v2 swing/twist IK
  → weighted 0/1/2-step refinement
  → torso / left-arm / right-arm regional gate
  → 完整 SMPL forward → joints / mesh / Unity pose
```

## 與 v3 的差異

| 項目 | Hybrid v3 | Hybrid v4 fast path |
|---|---|---|
| 2D confidence | 非必要；歷史資料使用 3D fallback | 不使用 |
| OG neural prior | 每幀 | 每 4 幀 |
| Adaptive refinement | 0／2／4 step | 0／1／2 step |
| 區域 gate | torso／左右臂 | 保留 |
| 正式 bridge | 未取代 | 未取代 |

## 實測結論

三次 Rig B 重複測量：

- v3：`23.69 ± 0.73 FPS`
- v4：`35.39 ± 1.62 FPS`
- 平均吞吐量提升約 `49%`

完整資料集的單次測量：

| 資料集 | v3 FPS | v4 FPS | v3 Upper11 p50 | v4 Upper11 p50 |
|---|---:|---:|---:|---:|
| Rig B 錄製 | 23.03 | 34.98 | 53.12 mm | 54.78 mm |
| AMASS clean | 33.21 | 48.22 | 15.46 mm | 21.31 mm |
| H3WB | 33.25 | 49.19 | 30.05 mm | 30.35 mm |

AMASS 的 pelvis-aligned MPVE p50 由 30.95 mm 增至 39.06 mm，且時序加速度 p95 明顯增加，因此 v4 應定位為低延遲 fast profile；v3 仍是較高精度、較平滑的 profile。

## 限制

- OG keyframe 間隔使快速或高頻動作較容易出現抖動；AMASS 已量測到此現象。
- Rig B 本次只有 30 幀連續片段，仍需更長的場域錄影與 Unity A/B。
- 影片播放 FPS 不等於推理 FPS；報告中的 FPS 只計 batch=1 模型路徑。

## 重現

實驗入口：`model_lab/benchmark/scripts/run_hybrid_v3_comparison.py`

必要參數：

```text
--method-key hybrid_v4_fastpath
--refinement-policy lite
--og-stride 4
```
