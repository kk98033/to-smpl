# SMPL 0901 Bridge UDP API

本文件是 <code>to-smpl</code> 對外通訊合約。服務沒有 HTTP/REST API；即時資料皆以 UDP datagram 傳輸。

| 方向 | 預設端點 | 格式 | 用途 |
| --- | --- | --- | --- |
| Pipeline → Bridge | <code>udp://0.0.0.0:9100</code> | UTF-8 JSON | 已三角化的 59 點人體骨架 |
| Bridge → Unity | <code>udp://UNITY_HOST:9095</code> | SMV2 binary | SMPL 姿態、root motion、雙手與品質 |
| Bridge → Unity/Recorder | <code>udp://UNITY_HOST:9096</code> | RSV1 binary | 未經轉換的原始 59 點骨架 |

UDP 不提供連線、ack、重送、順序或送達保證。每個 datagram 必須包含一個完整 frame；接收端應以 <code>frameId</code> 判斷重複、亂序或遺失。SMV2 與 RSV1 都採 little-endian。

## 1. 輸入：Factory 59-point JSON（UDP 9100）

### 傳輸規則

- 編碼：UTF-8。
- 一個 UDP datagram 對應一個 JSON object，不接受一包多幀。
- Bridge 單包接收上限為 1 MiB。
- Bridge 擬合期間若累積多包，會丟棄排隊舊包，只處理最新完整 datagram。
- UDP 沒有回應封包；成功與否從 Bridge log 與輸出 frame 判斷。
- <code>schema</code> 可為新版 <code>dt-pose.pose3d/v1</code> 或舊版 <code>factory_59pt_body_hands</code>；省略時依舊版欄位解析。

### 建議 JSON

~~~json
{
  "schema": "dt-pose.pose3d/v1",
  "source": "rig_b",
  "frame": 1054,
  "timestamp_ns": 1725150000123456789,
  "units": "m",
  "layout": "factory59",
  "joints": [[-0.580, -0.853, -1.332]],
  "single_person": true
}
~~~

範例為了易讀只畫出一點；實際 <code>joints</code> 必須有 59 筆。缺失關節使用 JSON <code>null</code>，不得傳送非標準 <code>NaN</code> token。

### 欄位

| 欄位 | 型態 | 必要 | 說明 |
| --- | --- | --- | --- |
| <code>schema</code> | string | 否 | 新版 <code>dt-pose.pose3d/v1</code>；亦接受舊版 <code>factory_59pt_body_hands</code> 或省略 |
| <code>frame</code> | integer | 新版建議 | v1 frame ID；舊版別名為 <code>frame_index</code>、<code>frame_id</code>、<code>frameId</code> |
| <code>timestamp_ns</code> | integer | 新版建議 | v1 PTP/epoch 奈秒；舊版別名為 <code>ptp_epoch_ns</code> |
| <code>units</code> | string | 新版必要 | <code>m</code> 或 <code>mm</code>；舊版使用 <code>_input_units</code>，皆無時 auto 預設 mm |
| <code>layout</code> | string | v1 必要 | <code>dt-pose.pose3d/v1</code> 固定為 <code>factory59</code> |
| <code>joints</code> | number/null [59][3] | v1 必要 | Factory59 座標；每個缺失 joint 可為 <code>null</code> |
| <code>single_person</code> | boolean | 否 | 三視角是否都只偵測到一人；Bridge 保留相容解析，品質政策仍由部署端決定 |
| <code>frame_index</code> | integer | 建議 | uint32 frame ID；亦接受 <code>frame_id</code>、<code>frameId</code> |
| <code>timestamp_s</code> | number | 否 | Unix epoch 秒；亦接受 <code>timestamp</code>，省略時使用接收時間 |
| <code>ptp_epoch_ns</code> | integer | 否 | Unix epoch 奈秒；省略時由 timestamp 換算，RSV1 exact flag 為 0 |
| <code>_input_units</code> | string | 建議 | <code>mm</code> 或 <code>m</code>；auto 模式省略時預設 mm |
| <code>coordinate_frame</code> | string | 建議 | 座標系名稱；RSV1 UTF-8 編碼後必須少於 64 bytes |
| <code>keypoints_3d</code> | number/null [59][3] | 舊版必要 | Factory59 點；亦接受 [133][3] 並擷取 WholeBody 指定點 |
| <code>points_3d</code> | number/null [59][3] | 替代 | <code>keypoints_3d</code> 的別名 |
| <code>keypoint_3d</code> | object | 替代 | 以 WholeBody ID 為 key：0..16、91..132 |
| <code>reliable</code> | bool/number [59] 或 object | 否 | 陣列為 Factory59 順序；object 以 WholeBody ID 為 key；轉成 [0,1] confidence |
| <code>reprojection_errors_px</code> | number [59] | 否 | reliable 省略時，有限且 ≤120 px 視為可靠 |

