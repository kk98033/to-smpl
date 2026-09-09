# SMPL 0901 Unity Player

這是專門接收 `smpl-0901-bridge` 之 `SMV2` UDP 封包的新播放器。它使用獨立 namespace `SMPL0901Player`，可和原本的 `CustomSMPL` 播放器同時存在，不會覆寫或修改舊版。

## 安裝

1. Unity 專案必須先有 BioMotionLab SUP package 及其 SMPL-H character prefab。
2. 只把本資料夾 `SMPL0901Player` 複製到 Unity 專案的 `Assets/SMPL0901Player`。
3. 等待 Unity 編譯完成。
4. 上方選單執行 **SMPL 0901 → Create Live Player in Scene**。
5. 進入 Play Mode；預設監聽 SMV2 UDP `9095` 與 RSV1 UDP `9096`。

如果 Scene 裡仍有舊版 UDP player，請將舊物件停用；同一台電腦上不能讓兩個播放器同時綁定 UDP 9095。舊腳本與 prefab 不需要刪除。

選單會建立並連接以下元件，不需要手動拖腳本：

- `Smpl0901LivePlayer`：只接收 1389-byte SMV2，latest-frame-wins。
- `Smpl0901RootMotionDriver`：套用相對 pelvis 位移與平滑。
- `Smpl0901RawHandRetargeter`：用 wrist-local Hand21 驅動手指。
- `Smpl0901TrackingPanel`：顯示封包 FPS、frame、residual、torso angle，並提供 Reconnect 與 Reset Root Anchor。
- `Smpl0901FittedSkeletonRenderer`：顯示 SMPL 反推後的 body skeleton。
- `Rsv1RawSkeletonRenderer`：接收並顯示原始 Body17 + Left Hand21 + Right Hand21。

Runtime UI 可分別切換：

- `SMPL Mesh`：SMPL-H mesh。
- `SMPL Fitted Skeleton`：0901 fitting 後的 SMPL body 骨架。
- `Raw 59pt Skeleton`：RSV1 原始推論骨架。

也可以輸入 `Server IP`、SMV2 port 與 RSV1 port，再按 `Reconnect Both`。Server IP 預設為 `192.168.1.250`；按 `Accept Any IP` 可暫時取消來源過濾。

Debug 區會顯示 Unity 本機 IPv4、兩個 bind endpoint、最後觀察到與最後接受的 sender IP、accepted／ignored／decode-error 計數及封包 age。沒有收到資料時，會直接提示是目的 IP、Windows Firewall、來源過濾或 binary size 哪一類問題。

## 與舊版的差異

- 不接收舊 `SMPL`／`SMPJ` 封包。
- 沒有影片播放器、離線 cache 或 playback 分支。
- 身體只套 SMPL pose index `0..21`；finger pose slots 不會覆蓋 Hand21。
- 手部沿用 `main/0818meeting` 的 hybrid `RawHandRetargeter`：wrist-local Hand21、ROM 關節限制、自適應平滑與低信心回 rest pose。
- Bridge 將 neck、head 與左右 wrist 固定為自然 local rotation：頭頸跟隨胸口朝前，手掌根節點跟隨前臂。手指的彎曲與張開仍直接來自原始 59 點中的左右 Hand21，並以 bind-relative delta 套到 SUP finger bones。
- Unity 主執行緒只套用接收執行緒留下的最新 frame，避免延遲持續累積。
- Bridge 也會送出 Dashboard 所顯示的安全門檻失敗候選姿勢，封包以
  `quality.inputValid=false`、`solverState=FAILED_HOLD` 及 `reasons` 清楚標記。
- Runtime UI 的 `Show Held Fit` 預設開啟：Unity 會套用這個候選姿勢，因此
  Unity mesh 與 Dashboard 的 SMPL mesh 使用同一份擬合結果。關閉後即為正式
  嚴格模式，遇到 `inputValid=false` 時保持上一個通過安全門檻的姿勢。
- 新版 SUP prefab 的 SMPL axis-angle 會以每根骨頭原始 bind rotation 為基準套用。這能確保零旋轉仍等於 prefab T-pose，避免收到第一幀後因清除 authored local bone basis 而扭曲。`applyPoseRelativeToBind` 預設開啟；只有舊式 identity-local-rotation rig 才應關閉。

## 座標校正

預設 root motion 使用 `invertSourceX=true`、`applyVertical=false`，沿用舊播放器的 Python/Unity 左右手座標轉換。若人物左右移動相反，取消 `invertSourceX`；若需要樓梯或垂直位移，再啟用 `applyVertical`。第一次部署請用「向前走、向右走、舉右手」確認座標與左右手。

## 不同主機

UDP 的目的地由傳送端決定。Unity UI 的 Server IP 是來源過濾條件，不會反向設定 server；Unity 與 bridge 在不同機器時，server 必須使用 Unity 主機 IP：

```bash
smpl-0901-bridge --unity-host <UNITY電腦IP> --unity-port 9095 ...
```

RSV1 sender 同樣要把 `<UNITY電腦IP>:9096` 當目的地。資料流為：

```text
Pipeline → UDP 9100 JSON → smpl-0901-bridge
                              ├─ UDP 9095 SMV2 fitted pose
                              └─ UDP 9096 RSV1 raw factory-59 skeleton
```

RSV1 decoder 嚴格接受 magic `RSV1`、protocol version `1` 與固定 1032 bytes；座標依 unit byte 自動將 m/mm 轉成 Unity meters，NaN 或 confidence 低於門檻的點不渲染。

Windows Firewall 必須允許 Unity Editor 或 build 接收 UDP 9095。
