# 2026-09-18 Hybrid v3 Confidence + Regional Gate 實驗

## 結論

Hybrid v3 在目前 Rig B 片段上同時提升吞吐量、擬合殘差與時序穩定度：相較 v2，FPS 提升至 23.03，Upper11 p50 降至 53.12 mm，時序加速度 p95 降至 98.53 mm。AMASS 的 Ground Truth Mesh 精度維持不變；H3WB 的兩個異常幀只鎖右臂，不再凍結全身。

本結果屬隔離實驗，未修改正式 bridge。

## 方法

1. 以 OG one-pass pose 作 rotation prior。
2. Hybrid v2 swing/twist IK 產生 SMPL candidate。
3. 歷史資料無 detector confidence 時，以 causal 關節速度與骨長一致性估計 joint quality。
4. 依 weighted residual 選擇 0／2／4-step refinement。
5. Torso、右臂、左臂分別檢查 confidence、residual、rotation delta 與 twist。
6. 只沿用不安全區域的上一幀 local rotations，再執行完整 SMPL forward。

## v2 與 v3

| 資料集 | 指標 | Hybrid v2 | Hybrid v3 | 變化 |
|---|---|---:|---:|---:|
| Rig B | FPS | 14.95 | 23.03 | +54.1% |
| Rig B | Upper11 p50 | 55.19 mm | 53.12 mm | -2.07 mm |
| Rig B | 時序加速度 p95 | 168.12 mm | 98.53 mm | -41.4% |
| AMASS | FPS | 31.10 | 33.21 | +6.8% |
| AMASS | Upper11 p50 | 15.45 mm | 15.46 mm | +0.01 mm |
| AMASS | MPVE p50 | 30.95 mm | 30.95 mm | 無實質變化 |
| H3WB | FPS | 30.98 | 33.25 | +7.3% |
| H3WB | Upper11 p50 | 29.22 mm | 30.05 mm | +0.83 mm |
| H3WB | 全身 HOLD | 2 幀 | 0 幀 | 改為 2 幀右臂局部 HOLD |

Rig B 的 adaptive refinement 由 v2 的 `0/3/5 = 1/14/15` 變為 v3 的 `0/2/4 = 7/17/6`，是速度改善的主要來源。

## Confidence 限制

歷史 Rig B `smpl_fit.jsonl` 沒有保存 2D confidence、可見相機數或重投影誤差。本實驗使用幾何 fallback，Rig B mean joint quality 為 0.984，沒有觸發區域 gate。因此：

- Rig B 的提升可以歸因於 refinement 排程與新的追蹤狀態。
- 不能用本實驗宣稱真實 detector confidence 已改善 Rig B。
- 即時版本應將 pipeline confidence／reprojection quality 寫入記錄，再做相同 A/B。

## 輸出位置

完整本機輸出（由 Git 忽略）：

`model_lab/comparisons/runs/20260918_hybrid_v3_six_method_final/`

- `metrics.json`：六方法完整指標。
- `visuals/*_average_three_views.png`：平均案例三視角圖。
- `visuals/*_mesh_comparison.mp4`：六方法 Mesh 影片。
- `visuals/*hybrid_v3*_candidate_vs_applied.mp4`：v3 gate 前後對照。
- `visuals/six_method_summary.png`：FPS／Upper11 摘要圖。

影片播放 FPS 僅供檢視，不代表模型推理 FPS。

## 下一階段

1. 先在 pipeline→bridge schema 與錄製檔保存 Body25 confidence、可見相機數與重投影誤差。
2. 使用更長 Rig B 序列與遮擋片段驗證區域 gate。
3. 將 v3 作為獨立 bridge profile，在 Unity 與 production 50-step 做 A/B。
4. 通過後再將 SciPy／NumPy IK 改為 Torch batch，處理純程式效能瓶頸。