缺失或非有限座標會把該點 confidence 設為 0。auto 模式依 payload 宣告單位；舊格式未宣告時才執行預設 mm → m 與 <code>x,-y,-z</code> proper-rotation 軸映射；RSV1 保留映射前的原始數值和單位。

### 59 點順序

- 0..16：COCO Body17。
- 17..37：Left Hand21，index 17 是 wrist。
- 38..58：Right Hand21，index 38 是 wrist。

Body17 順序為 nose、left/right eye、left/right ear、left/right shoulder、left/right elbow、left/right wrist、left/right hip、left/right knee、left/right ankle。Hand21 順序為 wrist，接著 thumb/index/middle/ring/pinky，每指由掌側到指尖各 4 點。

## 2. 輸出：SMV2（UDP 9095）

固定 **1389 bytes**，little-endian；Python struct format：

~~~text
<4sI3f156f3f3f4ff63f21f63f21fB4fiiI
~~~

| Offset | Bytes | 型態 | 欄位 |
| ---: | ---: | --- | --- |
| 0 | 4 | char[4] | Magic：<code>SMV2</code> |
| 4 | 4 | uint32 | frameId |
| 8 | 12 | float32[3] | legacy translation |
| 20 | 624 | float32[156] | 52×3 axis-angle pose slots |
| 644 | 12 | float32[3] | root position，相對第一個有效 pelvis，單位 m |
| 656 | 12 | float32[3] | pelvis world，經單位與軸映射，單位 m |
| 668 | 16 | float32[4] | root quaternion (x,y,z,w) |
| 684 | 4 | float32 | root confidence |
| 688 | 252 | float32[63] | left Hand21 wrist-local xyz |
| 940 | 84 | float32[21] | left confidence |
| 1024 | 252 | float32[63] | right Hand21 wrist-local xyz |
| 1276 | 84 | float32[21] | right confidence |
| 1360 | 1 | uint8 | input valid |
| 1361 | 16 | float32[4] | input score、mean residual mm、worst residual mm、torso deg |
| 1377 | 4 | int32 | solver state |
| 1381 | 4 | int32 | fitting steps used |
| 1385 | 4 | uint32 | reason bit mask |

目前 SMPL body rotation 寫入 pose 前 66 floats，其餘 pose slots 保留為 0。neck、head 與左右 wrist local rotation 由 Bridge 固定為自然零旋轉；手指則由左右原始 Hand21 wrist-local 資料獨立驅動。

### Solver state

| Code | 名稱 |
| ---: | --- |
| 0 | TRACKING |
| 1 | RECOVERED |
| 2 | ADAPTIVE_100 |
| 3 | KAMA_REINITIALIZE |
| 4 | HOLD_INPUT_INVALID |
| 5 | TRACKING_LOST |
| 6 | FAILED_HOLD |

### Reason mask

| Bit / Hex | 原因 |
| --- | --- |
| 0 / 0x001 | non_finite |
| 1 / 0x002 | coordinate_range |
| 2 / 0x004 | torso_length |
| 3 / 0x008 | left_right_asymmetry |
| 4 / 0x010 | bone_length_outlier |
| 5 / 0x020 | joint_speed |
| 6 / 0x040 | joint_residual |
| 7 / 0x080 | max_joint_residual |
| 8 / 0x100 | torso_orientation |

## 3. 輸出：RSV1（UDP 9096）

固定 **1032 bytes**，little-endian；Python struct format：

~~~text
<4sHHIQB3x64s177f59f
~~~

| Offset | Bytes | 型態 | 欄位 |
| ---: | ---: | --- | --- |
| 0 | 4 | char[4] | Magic：RSV1 |
| 4 | 2 | uint16 | version，目前為 1 |
| 6 | 2 | uint16 | flags；bit 0 表示來源有精確 PTP |
| 8 | 4 | uint32 | frameId |
| 12 | 8 | uint64 | ptpEpochNs |
| 20 | 1 | uint8 | unit：0 unknown、1 m、2 mm |
| 21 | 3 | padding | 保留 |
| 24 | 64 | char[64] | UTF-8 coordinate frame，NUL padded |
| 88 | 708 | float32[59][3] | 原始 xyz，允許 NaN |
| 796 | 236 | float32[59] | confidence [0,1] |

RSV1 在 JSON 解析後、SMPL 品質閘門前發送。因此某 frame 即使沒有對應 SMV2，仍可能有 RSV1。

## 4. Decoder 與接收要求

安裝此 package 後可直接使用正式 Python decoder：

~~~python
from smpl_0901.protocol_v2_udp import unpack_protocol_v2_frame
from smpl_0901.raw_skeleton_udp import unpack_raw_skeleton_frame

