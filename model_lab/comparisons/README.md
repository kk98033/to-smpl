# Model Comparisons

每次模型比較放在 `runs/YYYYMMDD_<experiment_name>/`。

```text
runs/<run_id>/
├── README.md
├── metrics.json
├── arrays/
│   ├── rig_b_recording.npz
│   ├── amass_clean.npz
│   └── h3wb.npz
└── visuals/
    ├── *_average_three_views.png
    ├── *_mesh_comparison.mp4
    ├── *_summary.png
    ├── *_candidate_vs_applied.mp4
    └── visual_manifest.json
```

`runs/` 預設不納入 Git，避免將 Mesh arrays、影片與資料集衍生檔案提交至 repository。比較報告確認後，可將小型 summary JSON、Markdown 或圖表選擇性加入版本控制。
