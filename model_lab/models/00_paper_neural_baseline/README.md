# 00 — 論文原始神經網路模型

## 方法

使用 Learnable-SMPLify 的 `NetBody25`。模型接收上一幀 SMPL 所回歸的 Body25 與本幀目標 Body25，在標準化人體座標中預測 root/body rotation 的增量。

```text
上一幀 SMPL pose + 本幀 Body25
  → normalize_kp
  → ST-GCN backbone
  → pose-delta regressor
  → SMPL forward
```

## 初始化

- 第一個 frame 使用解析式 root orientation 加完整 optimizer seed。
- 後續 frame 使用前一個神經網路輸出作為遞迴狀態。
- fixed betas 在各資料集內固定。

## 優點

- 單次神經推理，吞吐量高。
- 在乾淨且接近訓練分布的資料上表現良好。

## 限制

- 不直接對本幀目標反覆最佳化。
- 前一幀錯誤可能污染後續遞迴狀態。
- 場域遮擋、座標噪聲或動作分布差異可能增加擬合殘差。

## 模型來源

- 程式：`archive/Learnable-SMPLify/src/`
- 權重由 benchmark CLI 指定；權重不複製進本目錄。