if packet[:4] == b"SMV2":
    frame = unpack_protocol_v2_frame(packet)
elif packet[:4] == b"RSV1":
    frame = unpack_raw_skeleton_frame(packet)
~~~

接收 socket 應分別 bind <code>0.0.0.0:9095</code> 與 <code>0.0.0.0:9096</code>，並先檢查 datagram 長度與 magic。Unity/C# 請以 little-endian 逐欄讀取，不要依賴 C# struct 的預設 alignment。

## 4.1 Bridge 擬合診斷 JSONL（檔案介面）

`--fit-jsonl PATH` 是供 Dashboard／分析工具使用的本機 append-only JSONL，不是另一個 UDP port。每筆 `smpl-0901.fit/v1` 都來自同一個輸入 frame：

~~~json
{
  "schema": "smpl-0901.fit/v1",
  "frame": 1054,
  "timestamp_ns": 1725150000123456789,
  "units": "m",
  "coordinate_frame": "smpl_axes_pelvis_relative",
  "axis_map": "x,-y,-z",
  "fit_profile": "upper-body",
  "solver": {"endpoint_weight": 0.5, "torso_weight": 0.05, "temporal_weight": 0.01, "robust_huber": false},
  "selected_body25_joints": [0,1,2,3,4,5,6,7,8,9,12],
  "target_factory59": [[0.0,0.0,0.0]],
  "target_body25": [[0.0,0.0,0.0]],
  "fitted_body25": [[0.0,0.0,0.0]],
  "fitted_smpl24": [[0.0,0.0,0.0]],
  "joint_residual_mm": [12.3],
  "fit_residual_mm": 31.2,
  "worst_joint_residual_mm": 66.4,
  "torso_orientation_deg": 2.1,
  "worst_target_joint": {"index": 3, "joint": "right_elbow", "mm": 91.4},
  "pose_diagnostics": {
    "joint_names": ["pelvis", "left_hip"],
    "rotation_deg": [12.0, 48.0],
    "twist_deg": [null, 31.0],
    "delta_deg": [2.0, 8.0],
    "worst_twist": {"index": 17, "joint": "right_shoulder", "deg": 82.0},
    "worst_delta": {"index": 19, "joint": "right_elbow", "deg": 51.0},
    "warning_joints": [{"index": 17, "joint": "right_shoulder", "reasons": ["twist"]}],
    "thresholds_deg": {"rotation": 120.0, "twist": 75.0, "delta": 45.0}
  },
  "fixed_betas": [0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0]
}
~~~

實際陣列長度分別是 `59/25/25/24/25/10`。`joint_residual_mm` 中未參與目前 profile 的 Body25 關節為 JSON `null`。Dashboard 的橘色骨架來自 SMPL mesh 經同一 Body25 regressor 得到的 `fitted_body25`，並只顯示目前 profile 實際選取的關節；MPJPE 直接使用 `fit_residual_mm`，不會在瀏覽器內重新擬造骨架。

`pose_diagnostics` 的 `rotation_deg`、`twist_deg`、`delta_deg` 與 `joint_names` 實際皆為 SMPL24 長度 24。`twist_deg` 是關節相對主要子骨方向的 swing-twist 分解；沒有主要子骨的末端關節為 `null`。Dashboard 以 rotation 120°、twist 75°、單幀 geodesic delta 45° 為預設警示門檻。這些指標用來找「關節點接近但表面沿骨軸扭轉」的欠約束解，不等同 MPJPE。

## 4.2 SMPL mesh 除錯快照（檔案介面）

`--mesh-preview-json PATH` 以 atomic replace 維護最新擬合候選 frame，不是 UDP，也不是 append-only log。`accepted` 表示此候選是否通過安全門檻；所有候選均會以 SMV2 送往 Unity，未通過者以 `inputValid=false`、`FAILED_HOLD` 與 reason bit mask 標記。`faces` 使用 compact vertex indices；`source_vertex_count` 保留完整 SMPL surface 頂點數，`vertices` 只包含被抽樣 faces 引用的點。

~~~json
{
  "schema": "smpl-0901.mesh-preview/v1",
  "frame": 1054,
  "timestamp_ns": 1725150000123456789,
  "units": "m",
  "coordinate_frame": "smpl_axes_pelvis_relative",
  "fit_profile": "upper-body",
  "source_vertex_count": 6890,
  "vertices": [[0.012, -0.431, 0.083]],
  "faces": [[0, 1, 2]],
  "face_joint": [16]
}
~~~

Dashboard 透過受 token 保護的 `GET /api/smpl-mesh` 按需取得此快照。預設以 vertex clustering 簡化至最多 2400 triangles，目的是確認 server-side SMPL surface 與 fitted joints 是否同幀、同座標；它不是 Unity 最終材質或 skinning 畫面。

