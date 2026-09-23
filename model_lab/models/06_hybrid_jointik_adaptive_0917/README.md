# 06 — Hybrid v2 Joint IK + Adaptive Refinement（0917）

## 定位

隔離研究版本，不修改正式 `smpl_0901/service.py`、Docker、Dashboard 或 Unity。它修正 v1 在 AMASS 長序列幾乎全數 HOLD、Mesh 看似不動的問題，並保留 v1 作失敗對照。

## 相對 v1 的修改

- Root 新增 nose／neck／shoulder／hip 的 weighted Kabsch 候選。
- 修正 facing ambiguity：原 production diagnostic 對 AMASS Ground Truth SMPL 第一個測試幀回報 175.95°。v2 使用 100-step 可信 seed 在每個串流開始時校正一次 feet-forward 正負號，整段序列固定，不依資料集名稱判斷也不允許逐幀翻轉；本修正目前只存在於隔離實驗。
- Shoulder 與 elbow 不再直接沿用完整 OG local rotation；觀測 joints 決定 swing，OG/previous 只提供受限 axial twist。
- Shoulder twist 限制 ±45°，elbow twist 限制 ±20°。
- 三節 spine 先合成總旋轉，再以 20%／30%／50% 在 log-space 近似分配。
- Neck、head、wrist 維持 forward/zero local rotation。
- 下肢保持上一個 accepted state。
- Root 候選先滿足 facing，再優先限制為相對上一 accepted root 不超過 90°，避免選出之後必然被 safety gate 拒絕的 180° 跳轉。
- 一般逐幀追蹤不再使用 neutral／world-yaw-180／local-yaw-180 候選；這些多解候選只保留給 Frame 0 或未來明確的重新初始化流程，避免 AMASS 長序列中途翻面後連續 HOLD。
- Upper-body 模式固定下肢時，胸口相對腳尖超過 90° 可能是合法轉身，因此 facing 僅保留為候選診斷與排序訊號，不再單獨觸發 HOLD；閘門仍檢查擬合殘差、關節 twist 與 root 時序跳變。
- 候選之後可依 residual 執行 0／3／5-step 上半身 refinement，再經正式 safety gate。

## 輸出規則

Benchmark 必須同時保存：

- candidate joints／Mesh：閘門前模型真正產生的姿態。
- applied joints／Mesh：閘門後實際送往播放器的姿態；拒絕時為上一個可信姿態。

因此 HOLD 不會再被誤解成 SMPL pose 未讀入。

## 狀態

已完成三資料集離線 benchmark，但仍為隔離實驗版，不得直接取代 production；下一階段需做完整 Rig B 長序列、即時 bridge 與 Unity A/B 驗證。

## 2026-09-17 完整結果

測試範圍為 Rig B 實際錄製 30 幀、AMASS clean 233 幀、H3WB 280 幀。FPS 為 batch=1 core throughput，不含 I/O、UDP、Dashboard 與 Unity。

| 資料集 | FPS | Upper11 殘差 p50 | 採用率 | 最長 HOLD | AMASS MPVE p50 |
|---|---:|---:|---:|---:|---:|
| Rig B 錄製 | 14.95 | 55.19 mm | 100.00% | 0 | — |
| AMASS clean | 31.10 | 15.45 mm | 100.00% | 0 | 30.95 mm |
| H3WB | 30.98 | 29.22 mm | 99.29% | 2 | — |

AMASS 233 幀的 adaptive refinement 全部選擇 0-step；Rig B 因輸入雜訊較高，30 幀中有 14 幀使用 3-step、15 幀使用 5-step，因此場域 FPS 較低。AMASS applied Mesh 的 232 個相鄰轉場全部具有非零 vertex motion，平均每幀頂點位移 10.57 mm、p95 25.29 mm，證明修正後不再只有 root translation 移動。

與正式 50-step 相比，Hybrid v2 在 Rig B 的速度由 2.41 FPS 提升為 14.95 FPS，但 Upper11 p50 由 36.37 mm 增至 55.19 mm；它是速度／精度折衷，不是全面取代正式版。AMASS 上 v2 的 MPVE p50 為 30.95 mm，優於本次正式 50-step 的 93.11 mm，且沒有 v1 的長序列 HOLD。
