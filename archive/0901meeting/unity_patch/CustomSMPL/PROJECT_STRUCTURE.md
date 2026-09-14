# SMPL-test 專案結構文件

> 本文件記錄 Unity SMPL 動畫播放專案的完整結構，包含舊版（SUP 套件）與新版（CustomSMPL）播放器的架構比較。

---

## 目錄

1. [專案總覽](#專案總覽)
2. [目錄結構](#目錄結構)
3. [舊版播放器（SUP 套件）架構](#舊版播放器sup-套件架構)
4. [新版播放器（CustomSMPL）架構](#新版播放器customsmpl架構)
5. [新舊版詳細對照表](#新舊版詳細對照表)
6. [共用模組與依賴分析](#共用模組與依賴分析)

---

## 專案總覽

| 項目 | 說明 |
|------|------|
| **專案名稱** | SMPL-test |
| **專案路徑** | `f:\School\資策會\Unity\SMPL-test` |
| **用途** | 在 Unity 上播放 SMPL (Skinned Multi-Person Linear Model) 人體動畫 |
| **參考套件** | `com.biomotionlab.sup@1.2.0` (BioMotion Lab 的 SUP Viewer) |
| **自製播放器** | `Assets\CustomSMPL\` |

### 核心概念

```
JSON 動畫檔 (trans + poses) → 解析器 (JSON Parser) → Quaternion[] + Vector3[] → 播放器 (Player) → SMPL 角色骨架 (SkinnedMeshRenderer.bones) → 即時姿態更新 (每幀 Apply)
```

---

## 目錄結構

```
SMPL-test/
├── Assets/
│   ├── CustomSMPL/                          ← 🆕 自製播放器（核心開發）
│   │   ├── CustomAnimationPlayer.cs         ← 主要動畫播放腳本
│   │   ├── StandaloneHandTester.cs          ← 手指測試工具
│   │   ├── UI/                              ← 🆕 運行時動態 UI 系統
│   │   │   ├── AnimationUIManager.cs        ← UI 總管與初始化
│   │   │   ├── RuntimeUIBuilder.cs          ← 程式碼動態生成 UI
│   │   │   ├── FileBrowserPanel.cs          ← 檔案瀏覽與載入
│   │   │   └── PlaybackControlPanel.cs      ← 播放進度與控制
│   │   └── PROJECT_STRUCTURE.md             ← 本文件
│   │
│   ├── Samples/
│   │   └── bmlSUP/1.2.0/GUI Viewer/        ← SUP 套件的範例場景
│   │       ├── SUPViewer.cs                 ← 舊版播放入口腳本
│   │       ├── SUPViewer.unity              ← 舊版場景檔
│   │       └── SMPLX_Support/               ← SMPL-X 擴展支援
│   │
│   ├── Scenes/
│   │   └── SampleScene.unity                ← 主場景
│   │
│   └── TextMesh Pro/                        ← UI 文字套件
│
├── Library/
│   └── PackageCache/
│       └── com.biomotionlab.sup@1.2.0/      ← 📦 參考套件（原廠）
│           ├── Scripts/
│           │   ├── SMPLModel/               ← SMPL 模型核心
│           │   │   ├── Bones.cs             ← ⭐ 骨骼名稱 ↔ 關節索引映射
│           │   │   ├── CharacterPoser.cs    ← ⭐ 原廠姿態套用器
│           │   │   ├── CharacterComponent.cs← ⭐ 原廠角色元件
│           │   │   ├── CharacterTranslater.cs← 位移處理
│           │   │   ├── IndividualizedBody.cs ← 體型 Beta 調整
│           │   │   ├── ModelDefinition.cs    ← 模型定義（關節數等）
│           │   │   ├── AnimationData.cs      ← 動畫資料結構
│           │   │   └── ...
│           │   ├── Playback/                ← 播放控制
│           │   │   ├── SUPPlayer.cs         ← 原廠播放器
│           │   │   ├── AMASSAnimation.cs    ← 動畫封裝（含插值）
│           │   │   ├── Playback.cs          ← 播放計時器
│           │   │   └── ...
│           │   ├── FileLoaders/             ← 檔案載入
│           │   │   ├── LoadAnimationFromJSONFile.cs ← JSON 解析
│           │   │   └── ...
│           │   ├── Utilities/               ← 工具
│           │   │   ├── QuaternionExtensions.cs ← ⭐ ToLeftHanded / ToRightHanded
│           │   │   └── Vector3Extensions.cs   ← ⭐ ConvertTranslationFromMayaToUnity
│           │   ├── Display/                 ← 顯示相關
│           │   └── Settings/                ← 設定 ScriptableObject
│           ├── Prefabs/                     ← 預製物件
│           │   └── SUP_Player.prefab        ← 舊版 Player Prefab
│           ├── Models/                      ← SMPL/SMPLH 模型資源
│           │   ├── SMPL/
│           │   └── SMPLH/
│           └── ThirdParty/                  ← SimpleJSON 等第三方
```

---

## 舊版播放器（SUP 套件）架構

### 使用方式

舊版使用 **SUP_Player Prefab**，上面掛載以下腳本：

| 腳本 | 說明 |
|------|------|
| `SUPViewer` | 最上層入口，管理動畫載入與播放順序 |
| `UIManager` | UI 面板切換（Toggle Key = U） |

#### SUPViewer Inspector 欄位

| 欄位 | 對應型別 | 說明 |
|------|---------|------|
| Models | `Models` | 可用模型清單（SMPL / SMPLH） |
| Body Settings | `BodySettings` | 身體渲染選項（是否更新 pose、translation 等） |
| Display Settings | `DisplaySettings` | 顯示選項（Mesh、骨骼線、關節球等） |
| Playback Settings | `PlaybackSettings` | 播放選項（速度、循環、倒轉等） |
| Samples List Asset | `AnimationListAsset` | 預載動畫清單 |

### 舊版播放流程

```
SUPViewer → SUPLoader.LoadFromListAssetAsync() → AnimationJsonParser → AnimationData
         → SUPPlayer.Play(animationGroup) → AMASSAnimation.Reset() + CreateCharacter()
         → CharacterComponent.StartAnimation() → AMASSAnimation.AttachSkin()

每幀 Update:
  CharacterComponent → AMASSAnimation.PlayCurrentFrame()
    → GetResampledFrame()（含幀間插值 Quaternion.Slerp）
    → CharacterPoser.SetPoses(posesThisFrame)
    → CharacterTranslater.SetTranslation(translationThisFrame)
    → CharacterPoser.UpdatePoses()（套用到骨骼）
    → CharacterTranslater.UpdateTranslation()（套用位移）
```

### 舊版核心函數

#### `CharacterPoser.UpdatePoses()`（核心姿態套用）

```csharp
// 原廠 CharacterPoser.cs 第 74-98 行
void UpdatePoses() {
    for (int boneIndex = 0; boneIndex < bones.Length; boneIndex++) {
        string boneName = bones[boneIndex].name;
        
        // 1. 先清零旋轉
        bones[boneIndex].transform.localEulerAngles = Vector3.zero;
        
        // 2. Pelvis 特殊處理（Maya Z-up → Unity Y-up 的 -90 度修正）
        if (boneName == Bones.Pelvis) {
            bones[boneIndex].transform.Rotate(-90, 0, 0, Space.Self);
        }
        
        // 3. 用 Bones.NameToJointIndex 取得 pose 索引
        int poseIndex = Bones.NameToJointIndex[boneName];
        
        // 4. 累加旋轉（先有 -90 修正，再疊加 pose）
        bones[boneIndex].localRotation = bones[boneIndex].localRotation * poses[poseIndex];
    }
}
```

#### `AMASSAnimation.GetPosesAtFrame()`（幀間插值）

```csharp
// 使用 Quaternion.Slerp 在相鄰兩幀之間做球面線性插值
Quaternion[] GetPosesAtFrame(ResampledFrame resampledFrame) {
    for (int jointIndex = 0; jointIndex < Data.Model.JointCount; jointIndex++) {
        if (resampledFrame.IsFirstFrame) 
            posesThisFrame[jointIndex] = Data.Poses[0, jointIndex];
        else if (resampledFrame.IsLastFrame) 
            posesThisFrame[jointIndex] = Data.Poses[resampledFrame.FrameBeforeThis, jointIndex];
        else {
            posesThisFrame[jointIndex] = Quaternion.Slerp(
                Data.Poses[resampledFrame.FrameBeforeThis, jointIndex],
                Data.Poses[resampledFrame.FrameAfterThis, jointIndex],
                resampledFrame.PercentageElapsedSinceLastFrame);
        }
    }
}
```

---

## 新版播放器（CustomSMPL）架構

### 使用方式

新版使用一個空的 **`test` GameObject**，上面掛載：

| 腳本 | 說明 |
|------|------|
| `StandaloneHandTester` | 手指骨骼掃描與測試彎曲 |
| `CustomAnimationPlayer` | 🆕 主要動畫播放器 |
| `AnimationUIManager` | 🆕 UI 總管與運行時動態 UI 生成 |

#### CustomAnimationPlayer Inspector 欄位

| 欄位 | 說明 | 對應舊版 |
|------|------|---------|
| Character Prefab | SMPLH Character Female New | 取代舊版由 `Models` + `SUPPlayer` 自動建立角色 |
| Json File Path | JSON 動畫檔的**絕對路徑**（留空則由 UI 控制） | 取代舊版 `AnimationListAsset` + `SUPLoader` |
| Playback Speed | 播放速度（預設 1） | 對應舊版 `PlaybackSettings` |
| Target FPS | 目標幀率（預設 30） | 對應舊版 `AnimationData.Fps` |
| Freeze Position | 凍結位移（Debug 用） | 舊版無此功能 |
| Force Clench Fist | 強制握拳（Debug 用） | 舊版無此功能 |

### 新版播放流程

```
Start():
  1. Instantiate(characterPrefab)
  2. 關閉舊腳本 (CharacterPoser, CharacterComponent)
  3. SetupBones() — 取得 SkinnedMeshRenderer.bones
  4. LoadJsonData() — File.ReadAllText + JSON.Parse
  5. VerifyMapping() — 驗證骨骼對應
  6. isPlaying = true

每幀 Update:
  currentTime += deltaTime * playbackSpeed
  currentFrame = Floor(currentTime * targetFPS)
  ApplyFrame(currentFrame) → 透過 bones[] 直接設定 localRotation
```

---

### 新版完整 Function 結構

#### `CustomAnimationPlayer.cs` — 主類別

| 命名空間 | `CustomSMPL` |
|---------|-------------|
| 繼承 | `MonoBehaviour` |

---

##### `Start()` — 初始化（第 47-80 行）

```
流程：檢查 Prefab → 檢查 JSON → 生成角色 → 關閉舊腳本 → 設定骨架 → 載入資料 → 驗證映射 → 開始播放
```

| 步驟 | 動作 | 參考舊版 |
|------|------|---------|
| 1 | 檢查 `characterPrefab` 與 `jsonFilePath` 是否有效 | 舊版由 `SUPLoader` 處理錯誤 |
| 2 | `Instantiate(characterPrefab)` 生成角色 | 舊版由 `ModelDefinition.CreateCharacter()` 建立 |
| 3 | 停用 `CharacterPoser` 和 `CharacterComponent` | 🆕 **新版獨有**，防止舊腳本干擾 |
| 4 | 呼叫 `SetupBones()` | 同舊版 `CharacterPoser.Awake()` |
| 5 | 呼叫 `LoadJsonData()` | 取代舊版 `LoadAnimationFromJSONFile` + `AnimationJsonParser` |
| 6 | 呼叫 `VerifyMapping()` | 🆕 **新版獨有**，Debug 驗證用 |

```csharp
// 關閉舊腳本 — 新版獨有的處理
var oldPoser = instantiatedCharacter.GetComponentInChildren<CharacterPoser>();
if (oldPoser != null) oldPoser.enabled = false;
var oldComponent = instantiatedCharacter.GetComponentInChildren<CharacterComponent>();
if (oldComponent != null) oldComponent.enabled = false;
```

---

##### `SetupBones()` — 骨架設定（第 82-105 行）

| 項目 | 說明 |
|------|------|
| **作用** | 取得 `SkinnedMeshRenderer.bones` 陣列，找出 Pelvis 骨骼 |
| **參考舊版** | ✅ 直接使用原廠 `CharacterPoser.Awake()` 相同方式 |
| **共用依賴** | ✅ 使用原廠 `Bones.NameToJointIndex` 字典做映射驗證 |

---

##### `LoadJsonData()` — JSON 資料載入（第 107-187 行）

| 項目 | 說明 |
|------|------|
| **作用** | 讀取 JSON 檔案，解析 `trans` 和 `poses`，轉換為 Unity 座標系 |
| **參考舊版** | ✅ 核心邏輯取自原廠 `AnimationJsonParser.LoadPosesFromJoint()` |
| **新增功能** | ✅ 自動偵測 SMPL-H (52 joints) vs SMPL-X (55 joints) |

新版的一大改進：自動偵測 SMPL-X 格式並設定 `handIndexOffset = 3`，因為 SMPL-X 在關節 22-24 插入了 jaw、leye、reye，使手指索引整體偏移 +3。

**與舊版的對照：**

| 操作 | 新版做法 | 舊版做法 |
|------|---------|---------|
| 讀取 JSON | `File.ReadAllText` (同步) | `File.ReadAllText` (同步) → `JSON.Parse` (異步 Task) |
| 位移轉換 | ✅ `tMaya.ConvertTranslationFromMayaToUnity()` | ✅ 完全相同 |
| 旋轉轉換 | ✅ `raw.ToLeftHanded()` | ✅ 完全相同 |
| Quaternion 順序 | `(x, y, z, w)` — scipy `as_quat()` 輸出格式 | 同樣 `(x, y, z, w)` |
| 手指偵測 | 🆕 自動偵測手部資料品質 | 無此功能 |
| SMPL-X 支援 | 🆕 自動偵測 55 關節並偏移 | 無此功能 |

---

##### `VerifyMapping()` — 骨骼映射驗證（第 189-209 行）

| 項目 | 說明 |
|------|------|
| **作用** | 檢查 `bones[]` 中有多少骨骼能成功映射到 `Bones.NameToJointIndex` |
| **參考舊版** | ❌ **新版獨有** — 舊版無此驗證機制 |

---

##### `Update()` — 每幀更新（第 211-222 行）

| 項目 | 說明 |
|------|------|
| **作用** | 計算當前幀號，呼叫 `ApplyFrame()` |
| **參考舊版** | ⚠️ **簡化版** — 舊版用 `Playback.GetResampledFrame()` 做精確插值 |

**與舊版差異**：舊版使用 `Playback` 類別 + `ForwardsResampledFrame` 做精確的幀間 `Quaternion.Slerp` 插值；新版直接取最近整數幀（Floor），不做插值。

---

##### `ApplyFrame(int frame)` — 套用單幀姿態（第 229-290 行）

| 項目 | 說明 |
|------|------|
| **作用** | 核心！將指定幀的 pose 資料套用到所有骨骼 |
| **參考舊版** | ✅ **直接模仿** `CharacterPoser.UpdatePoses()` |
| **新增邏輯** | 🆕 SMPL-X 手指索引偏移、凍結位移、強制握拳 |

**與舊版 `UpdatePoses()` 的逐行比較：**

| 邏輯 | 舊版 CharacterPoser | 新版 CustomAnimationPlayer |
|------|---------------------|---------------------------|
| 清零旋轉 | ✅ `localEulerAngles = Vector3.zero` | ✅ 相同 |
| Pelvis 修正 | ✅ `Rotate(-90, 0, 0, Space.Self)` | ✅ 相同 |
| 取得 poseIndex | ✅ `Bones.NameToJointIndex[boneName]` | ✅ 使用 `TryGetValue`（更安全） |
| 套用旋轉 | ✅ `localRotation *= poses[poseIndex]` | ✅ 相同 |
| 位移處理 | ❌ 由 `CharacterTranslater` 分開處理 | ✅ 直接在 `ApplyFrame` 內設定 `localPosition` |
| SMPL-X 偏移 | ❌ 無 | 🆕 `actualJsonIndex = poseIndex + handIndexOffset` |
| 凍結位移 | ❌ 無 | 🆕 `freezePosition` 開關 |
| 強制握拳 | ❌ 無 | 🆕 `forceClenchFist` + Sin 波形動畫 |

---

##### `IsThumb(int jointIndex)` — 拇指判斷（第 224-227 行）

| 項目 | 說明 |
|------|------|
| **作用** | 判斷關節是否為拇指（用於握拳時改變彎曲軸） |
| **參考舊版** | ❌ **新版獨有** |
| **邏輯** | 左拇指 34-36，右拇指 49-51 |

---

#### `StandaloneHandTester.cs` — 手指測試工具

| 命名空間 | `CustomSMPL` |
|---------|-------------|
| 繼承 | `MonoBehaviour` |
| **參考舊版** | ❌ **完全獨立開發** |

##### `Start()` — 第 19-62 行

| 動作 | 說明 |
|------|------|
| 生成角色 | `Instantiate(characterPrefab)` |
| 掃描骨骼 | 用 `GetComponentsInChildren<Transform>()` 掃描所有子物件 |
| 過濾手指 | 關鍵字過濾：`index`, `middle`, `ring`, `pinky`, `thumb` |
| 分左右手 | 名稱以 `l` 開頭 → 左手，`r` 開頭 → 右手 |

##### `Update()` — 第 64-84 行

| 動作 | 說明 |
|------|------|
| Sin 波 | `pulse = (Sin(Time.time * 5f) + 1) / 2` → 0~1 呼吸頻率 |
| 彎曲角度 | `bendAngle = pulse * 90°` |
| 套用 | 左手 `Euler(0, 0, +angle)`，右手 `Euler(0, 0, -angle)` |

---

## 新舊版詳細對照表

### 架構層級對照

| 功能 | 舊版（SUP 套件） | 新版（CustomSMPL） |
|------|-----------------|-------------------|
| **入口腳本** | `SUPViewer` → `SUPPlayer` → `AMASSAnimation` | `CustomAnimationPlayer`（All-in-one） |
| **角色建立** | `ModelDefinition.CreateCharacter()` + `CharacterComponent` | 直接 `Instantiate(characterPrefab)` |
| **動畫載入** | `SUPLoader` → `AnimationJsonParser` → `AnimationData` | 直接 `File.ReadAllText` + `JSON.Parse` |
| **姿態套用** | `CharacterPoser.UpdatePoses()` | `ApplyFrame()` — 直接模仿 |
| **位移處理** | `CharacterTranslater`（獨立元件） | 直接在 `ApplyFrame()` 內處理 |
| **播放計時** | `Playback` 類別 + `ResampledFrame`（含插值） | 簡單 `deltaTime` 累加（無插值） |
| **UI 控制** | `UIManager` + `PlaybackEventSystem`（事件系統） | `AnimationUIManager` + `RuntimeUIBuilder`（程式碼動態生成） |
| **多動畫管理** | `animationSequence` 佇列，支援上/下一個 | 單一 JSON 檔案播放 |

---

## 共用模組與依賴分析

### 新版直接使用的原廠模組

| 原廠模組 | 使用方式 | 用途 |
|---------|---------|------|
| `Bones.NameToJointIndex` | 直接引用 | 骨骼名稱 → 關節索引映射 (0-51) |
| `Bones.Pelvis` | 直接引用 | Pelvis 常數字串 `"Pelvis"` |
| `QuaternionExtensions.ToLeftHanded()` | 擴充方法 | 右手座標系 → 左手座標系 Quaternion 轉換 |
| `Vector3Extensions.ConvertTranslationFromMayaToUnity()` | 擴充方法 | Maya 座標 → Unity 座標位移轉換 |
| `SimpleJSON (JSON.Parse)` | 直接引用 | JSON 檔案解析 |
| `CharacterPoser` | `GetComponentInChildren` → `enabled = false` | 防止舊腳本干擾新版播放 |
| `CharacterComponent` | `GetComponentInChildren` → `enabled = false` | 防止舊腳本干擾新版播放 |

### 座標轉換公式（新舊版共用）

**Maya (右手/Z-up) → Unity (左手/Y-up)：**

| 轉換 | 公式 | 原廠函數 |
|------|------|---------|
| **位移** | `x' = -x, y' = z, z' = -y` | `Vector3Extensions.ConvertTranslationFromMayaToUnity()` |
| **旋轉** | `x' = -x, y' = y, z' = z, w' = -w` | `QuaternionExtensions.ToLeftHanded()` |
| **Pelvis** | 額外 `Rotate(-90, 0, 0, Space.Self)` | 兩版都一樣 |

### 骨骼索引映射（`Bones.NameToJointIndex`）

| 區段 | 索引範圍 | 骨骼 |
|------|---------|------|
| 身體 | 0-21 | Pelvis(0), L_Hip(1), R_Hip(2), Spine1(3), L_Knee(4), R_Knee(5), Spine2(6), L_Ankle(7), R_Ankle(8), Spine3(9), L_Foot(10), R_Foot(11), Neck(12), L_Collar(13), R_Collar(14), Head(15), L_Shoulder(16), R_Shoulder(17), L_Elbow(18), R_Elbow(19), L_Wrist(20), R_Wrist(21) |
| 左手指 | 22-36 | lindex0-2(22-24), lmiddle0-2(25-27), lpinky0-2(28-30), lring0-2(31-33), lthumb0-2(34-36) |
| 右手指 | 37-51 | rindex0-2(37-39), rmiddle0-2(40-42), rpinky0-2(43-45), rring0-2(46-48), rthumb0-2(49-51) |

**注意**：`Bones.cs` 中 `L_Hand`(22) 和 `R_Hand`(23) 與 `lindex0`(22) 和 `lindex1`(23) 的索引**重複**！這是原廠的設計——手掌骨骼和食指基部共用同一個 joint index。

---

### 新版相對於舊版的改進與簡化

| 改進 | 說明 |
|------|------|
| 🆕 **SMPL-X 自動支援** | 偵測 55 關節 → 自動偏移手指索引 +3 |
| 🆕 **Debug 工具** | `freezePosition` 凍結位移、`forceClenchFist` 強制握拳、`StandaloneHandTester` 手指測試 |
| 🆕 **獨立性** | 不依賴 SUP 的事件系統、UI Manager、Settings ScriptableObject |
| 🆕 **直覺操作** | 只需拖入 Prefab + 填寫 JSON 路徑即可播放 |
| 🆕 **動態 UI** | 程式碼動態生成面板，支援檔案選擇、播放/暫停、速度控制，不依賴 Prefab |
| ⚠️ **簡化幀處理** | 無幀間插值（`Floor` 取整，非 `Slerp`） |
| ⚠️ **單一動畫** | 不支援動畫佇列，一次只播一個 JSON |
| ⚠️ **無體型調整** | 不讀取 `betas`，不做 `IndividualizedBody.UpdateBodyWithBetas()` |
