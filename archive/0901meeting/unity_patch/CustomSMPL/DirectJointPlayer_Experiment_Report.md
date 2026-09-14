# CustomSMPL 播放器總覽與 DirectJoint 實驗報告

本文整理 `Assets/CustomSMPL` 內目前幾個播放器的定位，並說明 `DirectJointPlayer.cs` 為什麼會讓人體模型扭曲，以及已做的修正方向。

## 結論先講

有，一個播放器就是 `H36M/H36MAnimationPlayer.cs`。它可以讀取 Human3.6M 類型的 17 個 3D 關節點，將關節點轉成 Unity 座標，並用 Sphere + LineRenderer 在 Unity 裡把骨架連起來播放。

如果要回答「為什麼不直接用關節點操控 3D 模型，而要轉 SMPL？」這個問題，`DirectJointPlayer` 是很適合做實驗的方向。但直接用 17 個關節點驅動 SMPL-H mesh，通常只能得到近似姿態，不能完整取代 SMPL 參數。原因是 17 個點缺少人體 mesh 需要的完整資訊，例如身形、骨長、骨盆/胸腔/肩膀 twist、腳掌方向、手指、局部關節旋轉自由度，以及 SMPL-H rig 原本的 bind pose 約束。

SMPL 轉換不是完全多餘。它的價值是把稀疏關節點或影片推論結果轉成一組符合人體模型拓樸、骨長和姿態先驗的參數，讓 mesh 變形比較穩定、可重播、可比較，也比較不會因為單幀關節噪聲把人物拉壞。代價是多一道最佳化或回歸步驟，會有性能成本，也可能因模型或座標轉換錯誤導致誤差。

所以最合理的回答不是「一定要 SMPL」或「一定不要 SMPL」，而是做 A/B 實驗：

- H36M skeleton player：只顯示輸入關節點，當 ground truth/輸入檢查工具。
- DirectJoint player：同樣吃 H36M 空間座標，直接驅動 SMPL-H mesh 的骨架旋轉，觀察不用 SMPL pose 會長怎樣。
- SMPL player：用 SMPL/SMPL-H pose 正規驅動 mesh，作為品質和穩定度基準。

## 目前播放器

### `CustomAnimationPlayer.cs`

用途：離線 SMPL JSON 播放器。

它讀取包含 `trans` 和 `poses` 的 JSON，將 axis-angle pose 轉為 Unity bone localRotation，再套到 SMPL-H 或 SMPL-X 類型的角色 prefab 上。這是「已經有 SMPL pose 參數」時的標準播放器。

入口：`CustomSMPL -> Setup Player Scene`

場景物件：

- `CustomSMPL_Player`
- `AnimationUI`

適合用途：

- 播放已轉好的 SMPL-H/SMPL-X 動畫。
- 檢查 SMPL pose JSON 是否能正確套到 Unity prefab。
- Debug 手指、全身旋轉、root translation。

### `H36M/H36MAnimationPlayer.cs`

用途：Human3.6M 17 關節點骨架播放器。

它讀取 `Assets/hu36_dataset/Human36M_subject1_joint_3d.json` 這類資料，格式大致是：

```text
Action -> Subaction -> Frame -> 17 x [x, y, z]
```

它會做座標轉換：

```text
H36M: x, y, z，單位 mm，Z-up
Unity: x/1000, z/1000, y/1000，單位 m，Y-up
```

然後建立 17 顆關節球與 16 條骨架線。

入口：`CustomSMPL -> Setup H36M Player Scene`

場景物件：

- `H36M_Player`
- `H36M_UI`

適合用途：

- 檢查 Human3.6M 關節點資料本身是否正確。
- 只看 skeleton，不牽涉 SMPL mesh。
- 作為 DirectJoint 實驗的資料解析與 UI 參考基底。

### `RealtimePipelinePlayer.cs`

用途：即時串流播放器。

