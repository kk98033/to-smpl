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

缺失或非有限座標會把該點 confidence 設為 0。auto 模式依 payload 宣告單位；舊格式未宣告時才執行預設 mm → m 與 <code>x,-y,z</code> 軸映射；RSV1 保留映射前的原始數值和單位。

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

目前 SMPL body rotation 寫入 pose 前 66 floats，其餘 pose slots 保留為 0；手指由左右 Hand21 wrist-local 資料獨立驅動。

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

## 5. CLI contract

| 參數 | 預設 | 說明 |
| --- | --- | --- |
| <code>--input</code> | unix:///tmp/dt_pose_3d.sock | 支援 udp、unix、json、jsonl、npz、stdin URI |
| <code>--input-units</code> | auto | auto、m、mm |
| <code>--axis-map</code> | x,-y,z | signed xyz permutation |
| <code>--unity-host</code> | 127.0.0.1 | SMV2 目的 IPv4/hostname |
| <code>--unity-port</code> | 9095 | SMV2 目的 UDP port |
| <code>--raw-skeleton-host</code> | Unity host | RSV1 目的 IPv4/hostname |
| <code>--raw-skeleton-port</code> | 9096 | 設為 0 可停用 RSV1 |
| <code>--smpl-dir</code> | package models | 模型根目錄 |
| <code>--device</code> | cuda | PyTorch device |
| <code>--calibration-frames</code> | 10 | fixed-beta 起始校正幀數 |
| <code>--calibration-iterations</code> | 100 | 體型校正迭代數 |
| <code>--iterations</code> | 100 | 每幀擬合迭代數 |
| <code>--endpoint-weight</code> | 2.5 | 端點 loss 權重 |
| <code>--torso-weight</code> | 1.5 | torso normal loss 權重 |
| <code>--temporal-weight</code> | 0.01 | temporal smoothing 權重 |
| <code>--robust-huber</code> | off | 啟用 Huber loss |
| <code>--min-confidence</code> | 0.5 | 必要 Body17 點最低 confidence |

完整 CLI 說明可執行 <code>smpl-0901-bridge --help</code>。模型目錄必須包含 <code>smpl/SMPL_NEUTRAL.pkl</code> 與 <code>J_regressor_body25.npy</code>。<code>smpl-0901-send PATH --destination udp://HOST:9100 --fps 30</code> 可用 JSON/JSONL 做輸入重播測試。
