# 統一 Benchmark Protocol

## 固定資料集

1. **Rig B 錄製資料**：使用 `smpl_fit.jsonl` 的同一連續片段；前 20 幀校正，後 30 幀量測。
2. **AMASS**：使用 `punching_poses.npz`；由 SMPL pose/betas 生成 Ground Truth Mesh 與 Body25 target。
3. **H3WB**：使用 `h3wb_mini_300f.npz` 的 `S5/Directions 1`；前 20 幀校正、後 280 幀量測。

## H3WB → Body25 映射

H3WB 前 17 個 body joints 使用 COCO-style 順序：nose、左右眼、左右耳、左右肩、左右肘、左右腕、左右髖、左右膝、左右踝。Body25 neck 與 mid-hip 分別由雙肩、雙髖中點建立；H3WB foot joints 17–22 對應 Body25 左右 toe/heel。

H3WB 不提供 SMPL pose/betas，因此它只能衡量模型對 3D joints 的擬合殘差，不能宣稱為 SMPL parameter Ground Truth。

## 固定輸出

- `metrics.json`
- `arrays/<dataset>.npz`
- `visuals/<dataset>_average_three_views.png`
- `visuals/<dataset>_mesh_comparison.mp4`
- `visuals/three_model_summary.png`
- `README.md`

FPS 必須同時記錄 mean 與由 latency p50 換算的 capacity FPS，並標示是否存在其他 GPU compute process。

## 執行

從 repository root、`smpl-0901` conda environment 執行：

```bash
python model_lab/benchmark/scripts/run_three_model_suite.py \
  --output-dir model_lab/comparisons/runs/<run_id> \
  --smpl-dir models \
  --og-source archive/Learnable-SMPLify/src \
  --og-checkpoint <learnable-smplify-checkpoint> \
  --og-model-dir <learnable-smplify-smpl-family-dir> \
  --rig-b-fit <rig-b-smpl-fit.jsonl> \
  --amass <amass-punching-poses.npz> \
  --h3wb <h3wb-mini-300f.npz> \
  --calibration-frames 20 \
  --rig-b-frames 30 \
  --h3wb-frames 280

python model_lab/benchmark/scripts/render_three_model_suite.py \
  model_lab/comparisons/runs/<run_id>
```

Hybrid Joint IK 四方法實驗使用同一組參數，改執行：

```bash
python model_lab/benchmark/scripts/run_hybrid_jointik_comparison.py \
  --output-dir model_lab/comparisons/runs/<run_id> \
  --smpl-dir models \
  --og-source archive/Learnable-SMPLify/src \
  --og-checkpoint <learnable-smplify-checkpoint> \
  --og-model-dir <learnable-smplify-smpl-family-dir> \
  --rig-b-fit <rig-b-smpl-fit.jsonl> \
  --amass <amass-punching-poses.npz> \
  --h3wb <h3wb-mini-300f.npz> \
  --calibration-frames 20 \
  --rig-b-frames 30 \
  --h3wb-frames 280

python model_lab/benchmark/scripts/render_hybrid_jointik_comparison.py \
  model_lab/comparisons/runs/<run_id>
```

`comparisons/runs/` 由 `.gitignore` 排除；模型文件、benchmark 程式與設定仍可在分支內審查。

## Hybrid v2 adaptive 實驗

Hybrid v2 可單獨執行，避免重跑已完成的基準方法：

```bash
python model_lab/benchmark/scripts/run_hybrid_v2_comparison.py \
  --output-dir model_lab/comparisons/runs/<v2_run_id> \
  --methods hybrid_v2_adaptive \
  --smpl-dir models \
  --og-source archive/Learnable-SMPLify/src \
  --og-checkpoint <learnable-smplify-checkpoint> \
  --og-model-dir <learnable-smplify-smpl-family-dir> \
  --rig-b-fit <rig-b-smpl-fit.jsonl> \
  --amass <amass-punching-poses.npz> \
  --h3wb <h3wb-mini-300f.npz> \
  --calibration-frames 20 \
  --rig-b-frames 30 \
  --amass-frames 233 \
  --h3wb-frames 280
```

將結果與既有四方法 run 合併並渲染：

```bash
python model_lab/benchmark/scripts/merge_hybrid_v2_results.py \
  model_lab/comparisons/runs/<four_method_run> \
  model_lab/comparisons/runs/<v2_run_id> \
  model_lab/comparisons/runs/<merged_run_id>

python model_lab/benchmark/scripts/render_hybrid_v2_comparison.py \
  model_lab/comparisons/runs/<merged_run_id>
```

Hybrid v2 除 applied Mesh 外也保存 candidate Mesh。渲染器會額外產生
`*_hybrid_v2_candidate_vs_applied.mp4`，用來區分模型沒有動作與安全閘門 HOLD。

## Hybrid v3 confidence／regional gate 實驗

```bash
python model_lab/benchmark/scripts/run_hybrid_v3_comparison.py \
  --output-dir model_lab/comparisons/runs/<v3_run_id> \
  --smpl-dir models \
  --og-source archive/Learnable-SMPLify/src \
  --og-checkpoint <learnable-smplify-checkpoint> \
  --og-model-dir <learnable-smplify-smpl-family-dir> \
  --rig-b-fit <rig-b-smpl-fit.jsonl> \
  --amass <amass-punching-poses.npz> \
  --h3wb <h3wb-mini-300f.npz> \
  --calibration-frames 20 \
  --rig-b-frames 30 \
  --amass-frames 233 \
  --h3wb-frames 280

python model_lab/benchmark/scripts/merge_hybrid_v2_results.py \
  model_lab/comparisons/runs/<existing_merged_run> \
  model_lab/comparisons/runs/<v3_run_id> \
  model_lab/comparisons/runs/<six_method_run> \
  --method-key hybrid_v3_confidence_limb_gate

python model_lab/benchmark/scripts/render_hybrid_v3_comparison.py \
  model_lab/comparisons/runs/<six_method_run>
```

歷史 `smpl_fit.jsonl` 未保存 detector confidence 時，v3 使用 causal 幾何 fallback；不得將該權重描述成真實多視角 confidence。

## Hybrid v5 adaptive batched IK

v5 不需要 2D confidence，使用 3D motion coherence 選擇高精度或快速排程，並啟用 fixed-beta cache、two-level arm IK 與 batched root hypotheses：

```bash
python model_lab/benchmark/scripts/run_hybrid_v3_comparison.py \
  --output-dir model_lab/comparisons/runs/<v5_run_id> \
  --method-key hybrid_v5_adaptive_batched \
  --method-label "Hybrid v5 adaptive batched IK" \
  --solver-version v5 \
  --schedule adaptive \
  --refinement-policy lite \
  --og-stride 4 \
  --motion-coherence-threshold 0.55 \
  --motion-speed-threshold 0.3 \
  --smpl-dir models \
  --og-source archive/Learnable-SMPLify/src \
  --og-checkpoint <learnable-smplify-checkpoint> \
  --og-model-dir <learnable-smplify-smpl-family-dir> \
  --rig-b-fit <rig-b-smpl-fit.jsonl> \
  --amass <amass-punching-poses.npz> \
  --h3wb <h3wb-mini-300f.npz> \
  --calibration-frames 20 \
  --rig-b-frames 30 \
  --amass-frames 0 \
  --h3wb-frames 280
```

`--compile-smpl` 只保留供消融；GB10 完整路徑實測沒有收益，最終設定不要加此旗標。
