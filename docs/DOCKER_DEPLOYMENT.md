# SMPL 0901 Bridge Docker 部署手冊

本文件供公司環境安裝、啟動與維運。Compose 只管理 SMPL Bridge，不會啟動、停止或修改 Pipeline、Fake Sender、Dashboard 和 Unity。

## 1. 容器責任與資料流

~~~text
dt-pose Pipeline
  └─ UDP 9100 / JSON ─> smpl-0901-bridge container
                           ├─ UDP 9095 / SMV2 ─> Unity
                           └─ UDP 9096 / RSV1 ─> Unity or recorder
~~~

UDP 9100 同時接受 `dt-pose.pose3d/v1`（`joints`, `frame`, `timestamp_ns`, `units=m`, `layout=factory59`）與舊版 `factory_59pt_body_hands`。因此更新 Pipeline 後不需改 Compose command；Bridge 會依每包 schema 解析，auto 單位不會把新版米制資料再縮小 1000 倍。

Compose 使用 host network，因此：

- Bridge 直接 bind Linux host 的 UDP 9100；
- 不需要 Docker <code>ports:</code> mapping；
- 9095/9096 是從 Linux host 主動送往執行時指定的 Unity IP；
- SMPL models 由 host 唯讀掛載到 container 的 <code>/models</code>。

## 2. 支援平台與必要條件

目前預設 base image 是 <code>nvcr.io/nvidia/pytorch:26.02-py3</code>，部署目標為 NVIDIA GB10 / ARM64 Linux。請勿改回僅含 <code>sm_87</code> 的 wheel；Docker build 會檢查 PyTorch 編譯架構中至少包含一個 <code>sm_12x</code> target，否則立即失敗。

必要條件：

1. NVIDIA GPU driver 可正常運作。
2. Docker Engine。
3. Docker Compose v2，使用 <code>docker compose</code> 指令。
4. NVIDIA Container Toolkit，Docker 可使用 GPU。
5. 能連線到 <code>nvcr.io</code>；第一次 build 可能下載數 GB。
6. 合法取得的 SMPL model。

先確認環境：

~~~bash
uname -m
nvidia-smi
sudo docker version
sudo docker compose version
~~~

預設平台的 <code>uname -m</code> 應為 <code>aarch64</code>。公司主機若為 x86_64 或其他 NVIDIA 平台，必須選用相容的 PyTorch/CUDA base image並重新跑完整測試；Docker image 不能跨 CPU 架構直接共用。

NVIDIA Container Toolkit 的安裝與 daemon 設定屬主機管理範圍，應由公司系統管理員依作業系統版本處理。

## 3. 取得程式

~~~bash
git clone git@github.com:kk98033/to-smpl.git
cd to-smpl
git status
~~~

若公司使用 HTTPS：

~~~bash
git clone https://github.com/kk98033/to-smpl.git
cd to-smpl
~~~

## 4. 準備 SMPL models

模型不在 Git repository，也不會 COPY 進 Docker image。預設目錄必須是：

~~~text
to-smpl/
└── models/
    ├── J_regressor_body25.npy
    └── smpl/
        └── SMPL_NEUTRAL.pkl
~~~

檢查：

~~~bash
test -r models/J_regressor_body25.npy
test -r models/smpl/SMPL_NEUTRAL.pkl
~~~

若模型放在其他位置，啟動時透過 <code>SMPL_MODELS_DIR</code> 指定絕對路徑。Container 只會唯讀掛載該目錄。SMPL 模型受原始授權條款約束，部署人員必須自行確認公司的使用與散布權限。

## 5. 建置

<code>UNITY_HOST</code> 不參與 build，同一份 image 可在啟動時送往不同 Unity 電腦。

可以直接執行前置準備腳本（自動檢查模型與建置映像檔）：

~~~bash
./prepare-gx10.sh
~~~

或手動執行 Docker Compose 建置：

~~~bash
sudo docker compose build
~~~

需要重新抓取最新 base layers 時：

~~~bash
sudo docker compose build --pull
~~~

指定另一個已由公司驗證的 NVIDIA PyTorch base：

~~~bash
sudo BASE_IMAGE=nvcr.io/nvidia/pytorch:<tag> docker compose build
~~~

建置完成後確認：

~~~bash
sudo docker image inspect smpl-0901-bridge:gx10
~~~

第一次由舊的 <code>26.02-py3-igpu</code> 修正時，建議清除該次 build cache 影響：

~~~bash
sudo docker compose build --pull --no-cache
~~~

這不會修改主機的全域環境變數；它只會更新此 Compose 使用的 local Docker image 與 build cache。之後程式未改動時可回到一般的 <code>sudo docker compose build</code>。

## 6. 啟動時指定 Unity IP

### Unity 在另一台 Windows 電腦

先在 Windows 執行 <code>ipconfig</code> 找到 Bridge server 可路由到的 LAN 或 VPN IPv4，再啟動：

~~~bash
sudo UNITY_HOST=192.168.200.1 docker compose up -d
~~~

Compose 預設 `SMPL_FIT_PROFILE=upper-body`，適合下半身長期被機台遮擋的影片；膝／腳踝不參與 loss，腿部 rotation 保持上一幀。全身清楚可見時才切回：

~~~bash
sudo UNITY_HOST=192.168.200.1 SMPL_FIT_PROFILE=full \
  docker compose up -d --force-recreate bridge
