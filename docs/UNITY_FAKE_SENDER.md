# Unity Fake Sender（Conda／不使用 Docker）

此工具讓 Unity 脫離 Pipeline 與 GPU fitter 單獨測試。它重播 Bridge
曾實際送出的原始 UDP datagram：

- UDP 9095：SMV2（SMPL pose、root motion、Hand21、品質狀態）。
- UDP 9096：RSV1（原始 59 點、confidence、PTP timestamp、座標資訊）。

重播的是正式 Bridge 的相同 bytes，不是另外模擬一套 pose 邏輯，因此能用來
區分問題在 Pipeline／fitter，還是 Unity decoder／retargeting。

## 1. 安裝

```bash
cd ~/iii/to-smpl
conda activate smpl-0901
python -m pip install -e .
```

只會安裝到 `smpl-0901` Conda 環境；不要使用 `sudo pip`，也不需要 Docker。

## 2. 先錄一段真實資料

Pipeline 的 UDP 9100 只有 59 點，還沒有 SMPL rotations，不能直接當 Unity
輸入。第一次需執行一次：

```text
Pipeline UDP 9100 → Bridge fitter → 錄製 SMV2 + RSV1
```

若 Docker Bridge 正占用 9100，先只停止該 Bridge：

```bash
sudo docker stop to-smpl-bridge-1
# 整合 Compose 可能叫：
# sudo docker stop dt-pose-v26-bridge-1
```

保持 Pipeline 輸出 UDP 9100，再用 Conda 啟動 Bridge：

若 Dashboard 輸出目錄先前由 Docker 建立而屬於 `root`，只修正這個明確目錄
的權限，不要遞迴修改整個 repo：

```bash
sudo chown -R "$USER":"$(id -gn)" ~/iii/digital-twin-pose/artifacts/live_v26
```

```bash
cd ~/iii/to-smpl
conda activate smpl-0901

smpl-0901-bridge \
  --input udp://0.0.0.0:9100 \
  --smpl-dir ~/iii/to-smpl/models \
  --device cuda \
  --unity-host 127.0.0.1 \
  --unity-port 9095 \
  --raw-skeleton-host 127.0.0.1 \
  --raw-skeleton-port 9096 \
  --fit-profile upper-body \
  --fit-jsonl ~/iii/digital-twin-pose/artifacts/live_v26/smpl_fit.jsonl \
  --mesh-preview-json ~/iii/digital-twin-pose/artifacts/live_v26/smpl_mesh.json \
  --record-unity-packets local_recordings/factory_demo.jsonl
```

錄到需要的動作後按 `Ctrl+C`。即使沒有 Unity listener 也能錄。指定檔案
每次啟動會覆寫，以免混入不同 session。`local_recordings/` 已由 Git 忽略；
刻意不使用可能由 Docker 建成 `root:root` 的 `artifacts/`。

Dashboard 可以在錄製期間保持開啟。上例把 fit 與 mesh 寫到 Dashboard 的
`artifacts/live_v26/`；如果 Pipeline/Dashboard 使用自訂 `OUTPUT_DIR`，這兩個
參數也必須指向同一目錄。比較頁面的原始骨架與 SMPL 都來自同一筆 fit record，
Bridge 寫到其他目錄時畫面會停在舊幀。

### 確認錄製成功

錄製期間檔案大小與行數應持續增加：

```bash
watch -n 1 'ls -lh local_recordings/factory_demo.jsonl; wc -l local_recordings/factory_demo.jsonl'
```

停止 Bridge 後，用套件本身的 parser 驗證 schema、Base64、packet magic、長度與
時間順序，並列出兩種協定的封包數：

```bash
python - <<'PY'
from collections import Counter
from smpl_0901.unity_fake_sender import load_recording

events = load_recording("local_recordings/factory_demo.jsonl")
print("packets:", len(events))
print("protocols:", dict(Counter(event.protocol for event in events)))
print("duration_s:", round((events[-1].elapsed_ns - events[0].elapsed_ns) / 1e9, 3))
PY
```

正常錄製至少有 `RSV1`；Bridge 完成 fixed-beta 校正且成功 fitting 後也會有
`SMV2`。parser 無例外且兩者計數大於零，代表可以拿來重播完整 Unity 輸入。

## 3. 不開 Pipeline／Bridge，單獨重播

```bash
cd ~/iii/to-smpl
conda activate smpl-0901

smpl-0901-unity-fake \
  local_recordings/factory_demo.jsonl \
  --unity-host 192.168.200.1 \
  --unity-port 9095 \
  --raw-skeleton-port 9096 \
  --loop
```

- Unity 同機時用 `--unity-host 127.0.0.1`。
- Windows 經 VPN 時填目前 VPN/PPP IPv4。
- `--loop` 持續到 `Ctrl+C`；frame ID 每輪遞增，Unity 不會忽略第二輪。
- `--speed 2` 兩倍速；預設 `1` 保留錄製間隔。
- `--no-timing` 立即發送，只適合壓力測試。
- 移除 `--loop` 只播放一輪。

## 4. 判讀

- Fake sender 正常、正式串流異常：查 Pipeline、Bridge fitter 或安全門檻。
- Fake sender 也異常：查 Unity bind pose、座標轉換、decoder 或 retargeter。
- Unity 顯示 no UDP：查 Windows listener、防火牆、server route。

錄製 JSONL 每行只有相對時間、協定與 datagram Base64。重播不修改姿態數值；
循環時只重寫 SMV2／RSV1 header 的 uint32 frame ID。

## 5. 錄完後恢復正式 Docker Bridge

先在錄製用的 Conda Bridge terminal 按 `Ctrl+C`，確認沒有其他 process 占用
UDP 9100：

```bash
sudo ss -lunp | grep ':9100'
```

同一時間只能有一個 Bridge bind 9100。再從本 repo 啟動正式 Bridge；若要讓
相鄰 `digital-twin-pose` 的 Dashboard 繼續顯示即時 fit，必須每次 recreate 都
重新傳入相同輸出目錄：

```bash
cd ~/iii/to-smpl
sudo UNITY_HOST=192.168.200.1 \
  SMPL_OUTPUT_DIR=../digital-twin-pose/artifacts/live_v26 \
  docker compose up -d --force-recreate bridge
sudo docker compose logs -f --tail=100 bridge
```

`--force-recreate` 沒帶 `SMPL_OUTPUT_DIR` 時會回到本 repo 的
`artifacts/live/`；Bridge 仍會運作，但另一個目錄上的 Dashboard 只會看到舊幀。
