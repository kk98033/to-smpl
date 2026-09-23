# 03 — Analytical Upper-body IK + Short Exact Refinement 0916

## 目的

避免依賴論文神經網路的訓練分布，以本幀可觀測的肩、肘、腕骨向量直接建立接近目標的 SMPL 上肢旋轉，再用少量完整 SMPL iterations 精修。

## 方法

```text
Body25 target
  → analytical root orientation
  → 保留上一個 accepted pose 的脊椎與穩定關節
  → 解析式對齊左右 shoulder→elbow
  → 解析式對齊左右 elbow→wrist
  → 鎖定 lower body 與 neck/head/wrist forward rotations
  → 10/15/20-step exact SMPL refinement
  → 現行 safety gate
```

## 旋轉求解

- 由 fixed-betas SMPL rest skeleton 建立 kinematic chain。
- 對每個肩與肘計算「目前骨向量旋轉到目標骨向量」的最小 global rotation。
- 透過 parent global rotation 轉回 SMPL local axis-angle。
- 解析解只決定可觀測的 swing；無法由關節位置觀察的 axial twist 仍由 pose prior、spine stability 與 safety gate 控制。

## 與 02 coarse-to-fine 的差異

- 02 仍使用多次 gradient-based skeletal iterations，實測受到 Python/optimizer 與小 kernel launch 成本影響。
- 03 使用固定次數的幾何旋轉求解，之後只保留少量 exact iterations。

## 限制

- 單一骨向量無法決定 axial twist。
- 目標骨長與 fixed-betas SMPL 骨長不同時，不能完全重合。
- 快速動作仍需 safety gate 與重新捕捉策略。