~~~

每個成功擬合 frame 會寫至 `artifacts/live/smpl_fit.jsonl`。若 Dashboard 位於相鄰的 `digital-twin-pose` repo，啟動時共用它的輸出目錄：

~~~bash
sudo UNITY_HOST=192.168.200.1 \
  SMPL_OUTPUT_DIR=../digital-twin-pose/artifacts/live_v26 \
  docker compose up -d --build --force-recreate bridge
~~~

### Unity 與 Bridge 在同一台 Linux 主機

~~~bash
sudo UNITY_HOST=127.0.0.1 docker compose up -d
~~~

### Models 位於其他目錄

~~~bash
sudo UNITY_HOST=192.168.200.1 \
  SMPL_MODELS_DIR=/absolute/path/to/models \
  docker compose up -d
~~~

<code>UNITY_HOST</code> 是 runtime 設定，不會寫入 image。未設定時，Compose config 和 build 仍能執行，但 container 啟動後會立即停止並顯示缺少設定。這可避免公司部署時誤送到開發環境的固定 IP。

Windows、VPN 或 DHCP 位址改變後，不必 rebuild：

~~~bash
sudo docker compose down
sudo UNITY_HOST=<NEW_UNITY_IP> docker compose up -d
~~~

## 7. 日常維運

~~~bash
# 查看狀態
sudo docker compose ps

# 查看最近 100 行並持續追蹤
sudo docker compose logs -f --tail=100 bridge

# 沿用既有 container 中保存的 UNITY_HOST
sudo docker compose restart bridge

# 停止並移除 container；不刪 image 或 host models
sudo docker compose down
~~~

更新程式：

~~~bash
git pull --ff-only
sudo docker compose build
sudo UNITY_HOST=<UNITY_IP> docker compose up -d
~~~

執行 <code>down</code> 後再次 <code>up</code> 必須重新指定目前的 <code>UNITY_HOST</code>；只做 <code>restart</code> 則沿用 container 建立時保存的值。

## 8. 網路與防火牆

| 主機 | 方向 | UDP port | 用途 |
| --- | --- | ---: | --- |
| Bridge server | inbound | 9100 | 接收 Pipeline JSON；Pipeline 同機時不必對外開放 |
| Bridge server | outbound | 9095 | 發送 SMV2 |
| Bridge server | outbound | 9096 | 發送 RSV1 |
| Unity Windows | inbound | 9095、9096 | Unity receivers |

Windows 管理員 PowerShell：

~~~powershell
New-NetFirewallRule -DisplayName "SMPL UDP 9095-9096" -Direction Inbound -Protocol UDP -LocalPort 9095,9096 -Action Allow
~~~

Unity receivers 必須 bind <code>0.0.0.0:9095</code> 與 <code>0.0.0.0:9096</code>。若 Unity UI 有 Server IP filter，應填封包實際來源 IP；除錯時可先選 Accept Any IP。

Server 端觀察輸出：

~~~bash
sudo tcpdump -ni any 'udp and (dst port 9095 or dst port 9096)'
~~~

若使用 VPN，Windows 有 VPN IP 不代表 VPN 一定允許 server 主動發 UDP；路由、防火牆與 VPN policy 都必須允許。以 Windows 測試 listener 收到 magic <code>SMV2</code> 或 <code>RSV1</code> 才代表傳輸路徑完整。

## 9. 驗證成功

~~~bash
sudo docker compose ps
sudo docker compose logs -f bridge
~~~

正常 log 順序：

1. 顯示 input、Unity 與 Raw Skeleton 端點。
2. 收到 Pipeline JSON 後顯示 <code>calibrating 1/30</code> 至完成。
3. 顯示 <code>calibration complete</code>。
4. 定期顯示 <code>received</code>、<code>sent</code>、<code>raw_sent</code>、<code>raw_dropped</code>、<code>dropped</code> 與 residual。

判讀：

- <code>received=0</code>：9100 尚未收到 Pipeline JSON。
- <code>raw_sent</code> 增加：輸入 JSON 已解析，RSV1 已嘗試送出。
- 只有 RSV1、沒有 SMV2：可能仍在前 30 個有效 frame 校正，或該 frame 未通過 SMPL 品質閘門。
- UDP send 成功只表示資料交給 OS，不代表 Unity 已收到；最終仍應查看 Unity packet counter。

## 10. 常見問題

| 現象 | 處理 |
| --- | --- |
| container 顯示 UNITY_HOST missing | 用 <code>sudo UNITY_HOST=&lt;IP&gt; docker compose up -d</code> 重建 container |
| SMPL model not found | 檢查模型樹、讀取權限與 <code>SMPL_MODELS_DIR</code> |
| Docker permission denied | 使用 sudo，或由管理員正確設定 docker group |
| Docker 看不到 GPU | 檢查 driver、NVIDIA Container Toolkit 和 Compose 的 <code>gpus: all</code> |
| received=0 | 確認 Pipeline 目的端是同機 UDP 9100，並用 tcpdump 檢查 |
| tcpdump 有 9095/9096、Unity no UDP | 檢查 Unity bind、Server IP filter、Windows Firewall 與 VPN routing |
| person input incomplete | 檢查必要 Body17 點的 reliable/confidence 與非有限座標 |

完整 wire format、JSON schema、byte offset 與 decoder 使用方式請見 [UDP API](UDP_API.md)。
