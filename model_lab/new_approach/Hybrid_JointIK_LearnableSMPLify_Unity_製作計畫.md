# 3D 關節點主導 + Learnable SMPLify 輔助之 Unity 人體姿態重建製作計畫書

## 1. 計畫目標

本計畫目標是將目前以 SMPL fitting 為核心的即時人體姿態重建流程，改造成以 **3D 空間關節點為主要姿態來源**，並由 **Learnable SMPLify OG 提供旋轉先驗與補充資訊** 的 Hybrid 架構。

主要目標如下：

- 保留目前 Pipeline 輸出的 59 個 3D 關節點
- Body17 作為人體骨架主要姿態來源
- Hand42 繼續直接驅動 Unity 手指
- Learnable SMPLify 不再負責完整人體姿態重建
- Learnable SMPLify 改為提供 twist、spine rotation distribution、遮擋時的 rotation prior
- Unity 最終姿態以空間關節點為主
- 保留 Safety Gate，避免錯誤姿態污染後續 frame
- 目標將目前約 3 FPS 的 50-step SMPL fitting 提升至即時等級
- 降低對完整 SMPL mesh forward 與大量 iterative optimization 的依賴

---

# 2. 現有系統

目前輸入為 59 個 3D joints：

```text
59 joints
├─ Body17
├─ Left Hand21
└─ Right Hand21
```

目前 Body 流程：

```text
Body17
→ Body25
→ SMPL fitting
→ root rotation
→ 23 body local rotations
→ translation
→ 6890 vertices
→ Unity
```

手部流程：

```text
Left / Right Hand21
→ Wrist-local coordinate
→ Unity hand retargeter
```

目前主要問題：

1. 每幀執行 50-step optimization
2. 每個 iteration 都涉及 SMPL forward
3. 推論速度約 3～4 FPS
4. 下半身遮擋容易造成不可靠輸入
5. 頭部與 wrist twist 本身缺乏充分觀測
6. Learnable SMPLify OG 雖然可達非常高 FPS，但直接用於場域資料時精度與長序列穩定性不足
7. Sequential inference 可能因前一幀誤差而累積

---

# 3. 新架構核心概念

新系統不再讓 SMPL 決定整個人體。

改成：

> 3D joints 決定可直接觀測的姿態
> Learnable SMPLify 提供難以從 joints 唯一決定的旋轉資訊

整體架構：

```text
Pipeline 59 joints
│
├─ Hand42
│   ↓
│ Wrist-local
│   ↓
│ Unity Fingers
│
└─ Body17
    ↓
Body25 + confidence
    │
    ├──────────────────────────────┐
    │                              │
    ↓                              ↓
Direct Skeleton Solver      Learnable SMPLify OG
    │                              │
Observed rotations            Rotation prior
    │                              │
    └──────────────┬───────────────┘
                   ↓
             Rotation Fusion
                   ↓
             Temporal Filter
                   ↓
              Safety Gate
                   ↓
          Unity Retarget Layer
                   ↓
               Avatar
```

---

# 4. Direct Skeleton Solver

## 4.1 Root Orientation

Root rotation 主要由實際 3D joints 計算。

可以使用：

```text
left hip
right hip
left shoulder
right shoulder
pelvis
neck
```

建立人體座標系。

例如：

```text
left_right =
left_shoulder - right_shoulder

up =
neck - pelvis

forward =
cross(left_right, up)
```

再正規化後形成 rotation matrix：

```text
R_root
```

Root rotation 以 Joint Solver 為主要來源。

Learnable SMPLify 僅作為：

- sanity check
- 異常偵測
- confidence 過低時 fallback

---

# 5. Shoulder Rotation

Shoulder 最主要的姿態可以直接從：

```text
shoulder → elbow
```

取得。

定義：

```text
upper_arm_direction =
normalize(elbow - shoulder)
```

將 Unity rest pose 的 upper arm direction 旋轉到目前觀測方向，即可得到主要 shoulder swing。

## 核心策略

```text
Swing
← 3D joints

Twist
← Learnable SMPLify
```

最終可表示為：

```text
R_final =
R_swing_from_joints
×
R_twist_from_smpl
```

這樣即使 Learnable SMPLify 的完整 shoulder rotation 有誤，仍不會讓上臂偏離實際 shoulder-elbow 方向。

---

