# 2026-09-19 Hybrid v5 Adaptive Batched IK 研究報告

## 結論

在不使用每關節 2D confidence 的前提下，v5 同時提高速度並恢復 v4 犧牲的快速動作精度與平滑度。

- Rig B：50.99 FPS；三次重測 `50.72 ± 0.25 FPS`。
- AMASS：55.90 FPS；Upper11 p50 16.95 mm、MPVE p50 32.62 mm，接近 v3 高精度版。
- H3WB：64.05 FPS；Upper11 p50 28.86 mm，低於 v3 與 v4。

本結果屬 `model_lab` 隔離實驗，沒有修改正式 bridge。

## 方法

### 1. 3D motion-coherence 動態排程

最近至多 5 幀以 pelvis 對齊。每個 Upper11 joint 的 motion coherence 定義為淨位移除以逐幀路徑長，再取關節平均。

| 狀態 | 條件 | OG prior | Refinement |
|---|---|---|---|
| coherent motion | coherence ≥ 0.55 且 speed ≥ 0.3 m/s | 每幀 | 0／2／4 |
| noisy／slow | 其他 | 每 4 幀 | 0／1／2 |

觀測到的 coherence median：Rig B 0.296、AMASS 0.897、H3WB 0.504。這避免單純以高速度把 Rig B 抖動誤認為真實快速動作。

### 2. 固定 shape 快取

fixed betas 在追蹤期間不變，因此 rest joints 與 neutral Body25 從每幀重算改為每段只算一次。

### 3. Two-level arm IK

左右肩在同一 kinematic depth 且互不依賴，左右肘亦同。每個 root hypothesis 的 FK 從肩／肩／肘／肘四次，降為肩層與肘層兩次。

### 4. Batched root hypotheses

analytical、torso-kabsch、previous、OG root 的 shape 與 betas 相同，先建立各自 IK body pose，再合成 batch 執行一次完整 SMPL LBS。選擇規則未改變。

## 完整三資料集結果

| 資料集 | 指標 | v3 quality | v4 fast | v5 final |
|---|---|---:|---:|---:|
| Rig B | FPS | 23.03 | 34.98 | **50.99** |
| Rig B | Upper11 p50 | **53.12** mm | 54.78 mm | 54.38 mm |
| Rig B | Upper11 p95 | **64.23** mm | 89.01 mm | 71.29 mm |
| Rig B | 時序加速度 p95 | 98.53 mm | **95.53** mm | 97.32 mm |
| AMASS | FPS | 33.21 | 48.22 | **55.90** |
| AMASS | Upper11 p50 | **15.46** mm | 21.31 mm | 16.95 mm |
| AMASS | Upper11 p95 | **31.87** mm | 52.56 mm | 32.15 mm |
| AMASS | MPVE p50 | **30.95** mm | 39.06 mm | 32.62 mm |
| AMASS | 時序加速度 p95 | **14.78** mm | 71.02 mm | 16.16 mm |
| H3WB | FPS | 33.25 | 49.19 | **64.05** |
| H3WB | Upper11 p50 | 30.05 mm | 30.35 mm | **28.86 mm** |
| H3WB | Upper11 p95 | **39.95** mm | 42.43 mm | 41.88 mm |
| H3WB | 時序加速度 p95 | **36.46** mm | 51.41 mm | 37.07 mm |

v5 相較 v3 的 FPS 提升：Rig B +121%、AMASS +68%、H3WB +93%。AMASS 精度仍略低於 v3，但已消除 v4 的主要退化；H3WB p50 反而改善。

## 工程優化 A/B

### Cached + two-level IK（固定 v4 排程，30／50／50 幀）

| 資料集 | 原 solver FPS | cached/two-level FPS | 最大 joint／vertex 差 |
|---|---:|---:|---:|
| Rig B | 35.07 | 42.67 | 0 |
| AMASS | 46.55 | 65.48 | 0 |
| H3WB | 46.55 | 64.40 | 0 |

root 選擇完全相同。

### Batched roots（完整資料集，coherence 0.65）

| 資料集 | 分開 forward | batched forward | 提升 | 最大差 |
|---|---:|---:|---:|---:|
| Rig B | 41.68 | 49.51 | +18.8% | 5.7e-7 m 以下 |
| AMASS | 48.58 | 53.66 | +10.4% | 0 |
| H3WB | 62.17 | 71.23 | +14.6% | 0 |

