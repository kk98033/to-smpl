# 0901 Multi-Dataset High-Precision Reconstruction Summary

**Test Date**: 2026-09-01  
**Hardware**: NVIDIA GeForce RTX 3090 (24GB VRAM, CUDA Enabled)  
**Output Directory**: `d:\School\Projects\main\0901meeting\new_outputs\`  

---

## 📊 跨資料集評測指標匯總

| 資料集 (Dataset) | 動作特徵與內容 | 評測影格數 | Body15 MPJPE ↓ | 軀幹朝向誤差 ↓ | 姿態狀態 | 成果影片 / 截圖 / JSON 格式 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Human3.6M (`h36m_300`)** | 經典 Mocap 動作 (Subject 1 Action 2) | 300 幀 | **25.30 mm** | **4.87°** | ✅ 完美挺直，無扭曲 | [MP4 影片](file:///d:/School/Projects/main/0901meeting/new_outputs/h36m_300/h36m_300_comparison.mp4)<br>[預覽圖](file:///d:/School/Projects/main/0901meeting/new_outputs/h36m_300/h36m_300_preview.png)<br>[JSON 串流檔](file:///d:/School/Projects/main/0901meeting/new_outputs/h36m_300/h36m_300.json) |
| **AMASS Sample (`amass_sample_300`)** | 全身坐姿、屈膝、手臂延伸連續動作 | 300 幀 | **39.78 mm** | **4.12°** | ✅ **修正駝背/龜頸問題** | [MP4 影片](file:///d:/School/Projects/main/0901meeting/new_outputs/amass_sample_300/amass_sample_300_comparison.mp4)<br>[預覽圖](file:///d:/School/Projects/main/0901meeting/new_outputs/amass_sample_300/amass_sample_300_preview.png)<br>[JSON 串流檔](file:///d:/School/Projects/main/0901meeting/new_outputs/amass_sample_300/amass_sample_300.json) |
| **AMASS Punching (`amass_punching`)** | 快速出拳、防守護頭格擋動作 | 234 幀 | **34.95 mm** | **3.71°** | ✅ 手腕/頭部精確對齊 | [MP4 影片](file:///d:/School/Projects/main/0901meeting/new_outputs/amass_punching/amass_punching_comparison.mp4)<br>[預覽圖](file:///d:/School/Projects/main/0901meeting/new_outputs/amass_punching/amass_punching_preview.png)<br>[JSON 串流檔](file:///d:/School/Projects/main/0901meeting/new_outputs/amass_punching/amass_punching.json) |
| **H3WB Mini (`h3wb_300`)** | 全身包含雙手 21 關節之 Ground Truth | 300 幀 | **20.35 mm** | **5.71°** | ✅ 全身與手勢貼合 | [MP4 影片](file:///d:/School/Projects/main/0901meeting/new_outputs/h3wb_300/h3wb_300_comparison.mp4)<br>[預覽圖](file:///d:/School/Projects/main/0901meeting/new_outputs/h3wb_300/h3wb_300_preview.png)<br>[JSON 串流檔](file:///d:/School/Projects/main/0901meeting/new_outputs/h3wb_300/h3wb_300.json) |

---

## 🖼️ 四大資料集正面預覽截圖

### 1. Human3.6M (`h36m_300`)
![H36M 預覽](file:///d:/School/Projects/main/0901meeting/new_outputs/h36m_300/h36m_300_preview.png)
*(左邊藍色：GT 關節點；中間橘色：SMPL 反解骨架；右邊：1:1 完美重合)*

### 2. AMASS Sample 坐姿延伸 (`amass_sample_300`)
![AMASS Sample 預覽](file:///d:/School/Projects/main/0901meeting/new_outputs/amass_sample_300/amass_sample_300_preview.png)
*(脊椎挺直，徹底消除 Frame 78 處的駝背與頸部過度前傾異常)*

### 3. AMASS Punching 拳擊動作 (`amass_punching`)
![AMASS Punching 預覽](file:///d:/School/Projects/main/0901meeting/new_outputs/amass_punching/amass_punching_preview.png)
*(雙手護頭防守姿態，手臂與頭部方位完全正確)*

### 4. H3WB Whole-Body (`h3wb_300`)
![H3WB 預覽](file:///d:/School/Projects/main/0901meeting/new_outputs/h3wb_300/h3wb_300_preview.png)
*(軀幹與手臂手勢精確擬合)*
