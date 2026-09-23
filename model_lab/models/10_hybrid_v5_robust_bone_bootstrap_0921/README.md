# 10 — Hybrid v5 Robust Bone Bootstrap（0921）

## 問題

Production `adaptive-fast` 原先直接以 tracker 的第一幀建立 3D 骨長 reference。
本次 Rig B live replay 的第一幀右前臂為 0.105 m；後續可信區段約 0.20 m。
骨長差超過 45% 後 joint confidence 變成 0，而舊 reference 只會在 confidence
足夠時更新，形成無法自行恢復的 deadlock。Dashboard 與 Unity 因此看見右臂
長期沿用上一個姿勢；上游右肩、右肘與右腕其實都有持續移動。

## 修正

1. 前 15 個 causal frames 使用 rolling median 建立每條骨長 reference。
2. bootstrap 完成後保留原本的 0.98／0.02 慢速 reference 更新。
3. 若 15-frame window 的 relative MAD 不超過 12%，且與 reference 分歧至少
   35%，連續 8 次後允許 reference recovery。
4. 單一離群值不會觸發 recovery。
5. live diagnostics 新增 `adaptive.region_confidence`。

## Rig B 同片段 A/B

來源為 2026-09-21 正在重播的同一段 live `smpl_fit.jsonl`，比較 frame
1438–1678，共 241 個 fitted frames。修正版離線 replay 使用相同 Factory59
targets、20 幀 calibration、`upper-body` 與 `adaptive-fast` 設定。

| 指標 | 原版單幀 reference | Robust bootstrap |
|---|---:|---:|
| 右臂允許更新 | 0 / 241 | 114 / 240 |
| 右肘最大 fitted motion | 157.9 mm | 516.9 mm |
| 右腕最大 fitted motion | 209.6 mm | 782.8 mm |
| 右肘 residual p50 | 236.8 mm | 130.2 mm |
| 右腕 residual p50 | 383.1 mm | 138.7 mm |
| 左腕 residual p50 | 101.2 mm | 105.4 mm |

新 confidence estimator 相較舊版增加約 0.125 ms/frame。完整修正版在 Pipeline、
live Bridge 與 Dashboard 同時運行、另加離線 replay 的競爭負載下，solver
`fit_ms p50=29.89 ms`（capacity 33.45 FPS）。這不是空載正式 throughput；只能
證明修正後仍超過目前上游輸出速度，不能拿來取代既有 v5 空載 50 FPS benchmark。

## 判讀

修正解決的是「錯誤 seed 造成永久單側鎖死」，不是取消 safety gate。Rig B 的
右臂仍有遮擋與幾何跳動，因此部分 frame 會因低 confidence、residual、delta
而保持上一個安全姿勢；這是預期行為。正式判定應同時觀察
`region_confidence`、`region_updates`、輸入 raw 59-point 與 fitted motion。