它透過 UDP 接收外部 pipeline 傳來的封包。主要支援：

- `SMPL` / `SMPJ`：SMPL pose、translation，以及可選的 3D joints。
- `VIDE`：影片路徑，用 Unity `VideoPlayer` 同步顯示原影片。

它可以同時渲染：

- SMPL-H mesh。
- 關節點與骨架線。
- 原始影片面板。

入口：`CustomSMPL -> Setup Realtime Pipeline Scene`

場景物件：

- `RealtimePipeline_Player`
- `RealtimePipeline_UI`

適合用途：

- 外部 Python / 推論管線即時把結果送到 Unity。
- 展示「影片、SMPL mesh、關節骨架」同步結果。
- 收到資料後快取並回放。

### `DirectJointPlayer.cs`

用途：實驗性播放器，測試「直接用 H36M 類型空間關節點驅動 SMPL-H mesh」。

入口：`CustomSMPL -> Setup Direct Joint Experiment Scene`

場景物件：

- `DirectJointExperiment`

它沿用 H36M 類型 JSON 的讀法，建立紅色 target joints，並實例化 SMPL-H character prefab。這個播放器不是標準 SMPL 流程，而是用來比較「不用 SMPL pose，直接讓 3D 模型跟關節點動」會發生什麼。

## DirectJoint 原本為什麼會扭曲

原本版本的核心問題是：每幀直接做 `mappedBones[i].position = targetWorldPos`。

這對 SkinnedMeshRenderer 的骨架很危險，原因如下：

- SMPL-H mesh 是用 bind pose 綁定到一整套骨架階層，不是 17 個可任意移動的點。
- 直接改 bone world position 會破壞 parent-child 局部關係。
- 骨長會被迫伸縮，mesh 權重因此被拉扯。
- 沒有設定 localRotation，所以骨頭方向、twist、關節彎曲軸都沒有被正確求解。
- H36M 只有 17 點，SMPL-H 有更多身體、手部和細節骨頭；未被控制的骨頭會留在原本位置或被父骨架扯動。

所以模型扭曲不是單純座標軸正負號錯，而是驅動方式本身錯了。紅點可以對，但 mesh 會壞。

## 已做修正

我已將 `DirectJointPlayer.cs` 改成實驗用的「方向旋轉驅動」：

1. 建立角色時記錄所有 SMPL-H bones 的 bind pose localPosition/localRotation。
2. 建立 H36M joint index 到 SMPL-H bone name 的映射。
3. 先用 H36M 的左右 hip 和 spine 建立 pelvis/root basis，推算整個角色根部朝向。
4. 每幀先把角色骨架重設回 bind pose。
5. 角色 root 移到輸入 pelvis 的位置。
6. 對四肢、脊椎、頭部等 pair 計算輸入關節方向，再用 `Quaternion.FromToRotation` 把 bind pose 中對應的骨頭方向轉到輸入方向。腿部從 `Hip->Knee` 開始，不再用 `Pelvis->Hip` 當 limb driver，避免骨盆被左右腿方向重複拉扯。
7. 紅色 target points 仍然顯示原始 H36M 輸入位置，方便比較 mesh 和輸入 skeleton 的差距。

這樣做的結果會比原本穩定很多，因為它不再強迫 bone position 破壞骨架階層。但它仍然不是完整 IK，也不是 SMPL pose fitting。

## Animation Rigging IK 版本

為了更接近「直接用關節點驅動普通人體模型」的做法，我已在 `Packages/manifest.json` 加入：

```json
"com.unity.animation.rigging": "1.2.1"
```

`DirectJointPlayer.cs` 也新增 `useAnimationRiggingIK` 選項。啟用時，角色生成後會自動建立：

- `RigBuilder`
- `DirectJoint_IK_Rig`
- `LeftLeg_IK`
- `RightLeg_IK`
- `LeftArm_IK`
- `RightArm_IK`

