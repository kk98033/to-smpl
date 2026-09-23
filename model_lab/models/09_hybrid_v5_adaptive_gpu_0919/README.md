# 09 — Hybrid v5 Adaptive Batched IK（0919）

## 定位

隔離實驗版，不修改正式 bridge。目標是在無法取得每關節 2D confidence 的條件下，同時改善 v4 的吞吐量與快速動作精度。

## 輸入與輸出

- 輸入：Body25 3D joints、fixed betas、上一個 accepted SMPL pose。
- 不需要：每關節 2D confidence。
- 輸出：SMPL root、23 個 local body rotations、translation、Body25 joints 與完整 Mesh。

## 流程

```text
Body25 3D joints
  → causal 3D geometry quality（速度／骨長一致性）
  → 最近 5 幀 pelvis-aligned motion coherence + speed
  ├─ coherent motion：每幀 OG prior + 0/2/4 refinement
  └─ noisy / slow：每 4 幀 OG prior + 0/1/2 refinement
  → cached fixed-beta rest joints / neutral Body25
  → two-level arm IK（左右肩一起、左右肘一起）
  → 3–4 個 root hypotheses 以單次 batched SMPL forward 評分
  → torso／左右臂 regional safety gate
  → accepted 完整 SMPL pose／Mesh
```

## Motion coherence

最近至多 5 幀先以 pelvis 對齊。對每個 Upper11 joint 計算：

```text
coherence = ||最後位置 - 最初位置|| / Σ||逐幀位移||
```

再取關節平均。最終設定：

- `coherence >= 0.55`
- 平均路徑速度 `>= 0.3 m/s`
- 最大 OG 間隔：4 幀

這能區分連續動作與高頻抖動；本次資料的 coherence median 為 Rig B 0.296、AMASS 0.897、H3WB 0.504。

## 等價工程加速

1. fixed betas 不變，因此 rest joints 與 neutral Body25 每段只計算一次。
2. 左右肩同層互不依賴，左右肘亦同；每個 root 的 FK 從 4 次降為 2 次。
3. root hypotheses shape 相同，以一個 batch 做完整 SMPL LBS，而不是分別啟動 3–4 次。

固定排程 A/B 中，cached/two-level IK 的 joints、vertices 與 root 選擇完全相同；batched root 的最大數值差小於 `6e-7 m`，root 選擇相同。

## 完整結果

| 資料集 | v3 FPS | v4 FPS | v5 FPS | v3 Upper11 p50 | v5 Upper11 p50 |
|---|---:|---:|---:|---:|---:|
| Rig B | 23.03 | 34.98 | 50.99 | 53.12 mm | 54.38 mm |
| AMASS | 33.21 | 48.22 | 55.90 | 15.46 mm | 16.95 mm |
| H3WB | 33.25 | 49.19 | 64.05 | 30.05 mm | 28.86 mm |

AMASS pelvis-aligned MPVE p50：v3 30.95 mm、v4 39.06 mm、v5 32.62 mm。AMASS 時序加速度 p95：v3 14.78 mm、v4 71.02 mm、v5 16.16 mm。

Rig B 三次重複量測為 `50.72 ± 0.25 FPS`。

## 未採用的實驗

- `torch.compile(mode="reduce-overhead")`：單獨 SMPL forward 快約 5.2%，但完整 Rig B 路徑慢 22%，因此不啟用。
- 完全取消 refinement：雖可到 40–49 FPS（舊 solver），Rig B p50 增至 82–89 mm，不採用。
- joint-only 宣稱等價：Upper11 regressor 涉及 3,558／6,890 vertices，直接以 SMPL24 FK 取代會改變 loss 定義，需另立實驗。

## 限制

- Rig B 正式比較片段只有 30 幀，仍需要更長場域錄影與 Unity A/B。
- v5 仍保留 SciPy rotation 與部分 CPU／GPU轉換；目前已不是端到端系統瓶頸。
- 本結果的 FPS 不含上游 2D／3D pipeline、UDP、Dashboard 與 Unity。
