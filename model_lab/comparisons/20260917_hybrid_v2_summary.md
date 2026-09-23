# 2026-09-17 Hybrid v2 Adaptive 比較摘要

## 目的

驗證「Learnable-SMPLify one-pass prior + bounded Joint IK + 0/3/5-step adaptive refinement」能否在保留標準 SMPL pose/Mesh 輸出的前提下，提高正式 50-step optimizer 的吞吐量，並修正 Hybrid v1 在 AMASS 只見 root 位移、肢體長時間 HOLD 的問題。

## 資料

- Rig B 實際錄製輸出：30 幀；代表目前場域輸入品質。
- AMASS `punching_poses.npz`：233 幀；由已知 SMPL pose/betas 產生 joints 與 Ground Truth Mesh。
- H3WB mini：280 幀；只有 3D joints，無 SMPL parameter Ground Truth。

大型陣列、圖片與影片位於未納入 Git 的：

`model_lab/comparisons/runs/20260917_hybrid_v2_five_method_final/`

## 主要結果

| 資料集 | 方法 | FPS | Upper11 殘差 p50 | 採用率 | MPVE p50 |
|---|---|---:|---:|---:|---:|
| Rig B | 論文 neural baseline | 71.59 | 63.51 mm | 100.00% | — |
| Rig B | 正式 upper-body 50-step | 2.41 | 36.37 mm | 100.00% | — |
| Rig B | Hybrid v1 | 25.99 | 71.74 mm | 100.00% | — |
| Rig B | Hybrid v2 adaptive | 14.95 | 55.19 mm | 100.00% | — |
| AMASS | 論文 neural baseline | 71.64 | 17.69 mm | 100.00% | 39.01 mm |
| AMASS | 正式 upper-body 50-step | 2.51 | 17.46 mm | 100.00% | 93.11 mm |
| AMASS | Hybrid v1 | 26.34 | 174.39 mm | 0.43% | 277.85 mm |
| AMASS | Hybrid v2 adaptive | 31.10 | 15.45 mm | 100.00% | 30.95 mm |
| H3WB | 論文 neural baseline | 69.91 | 62.98 mm | 100.00% | — |
| H3WB | 正式 upper-body 50-step | 2.38 | 14.40 mm | 100.00% | — |
| H3WB | Hybrid v1 | 26.61 | 35.22 mm | 37.14% | — |
| H3WB | Hybrid v2 adaptive | 30.98 | 29.22 mm | 99.29% | — |

`Upper11 殘差` 是輸入 joints 與模型 joints 的擬合殘差，不是 motion-capture Ground Truth MPJPE。只有 AMASS 可計算 pelvis-aligned Mesh Ground Truth 誤差（MPVE）。

## AMASS 靜止問題結論

舊 v1 的 pose 有產生候選動作，但 facing/root 多解與安全閘門使 232/233 幀套用上一個可信姿態，所以影片看起來只有整體位移。v2 修正 root 候選、stream-facing calibration 與 upper-body gate 後：

- 233/233 幀接受，HOLD 為 0。
- 232 個相鄰 Mesh 轉場全部非零。
- 平均每幀頂點位移 10.57 mm，p95 25.29 mm，最大 54.92 mm。

因此 AMASS 的手腳不動不是 pose axis-angle 套用錯誤，而是 v1 的 applied-output 長時間 HOLD；v2 已修正。

## 判定

Hybrid v2 是目前較合理的高速實驗候選：在乾淨 AMASS 上同時超過正式 50-step 的速度與 MPVE，本次 Rig B 也較正式版快約 6.2 倍。但 Rig B Upper11 殘差仍比正式版高約 18.82 mm，尚不能直接替換 production。下一步應先做長序列 Rig B 與即時 Unity A/B，再決定是否整合為快速路徑或背景 optimizer 架構。

## 可視化輸出

- `visuals/*_average_three_views.png`：平均案例三視角。
- `visuals/*_mesh_comparison.mp4`：五方法 3D Mesh 比較。
- `visuals/*_hybrid_v2_candidate_vs_applied.mp4`：閘門前候選與實際輸出。
- `visuals/five_method_summary.png`：FPS 與 Upper11 殘差摘要。

影片播放 FPS 只供人工檢視，不等同推理吞吐量。
