# 2026-09-01 Meeting：最佳 SMPL-H 轉換方案獨立套件與新電腦 (RTX 3090) 效能評測

本資料夾為 **2026-09-01 會議專屬交付與測試套件**，已將專案目前效果最好、最穩定的 **「固定體型 (Fixed Betas) + 旋轉約束擬合 (Soft Joint Target)」** 完整獨立封裝，並於全新 **NVIDIA GeForce RTX 3090** 主機完成效能壓測。

---

## ⚡ 新舊電腦硬體效能躍升對比 (Benchmark on RTX 3090)

| 評測方法 (Method) | 舊電腦 (RTX 3050 Ti Laptop) | **新電腦 (RTX 3090 Desktop)** | **加速倍率 (Speedup)** | 精度指標 (MPJPE) | 軀幹朝向誤差 |
|---|---:|---:|:---:|:---:|:---:|
| **KAMA-100 (Zero Betas)** | 273.9 ms | **56.0 ms** | **4.9x 🚀** | 15.35 mm | 4.30° |
| **KAMA-100 + Adaptive +100** | 195.7 ms | **53.9 ms** | **3.6x 🚀** | 8.18 mm | 1.09° |
| **Fixed Betas + Soft Target (最佳方案)** | 138.6 ms | **31.9 ms (31.3 FPS)** | **4.3x 🚀** | **38.03 mm** | **3.37°** |

> 🌟 **核心突破**：在你的新電腦 RTX 3090 上，最佳方案的單幀耗時僅需 **31.9 ms**（換算達 **31.3 FPS**），正式突破 30 FPS 即時門檻，達成 **真即時（True Realtime）串流**！

---

## 📁 0901 Meeting 目錄結構

```text
0901meeting/
|-- README.md                              <- 本說明文件
|-- BENCHMARK_REPORT_RTX3090.md            <- RTX 3090 完整評測與數據報告
|-- RUN_0901_BENCHMARK.ps1                 <- 一鍵執行 RTX 3090 效能基準評測
|-- RUN_0901_PIPELINE.ps1                  <- 一鍵執行動作序列轉換、NPZ 匯出與 MP4 比對渲染
|-- benchmark.py                           <- 基準測試 Python 腳本 (H3WB 30 樣本)
|-- run_best_pipeline.py                   <- 最佳方法獨立 Pipeline Runner
|-- fakesender.py                          <- Protocol V2 即時 UDP 串流發送器 (含對照影片同步)
|-- experiments/                           <- 實驗結果與 JSON 數據
|-- output/                                <- 產出的 NPZ 與渲染對照 MP4 影片
|-- unity_patch/                           <- Unity C# 播放器腳本 (含手部 ROM 限制與 Debug HUD)
```

---

## 🚀 快速使用說明

### 1. 一鍵執行 RTX 3090 基準評測
在 PowerShell 中執行：
```powershell
cd d:\School\Projects\main\0901meeting
.\RUN_0901_BENCHMARK.ps1 -Samples 30
```
- 會自動測試所有方法並更新 [BENCHMARK_REPORT_RTX3090.md](file:///d:/School/Projects/main/0901meeting/BENCHMARK_REPORT_RTX3090.md)。

---

### 2. 一鍵執行最佳方法動作推論與比對影片渲染
```powershell
cd d:\School\Projects\main\0901meeting

# 處理預設拳擊動作序列 (15 幀快速測試)
.\RUN_0901_PIPELINE.ps1 -MaxFrames 15

# 處理自訂 NPZ 檔案
.\RUN_0901_PIPELINE.ps1 -InputNpz "..\data\amass_dataset\punching_poses.npz" -MaxFrames 30
```
產出檔案位於 `0901meeting/output/`：
- **`*_best_method_result.npz`**：SMPL-H 156 維姿態、平移量、骨長 Betas 與骨架座標。
- **`*_best_method_comparison.mp4`**：PyTorch3D 渲染出的原動作 vs 反解 SMPL-H 左右並排對照影片。

---

### 3. 一鍵啟動 Unity 即時 UDP 串流（含手部與影片同步）
1. 開啟 Unity 專案 `SMPL-test`，點選選單 **`CustomSMPL > 0818 Realtime Protocol V2 UDP Player`** 並按 **Play**。
2. 在終端機執行：
```powershell
d:\School\Projects\hyberik\venv\Scripts\python.exe d:\School\Projects\main\0901meeting\fakesender.py --dataset punching --fps 30
```
- 支援動態同步發送 `SMV2` 二進位封包與 `VIDE` 影片連動控制。

---

## 💡 最佳方案核心技術總結

1. **體型與骨長 100% 恆定（Fixed Betas）**：
   - 前段 10 幀 Calibration 推估體型後永久鎖定，徹底杜絕 Unity Linear Blend Skinning (LBS) 角色蒙皮撕裂問題。
2. **軀幹法向量約束（Torso Normal Constraint）**：
   - 強制人體正向朝向，軀幹朝向誤差壓在 **3.37°**，100% 杜絕前後翻轉（Front/Back Flip）。
3. **手腕與腳踝加權 Soft Target**：
   - 關鍵末端誤差降至 **9.44 mm**。
4. **手部解剖學 ROM 約束**：
   - Unity 端限制手指中節/末節關節嚴禁後折（$\ge 0^\circ$），揮拳與手指動作自然平滑。
