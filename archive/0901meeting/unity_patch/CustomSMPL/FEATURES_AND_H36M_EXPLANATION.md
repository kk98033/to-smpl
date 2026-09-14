# Unity Custom SMPL & H3.6M 播放器系統功能與輸入詳解
# Features & H3.6M Dataset Input Explanation

本文件詳細記錄了本專案中所有新增與優化的功能模組，並針對 **Human3.6M (H3.6M) 播放器的資料輸入格式與解析坐標變換** 進行技術分析。

---

## 一、 已實作新增功能總覽

目前在自製播放器系統（`CustomSMPL`）中，共完成並整合了以下五大核心模組：

### 1. 編輯器一鍵場景建置工具
* **相關腳本**：[CustomSMPLSetup.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/Editor/CustomSMPLSetup.cs)
* **詳細功能**：
  * 在 Unity 編輯器頂部選單新增 `CustomSMPL` 工具列。
  * **`Setup Player Scene`**：自動在場景中建立 SMPL 播放器（`CustomSMPL_Player`）、自動載入並綁定女性角色 Prefab、配置動態 UI，一鍵完成所有參考連結。
  * **`Setup H36M Player Scene`**：自動在場景中建立 H3.6M 關節播放器物件（`H36M_Player`）與其專屬控制面板（`H36M_UI`），並自動填入資料庫 JSON 路徑。

### 2. 進階互動式播放時間軸與控制面板 (UI)
* **相關腳本**：
  * SMPL UI：[RuntimeUIBuilder.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/UI/RuntimeUIBuilder.cs)、[PlaybackControlPanel.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/UI/PlaybackControlPanel.cs)
  * H3.6M UI：[H36M_UIBuilder.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/H36M/UI/H36M_UIBuilder.cs)、[H36M_UIManager.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/H36M/UI/H36M_UIManager.cs)
* **詳細功能**：
  * **互動式時間軸進度條 (Scrubbing)**：將進度條升級為可點擊拖曳的互動式時間軸。在暫停狀態下拖曳，角色也會即時更新對應幀的姿態。
  * **事件回授防護機制**：實作了「暫時移除監聽、更新數值、重新載入監聽」的邏輯，避免了「播放器更新 Slider 數值」與「使用者手動拖曳 Slider」之間產生的無窮回授事件迴圈。
  * **播放控制與變速**：支援 0.1x 至 5.0x 的動態變速 Slider、Pause/Resume 按鈕切換、Stop 停止並銷毀角色。
  * **一鍵隱藏 (Hotkey H)**：按下鍵盤 `H` 鍵可隨時隱藏或顯示左側的所有 UI 面板，方便無干擾地觀察骨骼動作。
  * **即時渲染幀率 (Render FPS) 顯示**：在控制面板下方的資訊列，除了動畫原本的取樣 FPS 外，新增了電腦目前的即時繪圖幀率顯示（透過 `unscaledDeltaTime` 的平滑移動平均計算），方便監控效能與掉幀情況。

### 3. SMPL-X 格式自動偵測與手指映射修正
* **相關腳本**：[CustomAnimationPlayer.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/CustomAnimationPlayer.cs)
* **詳細功能**：
  * **關節數自動判定**：讀取 JSON 時，若偵測到 `numJoints == 55`，系統會自動將播放器切換至 SMPL-X 模式（傳統 SMPL-H 則為 52 個關節）。
  * **手指索引偏移處理 (+3 Offset)**：SMPL-X 在身體與手指骨骼之間插入了下顎（jaw）與左右眼（leye, reye）共 3 個關節，導致傳統播放器的手指動畫全部錯位。我們實作了自動偏移邏輯，當判定為 SMPL-X 時，手指關節索引自動加 3，使手指動畫能正確播出來。
  * **Debug 輔助模式**：
    * `Freeze Position`：鎖定在原點，方便觀察原地旋轉。
    * `Force Clench Fist`：強迫以正弦波頻率進行握拳與開掌，便於測試手部極限角度。
    * [StandaloneHandTester.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/StandaloneHandTester.cs)：手指骨骼掃描與極限彎曲測試獨立工具。

### 4. 檔案載入防錯驗證機制 (JSON Format Validation)
* **相關腳本**：[CustomAnimationPlayer.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/CustomAnimationPlayer.cs)
* **詳細功能**：
  * 防止使用者在 SMPL 播放器中誤載入 Human3.6M 的 3D 座標 JSON 檔。
  * 加入 JSON 欄位驗證，若缺少關鍵字 `trans` 或 `poses`，會直接拒絕載入並呼叫 `StopAndCleanup()` 復原場景。
  * 在 Console 輸出明確的警告：`[CustomPlayer] 載入失敗：此檔案為 Human3.6M 格式，請使用選單中的 H36M Player 播放器！`。