root 選擇完全相同。

## Coherence 門檻消融（30／100／100 幀）

| 門檻 | Rig B FPS / p50 / jitter | AMASS FPS / p50 / jitter | H3WB FPS / p50 / jitter |
|---:|---|---|---|
| 0.45 | 48.95 / 54.06 / 86.88 | 55.09 / 18.45 / 20.12 | 55.06 / 30.21 / 31.94 |
| 0.55 | 48.18 / 54.38 / 97.32 | 53.55 / 18.45 / 20.12 | 60.03 / 28.99 / 38.17 |
| 0.65 | 51.07 / 53.87 / 97.05 | 54.81 / 18.45 / 20.12 | 70.72 / 26.89 / 60.97 |

`0.55` 選為整體設定：H3WB 穩定度接近 v3，同時維持約 60 FPS；`0.65` 雖快，但 H3WB jitter 明顯增加。

## Profiler 結果

同一個 30／1／1 短測：

| 項目 | v4 | v5 |
|---|---:|---:|
| run core cumulative | 1.341 s | 1.051 s |
| IK cumulative | 0.680 s | 0.361 s |
| `_forward_kinematics` calls | 560 | 280 |
| FK cumulative | 0.368 s | 0.184 s |

Profiler 依 PyTorch 官方建議同時考慮 CPU orchestration 與 CUDA 工作；此處 cProfile 用來定位 Python／同步路徑，最終 FPS 仍以同步後 wall-clock 計算。

## `torch.compile` 實驗

- 單獨 SMPL forward：0.622 ms → 0.592 ms，約 +5.2%，輸出相同。
- 完整 v5（編譯測試當時為 unbatched coherence 0.65）：
  - Rig B：41.68 → 32.52 FPS（-22.0%）
  - AMASS：48.58 → 49.19 FPS（+1.2%）
  - H3WB：62.17 → 63.06 FPS（+1.4%）

Inductor 顯示 GB10 SM 數量不足以採用該 autotune GEMM 路徑；完整結果不具優勢，因此最終設定 `compile_smpl=false`。

## Joint-only 研究

SMPL Body25 regressor 為 `(25, 6890)`；Upper11 loss 涉及 3,558 個 unique vertices。直接以原生 SMPL24 FK 取代完整 vertices 會改變 Body25 joint 定義，不能宣稱零精度損失。若後續研究，應建立獨立 surrogate 並以現行 fitter 作 teacher，而非直接替換正式 loss。

## 主要參考

- PyTorch `torch.compile`：https://docs.pytorch.org/docs/stable/generated/torch.compile
- NVIDIA CUDA Graphs：https://docs.nvidia.com/cuda/cuda-programming-guide/04-special-topics/cuda-graphs.html
- PyTorch Profiler：https://docs.pytorch.org/docs/stable/profiler
- SMPL 官方模型說明：https://smpl.is.tue.mpg.de/
- HMD-Poser（temporal pose + FK）：https://openaccess.thecvf.com/content/CVPR2024/papers/Dai_HMD-Poser_On-Device_Real-time_Human_Motion_Tracking_from_Scalable_Sparse_Observations_CVPR_2024_paper.pdf

## 輸出

- 最終 run：`model_lab/comparisons/runs/20260919_hybrid_v5_adaptive_batched_final/`
- 原始指標：`metrics.json`
- 關節／Mesh／排程陣列：`arrays/*.npz`
- 原始消融：`coherence_ablation.csv`、`engineering_ablation.csv`、`repeated_rig_b.csv`
- 五方法視覺結果：`model_lab/comparisons/runs/20260919_hybrid_v5_five_method_final/visuals/`
  - `five_method_v5_summary.png`
  - 三資料集平均案例三視角圖。
  - OG／Production／v3／v4／v5 Mesh 比較影片。
  - v5 candidate 與 regional gate 後 applied pose 對照影片。
  - `visual_manifest.json` 保存平均案例 frame 與影片設定。

FPS 為 to-smpl 模型路徑 capacity，不含 calibration、資料 I/O、UDP、Dashboard、Unity，以及上游 2D／3D pose pipeline。
