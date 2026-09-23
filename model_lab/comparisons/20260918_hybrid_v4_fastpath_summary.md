# 2026-09-18 Hybrid v4 Fast Path 加速實驗

## 結論

在不使用每關節 2D confidence 的限制下，可以再加速。最佳 Pareto 設定是：

- OG neural prior 每 4 幀執行一次。
- 中間幀沿用上一個 accepted pose 作 prior，再執行 analytical IK。
- Adaptive refinement 從 `0/2/4` 降為 `0/1/2` step。
- 保留 v3 的 3D 幾何品質檢查與 torso／左右臂區域安全閘門。

三次 Rig B 重複量測，v3 為 `23.69 ± 0.73 FPS`，v4 為 `35.39 ± 1.62 FPS`，平均速度提升約 49%。完整測試單次量測為 34.98 FPS，已超過 30 FPS。

v4 是速度優先 profile，不是無條件取代 v3：Rig B 與 H3WB 的 p50 精度損失小，但 AMASS 乾淨 Ground Truth 的 MPVE 與時序抖動明顯變差。

## Rig B 加速消融（30 幀）

| Refinement | OG stride | FPS | Upper11 p50 | 時序加速度 p95 | 判定 |
|---|---:|---:|---:|---:|---|
| 0/2/4 | 1 | 23.03 | 53.12 mm | 98.53 mm | v3 高精度基準 |
| 0/1/2 | 1 | 28.50 | 57.07 mm | 100.47 mm | 接近 30 FPS |
| 0/2/4 | 2 | 27.45 | 53.16 mm | 141.13 mm | 精度保留，但抖動增加 |
| 0/1/2 | 2 | 33.61 | 55.65 mm | 99.34 mm | 可行 |
| 0/1/2 | 4 | 34.68 | 54.78 mm | 95.53 mm | 最佳 Pareto |
| 0 step | 2 | 40.79 | 81.93 mm | 140.71 mm | 精度損失過大 |
| 0 step | 4 | 48.56 | 89.08 mm | 78.95 mm | 不採用 |

消融測試與完整測試的 FPS 有小幅差異，來自獨立程序、GPU 時脈與背景負載；因此另以三次重複量測報告均值與標準差。

## 完整資料集比較

| 資料集 | 指標 | Hybrid v3 | Hybrid v4 fast path | 變化 |
|---|---|---:|---:|---:|
| Rig B | FPS | 23.03 | 34.98 | +51.9% |
| Rig B | Upper11 p50 | 53.12 mm | 54.78 mm | +1.67 mm |
| Rig B | 時序加速度 p95 | 98.53 mm | 95.53 mm | -3.00 mm |
| AMASS | FPS | 33.21 | 48.22 | +45.2% |
| AMASS | Upper11 p50 | 15.46 mm | 21.31 mm | +5.85 mm |
| AMASS | pelvis-aligned MPVE p50 | 30.95 mm | 39.06 mm | +8.11 mm |
| AMASS | 時序加速度 p95 | 14.78 mm | 71.02 mm | +56.25 mm |
| H3WB | FPS | 33.25 | 49.19 | +47.9% |
| H3WB | Upper11 p50 | 30.05 mm | 30.35 mm | +0.31 mm |
| H3WB | 時序加速度 p95 | 36.46 mm | 51.41 mm | +14.95 mm |

三個資料集皆無全身 HOLD。v4 在 AMASS 有 2 幀右臂局部保留；H3WB 有 2 幀右臂與 1 幀左臂局部保留。輸出仍為合法的完整 SMPL pose 與 mesh。

## 速度測量範圍

FPS 計入：batch=1 OG prior（依 stride）、IK、adaptive refinement、區域 gate 後的 SMPL forward。

FPS 不計入：啟動／校正、檔案 I/O、UDP、Dashboard、Unity、上游 2D／3D pose pipeline。因此這是 to-smpl 模型路徑吞吐量，不是端到端 FPS。

## 建議

1. 保留兩個 profile：`quality` 使用 v3，`fast` 使用 v4。
2. 場域即時展示可先用 v4；離線輸出或高精度需求使用 v3。
3. 若要同時逼近 v3 的 AMASS 平滑度，可在 v4 只對高角速度幀暫時將 OG stride 降為 1；必須另做消融，不能直接宣稱有效。
4. 正式合併前，需以長 Rig B 序列量測 hold duration、端到端延遲與 Unity 視覺結果。

## 實驗輸出

- 原始 v4 run：`model_lab/comparisons/runs/20260918_hybrid_v4_fastpath_lite_s4/`
- `metrics.json`：完整指標與設定。
- `arrays/*.npz`：三資料集的 joints、mesh、gate 與 timing 陣列。
- `ablation_rig_b.csv`：七組速度／精度消融。
- `repeated_rig_b.csv`：v3、v4 各三次重複測量。
- 四方法視覺結果：`model_lab/comparisons/runs/20260918_hybrid_v4_four_method_final/visuals/`
  - 三資料集平均案例三視角圖。
  - OG／Production／v3／v4 Mesh 比較影片。
  - v4 candidate 與 gate 後 applied pose 對照影片。
  - FPS 與 Upper11 p50 摘要圖。

上述結果仍屬 model_lab 隔離實驗，未修改正式 bridge，亦未推送 GitHub。