# 6. Elbow Rotation

Elbow 可由以下三點直接解出：

```text
shoulder
elbow
wrist
```

定義：

```text
u = normalize(shoulder - elbow)
v = normalize(wrist - elbow)
```

Elbow flexion angle：

```text
angle = acos(dot(u, v))
```

另外可利用：

```text
cross(
    elbow - shoulder,
    wrist - elbow
)
```

得到手臂 bending plane 的 normal。

因此 Elbow 建議：

```text
Flexion / Bending
← 3D joints

Axial twist
← SMPL prior 或 Hand21
```

---

# 7. Forearm 與 Wrist

目前系統已有 Hand21，因此 wrist 不一定需要依賴 SMPL。

可以利用：

```text
wrist
index MCP
pinky MCP
```

建立手掌局部座標系。

因此：

```text
Forearm direction
← elbow → wrist

Palm orientation
← Hand21

Wrist rotation
← Palm local frame
```

Learnable SMPLify 在 wrist 部分可只作為參考，不作主要輸出。

---

# 8. Spine Rotation

Body17 並沒有直接觀測：

```text
spine1
spine2
spine3
```

因此 Direct Solver 可以先計算：

```text
pelvis orientation
torso orientation
```

得到：

```text
pelvis → torso 的總旋轉
```

Learnable SMPLify 在這裡不需要提供完整絕對旋轉，而可以只提供三節 spine 的旋轉分配比例。

例如：

```text
SMPL prediction

spine1 = 5°
spine2 = 9°
spine3 = 16°
```

若 Direct Solver 判定 pelvis 到 torso 總旋轉為 30°，則使用 SMPL 的比例：

```text
5 : 9 : 16
```

重新分配 30°。

如此可兼顧：

- Direct joints 的空間準確度
- SMPL learned human motion prior
- 較自然的 spine bending

---

# 9. Lower Body

目前場域中下半身常被工作台或設備遮擋。

因此維持現有策略。

當：

```text
knee confidence 低
ankle confidence 低
```

則：

```text
保持 previous accepted pose
```

而不是強迫：

```text
Joint IK
或
SMPL prediction
```

若重新偵測到高 confidence：

```text
hip confidence high
knee confidence high
ankle confidence high
```

再恢復 Direct IK。

---

# 10. 各骨骼資訊來源規劃

| Bone | 主要來源 | Learnable SMPLify 用途 |
|---|---|---|
| Root | Hip + Shoulder + Torso joints | Sanity check / fallback |
| Spine1 | Torso rotation | Rotation distribution |
| Spine2 | Torso rotation | Rotation distribution |
| Spine3 | Torso rotation | Rotation distribution |
| Neck | Neck / head joints | Rotation prior |
| Head | Head-related joints | Rotation prior |
| Shoulder | Shoulder → Elbow | Twist prior |
| Elbow | Shoulder / Elbow / Wrist | 少量 prior |
| Wrist | Hand21 | 少量或不用 |
| Fingers | Hand21 | 不使用 |
| Hip | 3D joints | Prior / fallback |
| Knee | 3D joints | Fallback |
| Ankle | 3D joints | Fallback |

---

# 11. Rotation Fusion

不建議直接把 Joint Solver rotation 與 SMPL rotation 做普通平均。

第一版優先採用可解釋的分工：

```text
Swing
← joints

Twist
← SMPL
```

第二階段才考慮 confidence-based quaternion fusion。

例如：

```text
joint confidence 高
→ joints 權重高

joint confidence 低
→ SMPL / previous pose 權重提高
```

概念：

```text
R_final =
Slerp(
    R_joint,
    R_smpl,
    weight
)
```

其中 weight 由 joint confidence 決定。

---

# 12. Learnable SMPLify 的角色修改

原本 Learnable SMPLify：

```text
Previous SMPL
+
Current Body25
→ Complete SMPL Pose
```

新架構：

```text
Previous SMPL
+
Current Body25
→ Rotation Prior
```

OG 不再負責：

```text
決定 elbow 到底在哪
決定 wrist 到底在哪
決定人體全部骨架方向
```

OG 主要負責：

```text
Shoulder twist prior
Forearm twist prior
Spine distribution
Neck / head prior
Occlusion fallback
Human motion prior
```

這樣 OG 即使存在一定 joint fitting error，也不會直接造成整個人體位置偏離。

