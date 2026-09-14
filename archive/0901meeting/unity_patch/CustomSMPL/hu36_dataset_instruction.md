# Human3.6M (H36M) 3D Joint 播放器使用說明與架構文件
# Human3.6M (H36M) 3D Joint Player Documentation & Architecture

本文件說明如何在 Unity 中載入並播放 Human3.6M (H36M) 3D 關節座標動畫，並詳細記錄資料格式、骨架對應關係、坐標系轉換以及播放器設計架構。

---

## 1. 資料格式與結構 (Data Format)

H36M 關節座標檔案 `Human36M_subject1_joint_3d.json` (大小約 64MB) 的 JSON 結構如下：

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

* **Action_ID (動作代號)**：鍵值為 `"2"` 至 `"16"`，分別對應 H36M 的 15 種動作類別（如 Directions, Eating, Walking 等）。
* **Subaction_ID (子動作/試次)**：鍵值為 `"1"` 或 `"2"`，代表該動作的兩組獨立錄製數據。
* **Frame_Index (幀號)**：字串型別的整數（如 `"0"`, `"1"`...），播放器在解析時會依數值排序以確保正確的播放順序。
* **關節數據**：每一幀包含 17 個 3D 座標，單位為毫米 (mm)。

---

## 2. 骨架定義與索引對照 (Skeleton Topology)

H36M 採用 17 個主要關節構成人體骨架，其索引對照及拓撲連接關係如下：

### 關節索引對照表 (Joint Index Map)

| 索引 (Index) | 關節名稱 (Joint Name) | 解剖位置與側向 (Anatomical Position) |
| :---: | :--- | :--- |
| **0** | Pelvis | 骨盆 (中心臀部) |
| **1** | Right Hip | 右臀部 (右大腿根部) |
| **2** | Right Knee | 右膝蓋 |
| **3** | Right Ankle | 右腳踝 |
| **4** | Left Hip | 左臀部 (左大腿根部) |
| **5** | Left Knee | 左膝蓋 |
| **6** | Left Ankle | 左腳踝 |
| **7** | Torso / Spine | 軀幹 / 脊椎下部 |
| **8** | Neck / Thorax | 頸部 / 胸腔 |
| **9** | Head / Nose | 頭部中心 / 鼻部 |
| **10** | Head Top | 頭頂 |
| **11** | Left Shoulder | 左肩膀 |
| **12** | Left Elbow | 左手肘 |
| **13** | Left Wrist | 左手腕 |
| **14** | Right Shoulder | 右肩膀 |
| **15** | Right Elbow | 右手肘 |
| **16** | Right Wrist | 右手腕 |

### 骨骼連接關係 (Bone Connections)

播放器會根據以下 16 條骨骼連線，動態更新 `LineRenderer` 來繪製 3D 骨架線條：

* **軀幹與頭部**：`0-7` (Pelvis-Spine), `7-8` (Spine-Neck), `8-9` (Neck-Head), `9-10` (Head-HeadTop)
* **左腿**：`0-4` (Pelvis-L_Hip), `4-5` (L_Hip-L_Knee), `5-6` (L_Knee-L_Ankle)
* **右腿**：`0-1` (Pelvis-R_Hip), `1-2` (R_Hip-R_Knee), `2-3` (R_Knee-R_Ankle)
* **左臂**：`8-11` (Neck-L_Shoulder), `11-12` (L_Shoulder-L_Elbow), `12-13` (L_Elbow-L_Wrist)
* **右臂**：`8-14` (Neck-R_Shoulder), `14-15` (R_Shoulder-R_Elbow), `15-16` (R_Shoulder-R_Wrist)

---

## 3. 座標轉換公式 (Coordinate Transformation)

H36M 原始數據為**右手法則且 Z 軸朝上 (Z-up)** 的相機/世界坐標系，單位為毫米 (mm)；而 Unity 使用**左手法則且 Y 軸朝上 (Y-up)**，單位為公尺 (m)。

轉換公式如下：
* **Unity_X** = $H36M\_X / 1000$
* **Unity_Y** = $H36M\_Z / 1000$
* **Unity_Z** = $H36M\_Y / 1000$

經過此轉換後，角色在 Unity 場景中會以正確的站立朝向（Y 軸向上）及真實的人體身高比例（約 1.5 ~ 1.7 公尺高）呈現。

---

## 4. 播放器架構設計 (Architecture Design)

H36M 播放系統由三個核心組件組成：

1. **[H36MAnimationPlayer.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/H36M/H36MAnimationPlayer.cs)**:
   * **異步載入**：因 JSON 檔案達 64MB，在 `Start` 或手動載入時會開啟 background thread (`Task.Run`) 解析 JSON，避免 Unity 主執行緒凍結 (Freeze)。
   * **動態生成**：載入完成後，自動在場景中生成 17 個球體代表關節，並生成 16 個 `LineRenderer` 代表骨骼線段。
   * **播放計時**：在 `Update` 中依據 `Time.deltaTime * playbackSpeed` 計算當前時間與對應幀數。

2. **[H36M_UIBuilder.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/H36M/UI/H36M_UIBuilder.cs)**:
   * 採用純程式碼動態生成 UI 畫布 (Canvas) 和左側面板。
   * 提供 Actions 動作列表（將代號對照轉換為易讀的英文名稱，如 Discussion, Smoking 等）。
   * 包含子動作切換按鈕、播放/暫停/停止、播放速度 Slider、播放進度尋軌 (Scrubbing Slider)。

3. **[H36M_UIManager.cs](file:///f:/School/資策會/Unity/SMPL-test/Assets/CustomSMPL/H36M/UI/H36M_UIManager.cs)**:
   * 綁定 UI 事件與 Player API。
   * 更新每一幀的播放進度條數值，並防止回授事件迴圈 (Event Loop Loopback)。
   * 支援快捷鍵 `H` 隱藏/顯示 UI 面板。

---

## 5. 快速開始與使用步驟 (Quick Start)

### 步驟 A：自動化場景配置
1. 在 Unity 編輯器頂部選單點擊：`CustomSMPL -> Setup H36M Player Scene`。
2. 編輯器會自動在當前場景中建立兩個 GameObject：
   * `H36M_Player`：掛載 `H36MAnimationPlayer` 腳本，已自動配置資料庫路徑。
   * `H36M_UI`：掛載 `H36M_UIManager` 腳本。

### 步驟 B：運行與操作
1. 按下 Unity 編輯器的 **Play** 按鈕。
2. 畫面左側會出現 `H36M Animation Player` 介面，並開始自動加載 64MB 數據檔。
3. 加載完成後，點擊動作列表中的任何項目（例如 `Walking`），點選 `Subaction 1` 或 `Subaction 2`。
4. 綠色與藍色構成的 3D 關節火柴人將會出現在場景中並播放動畫。
5. 拖曳 **Speed** 調整播放速度，拖曳 **Progress (Frame)** 進度條可即時 seeks / scrubbing 動作姿態（即使在暫停狀態下亦可即時尋軌）。
6. 按下鍵盤 `H` 鍵可隨時隱藏/顯示操作面板。