四肢使用 Unity Animation Rigging 的 `TwoBoneIKConstraint`，讓手腕和腳踝追 H36M 的 target spheres，膝蓋和手肘使用對應中段關節當 hint。這才是「拿座標點操控骨架模型」比較正確的方向：座標點當 IK target，模型骨頭仍然用 rotation 變形。

實測發現如果同時啟用手算 `Quaternion.FromToRotation` rotation drivers 和 Animation Rigging IK，上半身會先被 spine/neck/head 的近似方向扭歪，IK 再拉四肢，結果仍然會變形。因此目前 `useManualRotationDrivers` 預設關閉；開 IK 時只保留 root 平移與四肢 IK。

若四肢呈現交叉，通常代表資料的 left/right label 與 SMPL-H prefab 的左右方向相反，或座標系有鏡像。`DirectJointPlayer` 目前提供 `swapLeftRightIKTargets`，預設開啟；它只交換 IK target，不改原始紅點位置，方便直接驗證左右映射。

## 修正後仍會存在的限制

DirectJoint 仍可能和紅點不完全重合，這是正常實驗結果：

- SMPL-H prefab 的骨長和 H36M subject 的骨長不一定一樣。
- 17 點不足以決定完整 3D 人體 pose。
- 沒有解 twist，例如上臂旋轉、前臂旋轉、股骨內外旋。
- H36M 沒有腳尖、手指、手掌朝向等資訊。
- 肩膀/鎖骨/胸腔在 SMPL-H 裡不是一個單點能完全決定。
- 沒有 IK solver，所以子關節不保證精準貼到 target point。

如果要讓 mesh 更貼 H36M target joints，但仍不走 SMPL fitting，可以再做第二版：

- 使用 Unity Animation Rigging 或自寫 CCD/FABRIK IK。
- 先依 H36M subject 和 SMPL-H bind pose 做身高/骨長縮放。
- pelvis/root 已用左右 hip 和 spine 估計 orientation；若仍歪斜，下一步要檢查資料座標手性與左右髖映射。
- shoulder、elbow、knee 加 pole vector，避免彎曲方向翻轉。
- feet/hands 沒資料時加穩定的預設方向。

## 是否需要轉成 SMPL

我的判斷是：如果最後目標是「穩定、自然、可交付的人體 mesh 動畫」，轉成 SMPL/SMPL-H 通常仍有必要。

直接關節驅動適合：

- 即時視覺化。
- Debug 關節點資料。
- 對性能極敏感、只要大概姿態的應用。
- 向業主展示不用 SMPL 時會少掉哪些資訊。

SMPL 適合：

- 要自然的人體 mesh。
- 要跨人物、跨資料集一致。
- 要保留手、身形、骨盆、胸腔、肩膀等完整姿態語意。
- 要後續輸出、重播、比較、評分或再編輯。

因此這個實驗很值得做。它能很直觀回答：直接操控 3D 模型確實省掉 SMPL 轉換成本，但品質和穩定性會輸在人體參數不足。若業主只看 skeleton，H36M player 就夠；若業主要可看的 3D 人體 mesh，SMPL 的穩定性仍然有價值。

## 驗證狀態

我嘗試用命令列執行：

```powershell
dotnet build F:\School\資策會\Unity\SMPL-test\Assembly-CSharp.csproj --no-restore
```

但本機缺少 `.NET Framework 4.7.1 Developer Pack`，build 在載入 Unity C# project 參考前就停止，錯誤是 MSB3644。這不是 Unity 程式碼本身的編譯結果。

建議在 Unity Editor 內重新切回專案，等待 Unity 自動 compile。若 console 沒有 C# error，再用：

```text
CustomSMPL -> Setup H36M Player Scene
CustomSMPL -> Setup Direct Joint Experiment Scene
CustomSMPL -> Setup Player Scene
```

分別比較 skeleton、direct joint mesh、SMPL pose mesh 的差異。
