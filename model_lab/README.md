# SMPL Model Lab

本目錄用於 SMPL 轉換模型的版本化實驗。正式服務程式仍位於 `smpl_0901/`；實驗方法在完成三資料集驗證前，不直接取代正式服務。

## 固定目錄規則

```text
model_lab/
├── models/
│   ├── 00_paper_neural_baseline/
│   ├── 01_production_upper_body_50step/
│   ├── 02_coarse_to_fine_0916/
│   ├── 03_analytical_ik_0916/
│   ├── 04_tuned_40step_tf32_0916/
│   ├── 05_hybrid_jointik_og_0917/
│   ├── 06_hybrid_jointik_adaptive_0917/
│   ├── 07_hybrid_v3_confidence_limb_gate_0918/
│   ├── 08_hybrid_v4_fastpath_0918/
│   └── 09_hybrid_v5_adaptive_gpu_0919/
├── benchmark/
│   ├── README.md
│   └── scripts/
└── comparisons/
    ├── README.md
    └── runs/                 # 大型實驗輸出，不納入 Git
```

每個 `models/<model_id>/` 必須包含：

1. `README.md`：方法、輸入輸出、初始化、loss、閘門、限制與相對前版修改。
2. 可執行的模型實作或 adapter。
3. 若有超參數，必須保存在程式或設定檔中，不只記錄於口頭說明。

每次比較必須使用相同三組資料：

- Rig B 實際錄製輸出。
- AMASS 乾淨 SMPL round-trip 資料。
- H3WB 3D 人體關節資料。

每次輸出至少包含：

- 平均 FPS、p50/p95 latency。
- Body15 與 Upper11 關節擬合殘差。
- safety-gate 採用率與最長連續 hold。
- 平均案例三視角圖。
- 3D Mesh 比較影片。
- 測試資料、frame selection、模型版本與限制說明。

## Git 保存範圍

Git 保存可重現與可審查的內容：各版本 `README.md`、模型／adapter 程式、設定檔、benchmark／render 腳本，以及不含逐幀資料的 Markdown 彙總。下列內容只保留在本機，不納入 Git：

- `comparisons/runs/` 與其他生成結果目錄。
- Rig B 錄製資料、AMASS、H3WB 與逐幀 JSONL／NPZ／NPY。
- SMPL／SMPL-X 授權模型、Learnable-SMPLify checkpoint 與其他權重。
- 生成的圖片、影片、Mesh arrays 及暫存檔。

v5 已驗證並整合至正式 `smpl_0901/`；`model_lab/` 保留其演進、消融方法與重現工具，後續候選策略仍須完成三資料集驗證後才能取代正式服務。
