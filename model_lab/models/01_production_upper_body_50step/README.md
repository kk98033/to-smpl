# 01 — 場域穩健上半身 50-step 正式模型

## 方法

這是目前正式 Bridge 使用的方法，不會載入 Learnable-SMPLify 的 `NetBody25` checkpoint。它直接對每一幀的 SMPL root orientation、23 個 body rotations 與 translation 建立 Adam optimizer，執行 50 次完整 SMPL soft-target fitting。

```text
Body25 target
  → fixed-betas calibration
  → previous accepted pose / analytical root seed
  → 50 × full SMPL mesh forward + Body25 regression + Adam
  → safety gate
  → Protocol V2 / Unity
```

## Loss 與約束

- Upper11 joint loss。
- endpoint weight：0.5。
- torso orientation weight：0.05。
- spine stability weight：0.02。
- body-facing weight：0.01。
- temporal smooth weight：0.01。
- 下肢 SMPL local rotations 固定。
- neck、head、left/right wrist rotations 歸零，避免前後翻轉。

## Safety gate

- fitting residual：100 mm。
- twist：100°。
- frame delta：90°。
- facing mismatch：90°。
- rejected candidate 不更新 accepted state。

## 優點

- 直接對當前輸入目標最佳化，Rig B 上半身擬合精度最高。
- 約束與閘門適合目前遮擋嚴重的工業影像。

## 限制

- 每個 iteration 都執行完整 6,890-vertex SMPL forward，batch=1 成本高。
- 固定 50 iterations，簡單 frame 也不會提前停止。
- 永久固定下肢不適合乾淨全身動作資料。

## 正式程式

- `smpl_0901/service.py`
- `smpl_0901/fixed_betas_fitter.py`
