# 3D 關節轉 SMPL：必要性與加速研究

## 結論先行

如果唯一目的只是讓 Unity 骨架跟著 3D 關節動，**SMPL 並非必要**。可以直接把父子關節方向轉成 Unity local bone rotations，再加入 bind-pose offset、twist prior、關節限制與 temporal filter。這條路速度最快，也最適合固定 avatar。

若需要一致的人體表面、體型、可交換角色的標準姿態參數、碰撞／接觸位置、表面量測，或要把結果保存成可重建的 body model，SMPL 才有明確價值。SMPL 不只是「把骨架畫成人」，而是以固定拓撲、shape、pose blend shapes 和 skinning，將骨架姿態轉成一致的完整人體表面。官方說明亦指出 SMPL 同時提供 mesh、skeleton rig、shape 與 pose-dependent blend shapes，並相容一般圖形管線。

## 為什麼關節點不能唯一決定 SMPL

3D 關節位置只約束骨段方向與部分長度，無法唯一決定：

- 骨頭軸向 twist；相同肘、腕位置可對應多種前臂旋轉。
- 身體表面與體型 betas。
- 肩胛、脊椎、手腕等多關節間如何分配旋轉。
- 被遮擋關節與不可靠關節的合理姿態。

因此目前 fitter 使用 torso facing、spine stability、temporal smoothness、固定下肢與 safety gate。這些不是單純為了降低 joint error，而是在多解問題中選擇可播放、不中斷的解。

## 可行的加速路線

### A. 直接 Unity 骨架 IK（不使用 SMPL）

```text
Body25 / 59 points
  → 固定骨長與缺點補值
  → swing rotation（骨段方向）
  → twist prior / joint limits
  → temporal filter
  → Unity local rotations
```

適用：即時展示、固定 avatar、只需要骨架動作。

代價：沒有標準 SMPL surface／betas；不同 avatar 的 bind pose 與骨架定義需個別 retarget；肩、脊椎、腕 twist 仍需規則或模型。它可以與 SMPL 管線並存，成為低延遲模式。

### B. HybrIK 類型的解析式 swing + 神經 twist

HybrIK 直接由 3D joints 解出 body-part swing rotation，再由網路補 twist。這正好針對關節位置無法觀測軸向 twist 的問題，比逐幀完整 SMPL optimizer 更接近本系統需要的 skeleton-to-mesh 任務。

建議輸入目前的 Body25、confidence、fixed betas 與前幾幀姿態；輸出 SMPL rotations。最後只執行一次 SMPL forward。這是最值得先做的結構性原型。

### C. 重新訓練場域版 Learnable-SMPLify／teacher distillation

可行，而且最可能同時接近 OG 的速度與正式 fitter 的精度。Learnable-SMPLify 本身就是以單次 regression 取代 iterative fitting，論文報告相對 SMPLify 接近 200 倍加速。本機測試也顯示其 core 約 69–82 FPS，但原權重在 Rig B、H3WB 誤差偏大。

建議不要只用「上一幀預測 → 下一幀」的純遞迴訓練。較穩健的設計為：

1. 使用正式 50-step fitter 產生 teacher pose、root、translation 與 accepted/rejected 標籤。
2. 訓練資料混合 AMASS、H3WB 與 Rig B；對 AMASS 注入 Rig B 型態的遮擋、joint dropout、抖動與 axis／scale perturbation。
3. 輸入 8–16 幀 Body25 + confidence，加上上一個 accepted pose；輸出 6D rotations、root、translation 及 uncertainty。
4. 在 SMPL layer 上訓練 joint、rotation geodesic、torso facing、twist、temporal acceleration 與 teacher distillation loss。
5. 使用 scheduled sampling：訓練時有一部分歷史狀態改用模型自身輸出，避免只學到理想 teacher history。
6. rejected candidate 不回灌 recurrent state；低信心時 hold previous 或觸發較慢的 optimizer recovery。

這種設計不保證一定超越正式 optimizer 的精度，必須用固定三資料集測試；但它針對目前 OG 的真正弱點——domain shift 與 error accumulation——而非犧牲速度做更多 iterations。

### D. 雙速率 hybrid（推薦的產品路線）

```text
每幀：快速 neural / analytical IK（目標 30–80 FPS）
          ↓ confidence + safety gate
低信心／每 N 幀：40/50-step optimizer 校正 anchor
          ↓
只把 accepted anchor 回灌快速 tracker
```

若慢 optimizer 在背景執行，不阻塞即時輸出，使用者看到的是持續的快速姿態；校正結果僅在安全通過後更新 tracker anchor。這比每幀都跑 optimizer 更符合即時系統。

### E. 保留 optimizer，但移除每 iteration 的完整 mesh

目前每個 iteration 都建立完整 6,890 vertices，再用 regressor 得 Body25。可改為：

- iteration 期間只算 SMPL24／少數 surface landmarks 的 FK surrogate。
- 收斂後只做一次完整 SMPL mesh forward。
- 將固定 shape 下的常數預先計算，並以 CUDA graph／TensorRT 或自訂 fused kernel 減少 Python 與小 kernel launch。

先前 Python coarse-FK 原型沒有變快，原因是小張量 Adam 與多個 kernel launch 的 overhead；這不否定方法本身，但表示必須做向量化／編譯後實作，不能只在 Python 迴圈中替換 loss。

## 建議順序

1. 保留 `0916 40-step TF32` 作低風險候選，不立即取代正式版。
2. 建立「直接 Unity IK」低延遲 baseline，確認產品是否真的需要 SMPL surface。
3. 以正式 fitter 產生 teacher labels，訓練場域版 temporal Learnable-SMPLify。
4. 加入 uncertainty + 現有 safety gate；測試 rejected state 不回灌。
5. 組成快速每幀、慢速校正的雙速率 hybrid，再用固定 Rig B／AMASS／H3WB protocol 比較。

## 主要資料來源

- [SMPL 官方說明](https://smpl.is.tue.mpg.de/)：SMPL 的 shape、pose-dependent blend shapes、skinning 與圖形管線定位。
- [Learnable SMPLify（arXiv, 2025）](https://arxiv.org/abs/2508.13562)：以單次神經 regression 取代 iterative fitting，使用 temporal sampling、human-centric normalization 與 residual learning。
- [HybrIK（CVPR 2021）](https://openaccess.thecvf.com/content/CVPR2021/html/Li_HybrIK_A_Hybrid_Analytical-Neural_Inverse_Kinematics_Solution_for_3D_Human_CVPR_2021_paper.html)：3D joints 的解析 swing 與神經 twist 分解。
- [PLIKS（CVPR 2023）](https://openaccess.thecvf.com/content/CVPR2023/html/Shetty_PLIKS_A_Pseudo-Linear_Inverse_Kinematic_Solver_for_3D_Human_Body_CVPR_2023_paper.html)：將參數化人體求解改寫為 pseudo-linear IK，避免傳統反覆最佳化。
- [SPIN（ICCV 2019）](https://openaccess.thecvf.com/content_ICCV_2019/html/Kolotouros_Learning_to_Reconstruct_3D_Human_Pose_and_Shape_via_Model-Fitting_ICCV_2019_paper.html)：以 optimizer 產生監督、再由 regression 學習的 fitting-in-the-loop 思路。