---

# 13. Learnable SMPLify Iterative Refinement

第一版可直接測試：

```text
N = 1
N = 3
N = 5
```

流程：

```text
Current Body25
↓
Learnable SMPLify #1
↓
Pose 1
↓
Learnable SMPLify #2
↓
Pose 2
↓
Learnable SMPLify #3
↓
Pose 3
```

原論文 Supplementary 顯示 N=3 相較 N=1 有明顯改善，而 N=5 後收益已趨於有限。

因此建議正式版本優先考慮：

```text
1～3 pass
```

而不是直接使用大量 iterative optimizer。

---

# 14. Safety Gate

保留目前 Safety Gate。

建議檢查：

```text
Upper-body joint residual
Axial twist
Single-frame rotation delta
Upper / Lower body facing mismatch
```

流程：

```text
Hybrid candidate
↓
Safety Gate
```

通過：

```text
ACCEPT
↓
更新 previous accepted state
```

失敗：

```text
FAILED_HOLD
↓
不更新 previous accepted state
↓
Unity 保持上一個正常姿態
```

如此可避免：

```text
Frame N 出錯
↓
污染 Frame N+1 initialization
↓
連續越跑越歪
```

---

# 15. Unity Retarget

不能直接：

```text
Unity.localRotation = SMPL.localRotation
```

原因是：

```text
SMPL rest-pose bone coordinate
≠
Unity avatar rest-pose coordinate
```

需要建立：

```text
Source bone frame
→ Unity bone frame
```

的 calibration offset。

建議第一次載入角色時：

```text
SMPL / Source Rest Pose
+
Unity Rest Pose
↓
計算 bone calibration offset
```

Runtime：

```text
Source rotation
↓
Coordinate conversion
↓
Unity local rotation
```

所有運算應以 quaternion 或 rotation matrix 為主。

避免使用 Euler angle 作為中間主要表示法。

---

# 16. Root Motion

保留目前 root motion 設計。

```text
rootPosition =
current pelvis position
-
first valid pelvis position
```

Unity 接收：

```text
relative translation
```

而不是 camera/world absolute coordinate。

可另外加入：

```text
pelvis position low-pass filter
velocity limit
outlier rejection
```

降低單幀跳動。

---

# 17. 建議移除 Runtime 中不必要的 SMPL Mesh

若正式 runtime 只需要：

```text
bone rotations
```

則不應每幀產生：

```text
6890 vertices
```

建議正式架構：

```text
Learnable SMPLify
↓
Rotation prior
↓
Hybrid Solver
↓
Unity
```

只有 Dashboard、debug、validation 模式才額外執行：

```text
SMPL full mesh forward
```

這樣可以降低：

```text
GPU workload
memory bandwidth
latency
```

---

# 18. Optional Hybrid Optimizer

若 Neural + Direct IK 結果仍不夠精確，可以加入少量 refinement。

不再固定每幀：

```text
50-step optimizer
```

改成：

```text
Hybrid prediction
↓
Residual evaluation
```

若結果好：

```text
0 step
```

若稍差：

```text
3 step optimizer
```

若較差：

```text
5 step optimizer
```

若明顯異常：

```text
HOLD
或
Re-initialize
```

正式門檻需依 Rig B 實測 distribution 設定。

---

# 19. 預計正式 Pipeline

```text
Pipeline 59 Joints
│
├─────────────────────────────────┐
│                                 │
↓                                 ↓
Body17                           Hand42
↓                                 ↓
Body25 + Confidence          Wrist-local
↓                                 ↓
Direct Skeleton Solver         Fingers
│
├────────────────────┐
│                    │
↓                    ↓
Observed Rotation   Learnable SMPLify
                     ↓
                  Prior Rotation
│                    │
└──────────┬─────────┘
           ↓
      Rotation Fusion
           ↓
      Temporal Filter
           ↓
       Safety Gate
       /         \
     PASS        FAIL
      ↓            ↓
   ACCEPT         HOLD
      ↓
Unity Retarget
      ↓
Root Motion
      ↓
Unity Avatar
```

---

# 20. 實作階段

## Phase 1：Direct Skeleton Solver Prototype

先完成：

- Root orientation
- Shoulder swing
- Elbow flexion
- Torso orientation
- Hip direction
- Joint confidence filtering