### 5. Linux/DGX Spark 部署包自動整理腳本
* **相關腳本**：[create_build_package.ps1](file:///C:/Users/kk091/.gemini/antigravity-ide/brain/ae183432-1a51-4118-a501-4dac82b7a705/scratch/create_build_package.ps1) (位於 scratch 目錄)
* **詳細功能**：
  * 解決了 Unity 編譯輸出至 Linux 時「資源檔案路徑錯位」與「缺失共享動態庫」的問題。
  * 腳本會自動抓取編譯出的 `.x86_64` 主程式、`*_Data` 數據資料夾，並精確複製關鍵的 **`UnityPlayer.so`** 與 **`GameAssembly.so`** 引擎動態庫。
  * 自動把專案根目錄的 `Animations` 與 `Assets/hu36_dataset` 資源包複製到輸出資料夾的正確相對路徑下，並自動打包壓縮成一個 `SMPL-test-build.zip` 部署包。

---

## 二、 Human3.6M 播放器輸入詳解

Human3.6M (H3.6M) 播放器輸入的不是骨骼的「局部旋轉角度（Rotation）」，而是「關節在 3D 空間中的絕對座標位置（Coordinates）」。

以下是 H3.6M 播放器載入的輸入檔案（`Human36M_subject1_joint_3d.json`）之詳細輸入格式與解析過程：

### 1. JSON 輸入層級結構

該 JSON 檔案採用三層嵌套的結構來管理動作捕捉數據：

```json
{
  "Action_ID": {
    "Subaction_ID": {
      "Frame_Index": [
        [x0, y0, z0],
        [x1, y1, z1],
        ...
        [x16, y16, z16]
      ]
    }
  }
}
```

* **Action_ID (第一層，動作代號)**：
  鍵值為字串型別的 `"2"` 至 `"16"`。為了讓 UI 易讀，播放器將這些數字代號映射為 H3.6M 標準的 15 個動作名稱：
  
  | Action ID | 動作名稱 (Action Name) | 說明 |
  | :---: | :--- | :--- |
  | **2** | Directions | 指導/方向說明 |
  | **3** | Discussion | 討論 |
  | **4** | Eating | 吃東西 |
  | **5** | Greeting | 打招呼 |
  | **6** | Phoning | 打電話 |
  | **7** | Posing | 擺姿勢 |
  | **8** | Purchases | 買東西 |
  | **9** | Sitting | 坐著 |
  | **10** | SittingDown | 坐下 |
  | **11** | Smoking | 抽菸 |
  | **12** | Photo | 拍照 |
  | **13** | Waiting | 等待 |
  | **14** | Walking | 行走 |
  | **15** | WalkDog | 牽狗散步 |
  | **16** | WalkTogether | 共同行走 |

* **Subaction_ID (第二層，子動作/試次)**：
  鍵值為 `"1"` 或 `"2"`。在 H3.6M 資料集中，同一個動作每個受試者都會錄製兩次（Trials），例如 `Walking 1` 與 `Walking 2`。

* **Frame_Index (第三層，幀號)**：
  鍵值為字串型別的數字，例如 `"0"`, `"1"`, `"2"`... 直至該動作結束。播放器會讀取這些鍵值並依數字大小重新排序，以保證動畫播放的連續性。

---

### 2. 17 個關節 3D 座標輸入 (Joint Coordinates)

在最底層的每一個 Frame 中，包含一個擁有 **17 個元素的二維陣列**。每個元素都是一個 `[x, y, z]` 三維向量，代表該關節點相對於動捕世界坐標系中心點的位置。

#### 17 個關節點的索引位置定義 (Joint Map)：
* **0**：Pelvis (骨盆/人體中心點)
* **1**：Right Hip (右臀) $\rightarrow$ **2**：Right Knee (右膝) $\rightarrow$ **3**：Right Ankle (右腳踝)
* **4**：Left Hip (左臀) $\rightarrow$ **5**：Left Knee (左膝) $\rightarrow$ **6**：Left Ankle (左腳踝)
* **7**：Spine (下脊椎) $\rightarrow$ **8**：Neck/Thorax (頸部/胸腔) $\rightarrow$ **9**：Head/Nose (頭部中心) $\rightarrow$ **10**：Head Top (頭頂)
* **11**：Left Shoulder (左肩) $\rightarrow$ **12**：Left Elbow (左手肘) $\rightarrow$ **13**：Left Wrist (左手腕)
* **14**：Right Shoulder (右肩) $\rightarrow$ **15**：Right Elbow (右手肘) $\rightarrow$ **16**：Right Wrist (右手腕)

---

### 3. 播放器如何解析並轉換這些輸入？

當 [H36MAnimationPlayer.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/H36M/H36MAnimationPlayer.cs) 讀取這個 JSON 後，會透過以下步驟進行轉換與渲染：

#### A. 單位與坐標空間轉換
* **單位轉換**：H3.6M 的原始數值單位是**毫米 (mm)**（例如 Pelvis 高度為 `907.2`），而 Unity 使用**公尺 (m)**。因此播放器會將每個數值除以 `1000f`。
* **坐標軸對照 (Z-Up 轉 Y-Up)**：
  * H3.6M 坐標系：$X$ 為左右，$Y$ 為前後，$Z$ 為上下 (Height)。
  * Unity 坐標系：$X$ 為左右，$Y$ 為上下 (Height)，$Z$ 為前後。
  * **轉換公式**：`Unity_Pos = new Vector3(H36M_X / 1000f, H36M_Z / 1000f, H36M_Y / 1000f);`
  這可以確保角色直立站好，且身高比例大約在正常的 1.5 到 1.7 公尺之間。

#### B. 骨架連接線渲染 (Skeleton Rendering)
由於 H3.6M 沒有網格模型（Mesh），播放器會在運行時：
1. 產生 17 個球體物件 (Spheres) 置於對應的關節轉換坐標位置。
2. 根據拓撲結構定義（例如 `0 連接 7`, `7 連接 8` 等），建立 16 個 `LineRenderer` 線段。
3. 每一幀更新時，先移動球體位置，再將 `LineRenderer` 的起點與終點位置鎖定在對應球體的中心點，即時畫出一個會運動的 3D 骨架火柴人。
