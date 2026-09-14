# CustomSMPL 播放器模組詳細說明

在 Unity 專案中的 `Assets/CustomSMPL` 資料夾內，包含了多種不同用途的播放器 (Players) 與測試工具，主要負責將 3D 關節點 (Joints) 以及 SMPL 參數化模型姿勢 (Poses) 套用到 Unity 的角色或骨架上。這些工具可透過上方選單 `CustomSMPL` 中的選項一鍵生成至場景中。

以下詳細說明各播放器的用途與核心功能：

---

## 1. RealtimePipelinePlayer (即時串流播放器)

**腳本位置：** `RealtimePipelinePlayer.cs`
**生成選單：** `CustomSMPL -> Setup Realtime Pipeline Scene`
**主要用途：** 作為串流接收端，透過 UDP Socket 實時接收外部 (例如 Python 推論管線) 傳送過來的 SMPL / SMPJ 封包，並同步驅動 3D 模型與骨架。

### 核心功能與特點：
- **UDP 即時接收**：透過獨立的背景執行緒 (Thread) 監聽指定的 Port (預設 9095)。支援接收二進位封包。
- **封包解析**：
  - **`SMPL` / `SMPJ` 封包**：包含 Frame ID、全域位移 (Translation) 以及 156 維的 SMPL 關節旋轉 (Pose) 資料。`SMPJ` 還會額外包含 67 個 3D 關節點座標。
  - **`VIDE` 封包**：傳送原始影片路徑，通知 Unity 的 `VideoPlayer` 自動讀取並同步播放對照影片。
- **雙軌渲染**：
  - **SMPL 模型驅動**：利用 `SkinnedMeshRenderer` 取得模型的 Bones，將收到的 Axis-Angle 資料轉為 Quaternion 並加上座標系轉換，實時套用到人物模型上。支援凍結下半身 (Freeze Lower Body)。
  - **骨架渲染 (Skeleton Visualization)**：使用 67 顆 Sphere 作為關節節點，並使用 `LineRenderer` 依照 Body25 + 手指拓樸結構連接成骨架線條。
- **快取與回放 (Playback Mode)**：收到的串流資料會存入記憶體快取 (Cache)，在斷開串流後可切換為回放模式，搭配 UI 進行進度條拖曳 (Scrubbing) 觀看。

---

## 2. CustomAnimationPlayer (離線 SMPL JSON 播放器)

**腳本位置：** `CustomAnimationPlayer.cs`
**生成選單：** `CustomSMPL -> Setup Player Scene`
**主要用途：** 用於讀取並播放預先算好的 `.json` 動畫檔 (包含 SMPL-H 或 SMPL-X 格式的 Trans 和 Poses 資料)，不涉及網路串流，完全在本地端運作。

### 核心功能與特點：
- **JSON 解析與記憶體載入**：一次性將 JSON 動畫的所有影格載入記憶體。
- **格式自動偵測 (SMPL-H vs SMPL-X)**：
  - 若解析出關節數量為 52，視為 SMPL-H。
  - 若解析出關節數量為 55，視為 SMPL-X，並自動處理手指索引的偏移 (+3)。
- **精準的骨骼對應**：與 `RealtimePipelinePlayer` 相同，透過比對 Unity Bones 名稱與預定義的字典 (如 `Bones.NameToJointIndex`) 來完成套用。
- **Debug 工具**：提供 `freezePosition` (凍結原地位移) 以及 `forceClenchFist` (強制無視手指資料，讓雙手呈握拳張開的循環動畫，方便 Debug 手指權重)。

---

## 3. H36MAnimationPlayer (Human3.6M 資料集專用播放器)

**腳本位置：** `H36M/H36MAnimationPlayer.cs`
**生成選單：** `CustomSMPL -> Setup H36M Player Scene`
**主要用途：** 專門用來讀取、解析及播放 Human3.6M (H36M) 原生 3D 關節點 JSON 資料。

### 核心功能與特點：
- **純骨架渲染 (No Mesh)**：這個播放器**不會**套用 SMPL 模型，而是純粹建立 17 個球體 (Spheres) 與線段 (LineRenderers) 來構成 H36M 的骨架。
- **非同步讀取 (Async Loading)**：由於 H36M 資料集 JSON 檔案通常十分龐大，載入過程放入背景執行緒 (`Task.Run`)，避免主執行緒 (Main Thread) 卡頓 (UI 凍結)。
- **動作分類與切換**：解析後的資料庫結構為 `[Action][Subaction] -> Sequence` (例如：Walking、Eating、Sitting 等)。可以透過腳本 API (通常搭配 UI) 在各個動作片段之間切換與播放。

---

## 4. StandaloneHandTester (手部骨架獨立測試器)

**腳本位置：** `StandaloneHandTester.cs`
**主要用途：** 開發與除錯階段使用的輕量化測試工具。當你匯入了一個新的 SMPL 模型但不確定手指的 Rigging 是否正確時，可掛載此腳本進行測試。

### 核心功能與特點：
- **自動掃描手指**：在 `Start()` 時自動往下遍歷子物件，利用關鍵字 ("index", "thumb", "left", "l_" 等) 自動分類左手與右手的手指關節。
- **動態彎曲測試**：在 `Update()` 中利用 Sin 函數 (`Mathf.Sin`) 產生平滑的數值，強制將所有手指在 Z 軸來回彎曲 (0 ~ 90度)，模擬手部握拳到張開的呼吸動態，藉此用肉眼快速驗證手指綁定與轉動軸向是否正常。

---

## 5. Editor/CustomSMPLSetup.cs (編輯器一鍵生成腳本)

**主要用途：** 定義在 Unity 頂部選單 `CustomSMPL` 中的功能。
- 利用 `GameObject.Find` 檢查場景中是否已有對應的 Player，若無則生成新的 GameObject 並掛載正確的腳本 (`RealtimePipelinePlayer` / `CustomAnimationPlayer` / `H36MAnimationPlayer`)。
- 自動從 `Packages/` 路徑尋找並綁定預設的 SMPL-H Character Prefab，以及一併生成關聯的 UI 控制面板 (Manager)，大幅降低使用者的環境建置成本。