先完全不使用 SMPL。

目的：

```text
確認 Body17 本身可以多準確地驅動 Unity skeleton
```

---

## Phase 2：加入 Learnable SMPLify Prior

加入 OG Learnable SMPLify。

優先使用：

- Shoulder twist
- Spine distribution
- Neck prior
- Root sanity check

不要一開始直接融合完整 24-joint rotation。

---

## Phase 3：Hand21 Orientation

利用 Hand21 建立 palm frame。

完成：

```text
Forearm
Wrist
Palm
Finger
```

之間的完整 rotation chain。

降低對 SMPL wrist rotation 的依賴。

---

## Phase 4：Safety Gate 整合

將目前的 Safety Gate 移植到 Hybrid pipeline。

保留：

- Accepted state
- FAILED_HOLD
- Previous valid pose

---

## Phase 5：OG Iteration Test

測試：

```text
N = 1
N = 3
N = 5
```

比較：

- FPS
- Upper-body residual
- Rotation stability
- Long sequence drift

---

## Phase 6：Optional Lightweight Refinement

測試：

```text
Hybrid only
Hybrid + 3-step optimizer
Hybrid + 5-step optimizer
```

確認是否仍需要 optimizer。

---

# 21. 驗證項目

建議至少比較以下四種方法：

```text
A. Learnable SMPLify OG

B. Current 50-step SMPL Fitting

C. Direct Joint IK

D. Direct Joint IK + Learnable SMPLify Prior
```

測試資料：

```text
Rig B
AMASS
H3WB
```

主要指標：

| 指標 | 說明 |
|---|---|
| FPS | Core inference speed |
| Upper11 p50 | 上半身 fitting residual 中位數 |
| Upper11 p95 | 上半身 fitting residual 95 percentile |
| Rotation Delta | Frame-to-frame rotation stability |
| Safety Gate Fail Rate | 被 HOLD 的比例 |
| Long Sequence Drift | 長序列是否逐漸偏移 |
| Unity Visual Stability | 實際 Avatar 動作品質 |

---

# 22. 預期優點

新架構預期具有以下優點：

1. 不再每幀強制跑 50-step SMPL optimization
2. 可直接利用 Pipeline 已經產生的 3D joints
3. 可大幅提高 FPS
4. Shoulder、Elbow 等明確可觀測骨骼不再依賴 Neural solver 猜測
5. Learnable SMPLify 只處理 twist 與人體先驗
6. 下半身遮擋不容易污染上半身
7. Hand21 可以提供 wrist 與 palm orientation
8. 保留 Safety Gate 可避免 sequential error accumulation
9. 可降低對 6890-vertex SMPL mesh 的 runtime 依賴
10. 架構較可解釋
11. 每一節 bone 的 rotation 來源都可以明確追蹤

---

# 23. 主要風險

## Twist Ambiguity

只有兩個 joint 無法決定 bone axial twist。

解法：

```text
SMPL prior
Hand21
Previous frame
Joint plane
```

共同提供資訊。

## Noisy 3D Joints

Direct IK 很容易直接反映 joint jitter。

解法：

```text
confidence filter
temporal filter
velocity limit
Safety Gate
```

## Unity Coordinate Difference

不同 Rig 的 local axis 不一致。

解法：

```text
Rest-pose calibration
Quaternion-based retarget
```

## Learnable SMPLify Drift

OG sequential inference 仍可能累積誤差。

解法：

```text
OG 不作唯一姿態來源
Direct joints 主導 swing
Safety Gate 保護 previous state
```

---

# 24. 最終建議

本計畫不建議直接完全移除 Learnable SMPLify，也不建議讓 Learnable SMPLify 繼續控制完整人體姿態。

建議定位為：

```text
3D Joints
=
主要幾何觀測

Learnable SMPLify
=
人體旋轉 Prior

Previous Accepted Pose
=
Temporal Prior

Safety Gate
=
錯誤隔離機制
```

最終目標：

```text
準確位置
來自 3D joints

合理旋轉
來自 Joint IK + SMPL Prior

穩定性
來自 Temporal + Safety Gate

手指
來自原始 Hand42

Unity
只接收融合後的 final local rotations
```

這會比目前完整依賴 50-step SMPL fitting 更適合即時場域部署，同時保留 Learnable SMPLify 在人體旋轉先驗方面的價值。