Bridge 會依 `--diagnostic-log-every` 定期在 stdout 輸出單行 `[bridge] distortion {JSON}`，schema 為 `smpl-0901.distortion-log/v1`。內容包含 `accepted`、`action`、`reasons`、`fit_residual_mm`、`fit_elapsed_ms`、`fit_iterations`、`torso_orientation_deg`、`worst_target_joint`、`worst_rotation`、`worst_twist`、`worst_delta` 與 `warning_joints`。`accepted:false` 表示候選姿勢被安全門檻攔截，不更新 Bridge 的已接受 fitting 狀態；SMV2 仍會送出，但 `inputValid=false`、`solverState=FAILED_HOLD`，reason mask 會包含 `twist`、`delta`、`facing_mismatch` 或 `fit_residual`。新版 Unity 預設將它當 Dashboard 候選顯示；關閉 `Show Held Fit` 後才會保留上一個正常姿勢。`body_facing_mismatch_deg` 是輸入上半身前向與 SMPL 雙腳掌水平前向的夾角，超過 90°代表上下半身前後相反。pelvis 的絕對旋轉代表人物朝向，不列入 rotation distortion；pelvis 的單幀 delta 仍會檢查。

## 5. CLI contract

| 參數 | 預設 | 說明 |
| --- | --- | --- |
| <code>--input</code> | unix:///tmp/dt_pose_3d.sock | 支援 udp、unix、json、jsonl、npz、stdin URI |
| <code>--input-units</code> | auto | auto、m、mm |
| <code>--axis-map</code> | x,-y,-z | proper right-handed camera-to-SMPL rotation; reflection maps such as x,-y,z cause anatomical twisting |
| <code>--unity-host</code> | 127.0.0.1 | SMV2 目的 IPv4/hostname |
| <code>--unity-port</code> | 9095 | SMV2 目的 UDP port |
| <code>--raw-skeleton-host</code> | Unity host | RSV1 目的 IPv4/hostname |
| <code>--raw-skeleton-port</code> | 9096 | 設為 0 可停用 RSV1 |
| <code>--smpl-dir</code> | package models | 模型根目錄 |
| <code>--device</code> | cuda | PyTorch device |
| <code>--calibration-frames</code> | 30 | fixed-beta 起始校正幀數 |
| <code>--calibration-iterations</code> | 100 | 體型校正迭代數 |
| <code>--iterations</code> | 100 | 每幀擬合迭代數；Docker Compose 為即時用途預設 `SMPL_ITERATIONS=50` |
| <code>--fit-profile</code> | full | `full` 使用 Body25 0..14；`upper-body` 使用 0..9,12，排除膝與腳踝並凍結腿部 rotation；Compose 預設 upper-body |
| <code>--beta-limit</code> | 3.0 | 校正 betas 的絕對值上限；0 停用 |
| <code>--fit-jsonl</code> | disabled | 寫出同幀實際 fitted joints 與 residual |
| <code>--mesh-preview-json</code> | disabled | atomic latest-only connected SMPL surface JSON |
| <code>--mesh-preview-faces</code> | 2400 | 連續 mesh preview 的三角面上限 |
| <code>--endpoint-weight</code> | 0.5 | 端點 loss 權重 |
| <code>--torso-weight</code> | 0.05 | torso normal loss 權重 |
| <code>--body-facing-weight</code> | 0.01 | torso 與腳掌水平前向一致性 loss 權重 |
| <code>--temporal-weight</code> | 0.01 | temporal smoothing 權重 |
| <code>--max-fit-residual-mm</code> | 100 | MPJPE 超標時保留上一個正常姿勢；0 停用 |
| <code>--max-twist-deg</code> | 100 | 任一軸向 twist 超標時保留上一姿勢；0 停用 |
| <code>--max-delta-deg</code> | 90 | 任一關節單幀旋轉跳動超標時保留上一姿勢；0 停用 |
| <code>--max-facing-mismatch-deg</code> | 90 | torso 與腳掌水平朝向差超標時保留上一姿勢；0 停用 |
| <code>--diagnostic-log-every</code> | 10 | 每 N 個成功 fit 輸出一筆 structured distortion log；被攔截幀一律記錄；0 停用正常幀定期紀錄 |
| <code>--robust-huber</code> | off | 啟用 Huber loss |
| <code>--min-confidence</code> | 0.5 | 目前 fit profile 所選 Body25 點的最低 confidence |

完整 CLI 說明可執行 <code>smpl-0901-bridge --help</code>。模型目錄必須包含 <code>smpl/SMPL_NEUTRAL.pkl</code> 與 <code>J_regressor_body25.npy</code>。<code>smpl-0901-send PATH --destination udp://HOST:9100 --fps 30</code> 可用 JSON/JSONL 做輸入重播測試。
